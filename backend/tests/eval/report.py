"""Aggregate the latest deterministic + judge + observability scores into
docs/eval-report.md — a portfolio artifact and interview reference (Phase 5,
Step 8 of docs/wanderwise_phase5.md).

Usage:
    python backend/tests/eval/run_eval.py --suite all --json-out /tmp/graph.json
    python backend/tests/eval/run_prompt_eval.py --judge --json-out /tmp/prompts.json
    python backend/tests/eval/report.py /tmp/graph.json /tmp/prompts.json

Regeneration is idempotent — the same inputs always produce the same report
(modulo the "generated at" timestamp and observability window, which reflect
whatever's live in LangSmith at generation time).
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from backend.app.config import settings
from backend.app.observability import metrics

REPO_ROOT = Path(__file__).parents[3]
REPORT_PATH = REPO_ROOT / "docs" / "eval-report.md"

_METHODOLOGY = """## Methodology

WanderWise's eval suite splits into two tiers, on purpose:

- **Deterministic checks** (`run_eval.py`, `run_prompt_eval.py` without `--judge`)
  run on every push. They're cheap, free of LLM-judge cost, and never flaky —
  exactly what should gate a merge. They cover routing tier accuracy,
  retrieval Hit@5, decomposition structure, budget/temporal validity,
  guardrail block/false-block rates, and fault-injection handling.
- **LLM-as-judge checks** (`judges.py`, `run_prompt_eval.py --judge`) cover the
  quality dimensions that need a judge — faithfulness, decomposition merge
  quality, itinerary helpfulness. These are *sampled* and run *nightly*, off
  the PR path (`.github/workflows/eval-nightly.yml`), so a flaky judge call
  never blocks an unrelated PR, and the free-tier LLM/LangSmith quota isn't
  burned re-judging every case on every push.

The eval set is intentionally **small and honest** (~40 labeled cases) rather
than large and noisy — each case carries an explicit expected label, so every
check is objective. The methodology is the signal here, not the case count.

**Judges are hand-rolled**, not RAGAS: three small functions
(`judge_faithfulness`, `judge_merge_quality`, `judge_helpfulness` in
`backend/tests/eval/judges.py`) built directly on the project's own
provider-agnostic `LLMClient`. That keeps quota control, retries, and Groq
fallback for three prompts' worth of judging without pulling RAGAS's
dependency tree or building a second LLM-calling path outside the system's
existing reliability layer. The trade-off: less interview name-recognition
than RAGAS, in exchange for consistency with how every other LLM call in the
system is made, retried, and traced.
"""


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, text=True,
        ).strip()
    except Exception:
        return "unknown"


def _deterministic_table(graph_results: dict) -> str:
    metric_labels = {
        "block_rate": "Guardrail block rate",
        "false_block_rate": "Guardrail false-block rate",
        "routing_accuracy": "Routing tier accuracy",
        "decomposition_correctness": "Decomposition correctness",
        "budget_validity": "Budget validity",
        "temporal_validity": "Temporal validity",
        "retrieval_hit5": "Retrieval Hit@5",
        "fault_handling": "Fault-injection handling",
    }
    lines = [
        "## Deterministic metrics (gate every push)",
        "",
        "| Metric | Target | Current | CI-blocking | Status |",
        "|---|---|---|---|---|",
    ]
    metrics_dict = graph_results.get("metrics", {})
    for key, label in metric_labels.items():
        m = metrics_dict.get(key)
        if m is None:
            lines.append(f"| {label} | — | no cases | yes | not computed |")
            continue
        status = "PASS" if m["passed"] else "FAIL"
        lines.append(
            f"| {label} | {m['threshold']:.0%} | {m['value']:.0%} | yes | {status} |"
        )
    lines.append("")
    lines.append(
        f"Suite: `{graph_results.get('suite', '?')}` — "
        f"{graph_results.get('total_cases', 0)} cases, "
        f"{graph_results.get('failures', 0)} failure(s). "
        f"Generated: {graph_results.get('generated_at', '?')}"
    )
    return "\n".join(lines)


def _judge_table(prompt_results: dict) -> str:
    lines = [
        "",
        "## LLM-as-judge metrics (sampled, nightly, non-blocking)",
        "",
        "| Prompt | Metric | Threshold | Cases judged | Result |",
        "|---|---|---|---|---|",
    ]
    prompts = prompt_results.get("prompts", {})
    judge_prompts = {
        "guardrails/output_grounding": ("grounding_label_agreement", 1.00),
        "rag/synthesis": ("faithfulness", settings.EVAL_FAITHFULNESS_MIN),
        "orchestrator/assemble_itinerary": ("helpfulness", settings.EVAL_HELPFULNESS_MIN),
    }
    if not prompt_results.get("judge_included"):
        lines.append("| _(none — last run excluded `--judge`)_ | | | | |")
    else:
        for prompt_id, (metric_name, threshold) in judge_prompts.items():
            cases = prompts.get(prompt_id, [])
            if not cases:
                lines.append(f"| {prompt_id} | {metric_name} | {threshold:.2f} | 0 | not run |")
                continue
            passed = sum(1 for c in cases if c["passed"])
            result = "PASS" if passed == len(cases) else "FAIL"
            lines.append(f"| {prompt_id} | {metric_name} | {threshold:.2f} | {len(cases)} | {result} ({passed}/{len(cases)}) |")
    return "\n".join(lines)


def _per_prompt_table(prompt_results: dict) -> str:
    lines = [
        "",
        "## Per-prompt eval results",
        "",
        "| Prompt | Cases | Passed | Pass rate |",
        "|---|---|---|---|",
    ]
    prompts = prompt_results.get("prompts", {})
    if not prompts:
        lines.append("| _(no per-prompt results in the last run)_ | | | |")
    else:
        for prompt_id, cases in sorted(prompts.items()):
            passed = sum(1 for c in cases if c["passed"])
            rate = passed / len(cases) if cases else 0.0
            lines.append(f"| {prompt_id} | {len(cases)} | {passed} | {rate:.0%} |")
    return "\n".join(lines)


def _observability_section() -> str:
    lines = ["", "## Observability aggregates (last 7 days)", ""]
    cost = metrics.cost_by_tier(7)
    cache = metrics.cache_hit_rate(7)
    retry = metrics.retry_rate(7)
    latency = metrics.latency_stats(7)

    if cost is None and cache is None and retry is None and latency is None:
        lines.append(
            "_LangSmith unavailable (no API key configured, or the API call failed) "
            "— observability aggregates not computed this run._"
        )
        return "\n".join(lines)

    if cost:
        lines.append(
            f"- **Cost by tier** (list-price equivalent): "
            f"${cost.total_cost_usd:.4f} actual vs. ${cost.all_large_counterfactual_usd:.4f} "
            f"all-large counterfactual — **{cost.savings_pct:.1f}% saved** by routing to small tier."
        )
    if cache:
        lines.append(f"- **Cache hit rate**: {cache.rate:.1%} ({cache.hits}/{cache.total})")
    if retry:
        lines.append(
            f"- **Retry/degradation rate**: {retry.rate:.1%} ({retry.degraded}/{retry.total}), "
            f"quality-reflection rate: {retry.reflection_rate:.1%}"
        )
    if latency:
        lines.append(
            f"- **Latency**: p50={latency.p50_ms:.0f}ms, p95={latency.p95_ms:.0f}ms, "
            f"mean={latency.mean_ms:.0f}ms, n={latency.count}"
        )
    return "\n".join(lines)


def _sampling_policy_section() -> str:
    return f"""
