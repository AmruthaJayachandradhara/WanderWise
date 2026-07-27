"""Observability metrics aggregation (Phase 5) — turns the per-run trace
fields captured since Phase 1 (tier, model, tokens, latency) plus the
cache/retry/guardrail flags added in Phase 3 into the aggregates the
LangSmith dashboards (scripts/run_dashboards.py) and the eval report
(backend/tests/eval/report.py) need.

Nothing here is new instrumentation — trace_metadata() has recorded
tier/model on every LLM call since Phase 1 Step 3, and GraphState has
carried cache_hit/degraded_flags/reflection_attempts since Phase 3. This
module only queries and aggregates what already exists.

Read-only: never called from the request-serving path, only from eval/
dashboard tooling. Every public function degrades to None (with a logged
warning) if LANGSMITH_API_KEY isn't set or the LangSmith API call fails —
a missing dashboard metric must never break the caller.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from backend.app.config import settings

logger = logging.getLogger(__name__)

# List-price-equivalent USD per 1M tokens (input, output). Gemini free-tier
# usage is actually free — this is a notional "if this were metered" price
# used only to quantify the routing layer's savings, not a real bill.
_TIER_PRICING_PER_1M: dict[str, tuple[float, float]] = {
    "small": (0.075, 0.30),   # gemini-flash-lite list price
    "large": (0.30, 2.50),    # gemini-flash list price
}


def _get_client():
    """Return a langsmith.Client, or None if unavailable/unconfigured."""
    if not settings.LANGSMITH_API_KEY:
        logger.warning("metrics: LANGSMITH_API_KEY not set — metric unavailable")
        return None
    try:
        from langsmith import Client
        return Client()
    except Exception as exc:
        logger.warning("metrics: failed to construct LangSmith client — %s", exc)
        return None


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


@dataclass
class CostByTier:
    tier_tokens: dict[str, tuple[int, int]] = field(default_factory=dict)  # tier -> (input, output)
    tier_cost_usd: dict[str, float] = field(default_factory=dict)
    total_cost_usd: float = 0.0
    all_large_counterfactual_usd: float = 0.0  # cost if every call had used "large"
    savings_pct: float = 0.0


def cost_by_tier(days: int = 7) -> CostByTier | None:
    """Token cost by tier — the routing-savings story (Flash-Lite vs Flash spend).

    Also computes an "all-large counterfactual": what the same token volume
    would have cost if every call had gone to the large tier, so the
    routing layer's savings are legible as a percentage.
    """
    client = _get_client()
    if client is None:
        return None
    try:
        tier_tokens: dict[str, list[int]] = {}
        for run in client.list_runs(
            project_name=settings.LANGSMITH_PROJECT,
            run_type="llm",
            start_time=_since(days),
        ):
            metadata = (run.extra or {}).get("metadata", {}) if run.extra else {}
            tier = metadata.get("tier")
            if not tier:
                continue
            in_tok = getattr(run, "prompt_tokens", None) or 0
            out_tok = getattr(run, "completion_tokens", None) or 0
            bucket = tier_tokens.setdefault(tier, [0, 0])
            bucket[0] += in_tok
            bucket[1] += out_tok

        result = CostByTier()
        total_in = total_out = 0
        for tier, (in_tok, out_tok) in tier_tokens.items():
            result.tier_tokens[tier] = (in_tok, out_tok)
            in_price, out_price = _TIER_PRICING_PER_1M.get(tier, _TIER_PRICING_PER_1M["large"])
            cost = (in_tok / 1_000_000) * in_price + (out_tok / 1_000_000) * out_price
            result.tier_cost_usd[tier] = round(cost, 4)
            result.total_cost_usd += cost
            total_in += in_tok
            total_out += out_tok

        large_in_price, large_out_price = _TIER_PRICING_PER_1M["large"]
        result.all_large_counterfactual_usd = round(
            (total_in / 1_000_000) * large_in_price + (total_out / 1_000_000) * large_out_price, 4,
        )
        result.total_cost_usd = round(result.total_cost_usd, 4)
        if result.all_large_counterfactual_usd > 0:
            result.savings_pct = round(
                100 * (1 - result.total_cost_usd / result.all_large_counterfactual_usd), 1,
            )
        return result
    except Exception as exc:
        logger.warning("cost_by_tier: query failed — %s", exc)
        return None


@dataclass
class CacheHitRate:
    hits: int = 0
    total: int = 0
    rate: float = 0.0
    by_source: dict[str, int] = field(default_factory=dict)


def cache_hit_rate(days: int = 7) -> CacheHitRate | None:
    """Semantic + API cache hit rate from root graph-run outputs."""
    client = _get_client()
    if client is None:
        return None
    try:
        result = CacheHitRate()
        for run in client.list_runs(
            project_name=settings.LANGSMITH_PROJECT,
            is_root=True,
            start_time=_since(days),
        ):
            result.total += 1
            outputs = run.outputs or {}
            if outputs.get("cache_hit"):
                result.hits += 1
                source = outputs.get("cache_source") or "unknown"
                result.by_source[source] = result.by_source.get(source, 0) + 1
        result.rate = round(result.hits / result.total, 4) if result.total else 0.0
        return result
    except Exception as exc:
        logger.warning("cache_hit_rate: query failed — %s", exc)
        return None


@dataclass
class RetryRate:
    total: int = 0
    degraded: int = 0
    rate: float = 0.0
    by_flag: dict[str, int] = field(default_factory=dict)
    reflection_rate: float = 0.0


def retry_rate(days: int = 7) -> RetryRate | None:
    """Infra retry/fallback rate (degraded_flags) and quality-retry rate
    (reflection_attempts > 0), from root graph-run outputs."""
    client = _get_client()
    if client is None:
        return None
    try:
        result = RetryRate()
        reflected = 0
        for run in client.list_runs(
            project_name=settings.LANGSMITH_PROJECT,
            is_root=True,
            start_time=_since(days),
        ):
            result.total += 1
            outputs = run.outputs or {}
            flags = outputs.get("degraded_flags") or []
            if flags:
                result.degraded += 1
                for flag in flags:
                    key = flag.split(":")[0]  # e.g. "retry_exhausted:RuntimeError" -> "retry_exhausted"
                    result.by_flag[key] = result.by_flag.get(key, 0) + 1
            if (outputs.get("reflection_attempts") or 0) > 0:
                reflected += 1
        result.rate = round(result.degraded / result.total, 4) if result.total else 0.0
        result.reflection_rate = round(reflected / result.total, 4) if result.total else 0.0
        return result
    except Exception as exc:
        logger.warning("retry_rate: query failed — %s", exc)
        return None


@dataclass
class LatencyStats:
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    mean_ms: float = 0.0
    count: int = 0


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, int(len(sorted_vals) * pct))
    return sorted_vals[idx]


def latency_stats(days: int = 7) -> LatencyStats | None:
    """End-to-end latency distribution from root graph-run start/end times."""
    client = _get_client()
    if client is None:
        return None
    try:
        durations_ms: list[float] = []
        for run in client.list_runs(
            project_name=settings.LANGSMITH_PROJECT,
            is_root=True,
            start_time=_since(days),
        ):
            if run.start_time and run.end_time:
                durations_ms.append((run.end_time - run.start_time).total_seconds() * 1000)
        if not durations_ms:
            return LatencyStats()
        durations_ms.sort()
        return LatencyStats(
            p50_ms=round(_percentile(durations_ms, 0.50), 1),
            p95_ms=round(_percentile(durations_ms, 0.95), 1),
            mean_ms=round(sum(durations_ms) / len(durations_ms), 1),
            count=len(durations_ms),
        )
    except Exception as exc:
        logger.warning("latency_stats: query failed — %s", exc)
        return None


@dataclass
class EvalScoresOverTime:
    # {feedback_key: [(date_iso, score, prompt_id, prompt_version), ...]}
    scores: dict[str, list[tuple[str, float, str | None, int | None]]] = field(default_factory=dict)


def eval_scores_over_time(days: int = 30) -> EvalScoresOverTime | None:
    """Judge feedback scores (faithfulness/merge_quality/helpfulness/
    grounding_label_agreement) grouped by day and by the run's
    prompt_id/prompt_version metadata — makes prompt regressions
    attributable (Step 6 of docs/wanderwise_phase5.md)."""
    client = _get_client()
    if client is None:
        return None
    try:
        run_ids = [
            run.id
            for run in client.list_runs(
                project_name=settings.LANGSMITH_PROJECT,
                start_time=_since(days),
            )
        ]
        if not run_ids:
            return EvalScoresOverTime()

        run_meta: dict[str, tuple[str | None, int | None]] = {}
        result = EvalScoresOverTime()
        for feedback in client.list_feedback(run_ids=run_ids):
            key = feedback.key
            score = feedback.score
            if score is None:
                continue
            run_id = str(feedback.run_id)
            if run_id not in run_meta:
                try:
                    run = client.read_run(feedback.run_id)
                    metadata = (run.extra or {}).get("metadata", {}) if run.extra else {}
                    run_meta[run_id] = (metadata.get("prompt_id"), metadata.get("prompt_version"))
                except Exception:
                    run_meta[run_id] = (None, None)
            prompt_id, prompt_version = run_meta[run_id]
            date_iso = feedback.created_at.date().isoformat() if feedback.created_at else "unknown"
            result.scores.setdefault(key, []).append((date_iso, score, prompt_id, prompt_version))
        return result
    except Exception as exc:
        logger.warning("eval_scores_over_time: query failed — %s", exc)
        return None