## Sampling & free-tier policy

| Context | TRACE_SAMPLING | Rationale |
|---|---|---|
| Interactive/demo | 1.0 (full) | Every trace visible for a live walkthrough |
| Nightly eval (`eval-nightly.yml`) | 0.25 | Full 40-case suite + judge sampling generates real volume; sampled tracing respects LangSmith's free Developer-tier trace cap |
| PR-path CI (`ci.yml`) | 0 (off) | Fast, free, deterministic gate — tracing adds no signal to a pass/fail gate |

Judge sampling: `JUDGE_SAMPLE_RATE={settings.JUDGE_SAMPLE_RATE}` of eligible
cases per nightly run (seeded on the date, so the sample rotates day to day
for eventual full coverage rather than always judging the same subset).

Gemini free-tier limit: 1,500 requests/day. A full nightly run (~40 graph
cases, ~17 of which call the LLM, plus sampled judge calls) stays well under
that even without fallback. Groq is wired as a fallback provider so transient
429s during a burst (e.g. all 13 per-prompt suites plus the graph suite
running close together) are absorbed rather than surfaced as stubs.
"""


def generate_report(graph_json: Path | None, prompt_json: Path | None) -> str:
    graph_results = _load_json(graph_json) if graph_json else {}
    prompt_results = _load_json(prompt_json) if prompt_json else {}

    sections = [
        "# WanderWise Eval Report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()} — commit `{_git_sha()}`",
        "",
        _METHODOLOGY,
        _deterministic_table(graph_results) if graph_results else "## Deterministic metrics\n\n_(no graph eval results provided)_",
        _judge_table(prompt_results),
        _per_prompt_table(prompt_results),
        _observability_section(),
        _sampling_policy_section(),
    ]
    return "\n".join(sections) + "\n"


def main() -> int:
    args = sys.argv[1:]
    graph_json = Path(args[0]) if len(args) > 0 else None
    prompt_json = Path(args[1]) if len(args) > 1 else None

    report = generate_report(graph_json, prompt_json)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report)
    print(f"Wrote {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
