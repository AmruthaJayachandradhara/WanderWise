"""Eval harness — deterministic checks on the compiled graph (Phase 5: full suite).

Modes (per-case `mode` field, default "graph"):
  graph      — full graph.invoke(), as in Phases 1-4.
  retrieval  — calls backend.app.rag.retriever.retrieve() directly (bypasses
               the graph and the query-rewrite LLM call) to measure Hit@5.
  fault      — exercises the LLM client / weather tool in isolation with a
               mocked failure, to verify graceful degradation without
               spending live LLM quota.

Suites (per-case `suite` field): "ci" (fast, ~5 LLM calls total, runs on every
push) vs "nightly" (the full labeled surface, run nightly or locally). Select
via --suite {ci,nightly,all}.

Deterministic checks (Phases 1-4, unchanged):
  1. Router uses the declared tier; assemble uses the declared tier.
  2. Summary is non-empty (and is NOT the degraded-service stub — Phase 5
     removes the old "stub is OK" exemption now that Groq fallback is wired).
  3. expected_fields present and non-null.
  4. Budget validity (total <= total_budget) when expected_budget_valid=true.
  5. Guardrail block/false-block, aggregate rate thresholds.
  6. Decomposition fan-out (sub-query count + passport/destination subjects).
  7. Booking-gate narrative: confirmation_id present/absent per resume_approved.

Phase 5 additions:
  8. Retrieval Hit@5 aggregate (mode=retrieval cases).
  9. Routing accuracy aggregate (router/assemble tier match rate, not a hard
     per-case fail — Step 4 of docs/wanderwise_phase5.md).
 10. Decomposition correctness aggregate (structural: count + subjects).
 11. Temporal validity (selected_flight.departure_at / weather.daily dates /
     calendar_ics DTSTART<=DTEND, whichever the case actually produced).
 12. Fault-injection handling aggregate (mode=fault cases).

All thresholds are read from backend.app.config.settings.EVAL_* — the single
source shared with run_prompt_eval.py and report.py.

Exits non-zero if any case fails OR if any aggregate rate misses its threshold.
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from langgraph.types import Command

from backend.app.config import settings
from backend.app.logging_config import setup_logging
from backend.app.observability.tracing import init_tracing

setup_logging("INFO")
os.environ["LANGSMITH_TRACING"] = "false"
init_tracing()

from backend.app.orchestrator.graph import graph  # noqa: E402

logger = logging.getLogger(__name__)

DATASET_PATH = Path(__file__).parent / "dataset.jsonl"

# The exact stub text returned when all LLM retries + fallbacks are exhausted
# (backend/app/reliability/fallback.py:_DEGRADED_STUB). With Groq wired as a
# fallback provider (Phase 5), a real graph run should never surface this —
# if it does, that's a genuine outage, not something to wave through.
_STUB_TEXT = "[Service temporarily unavailable. Please try again shortly.]"


# ---------------------------------------------------------------------------
# Aggregate counters
# ---------------------------------------------------------------------------

class _Aggregates:
    def __init__(self) -> None:
        self.redteam_total = 0
        self.redteam_blocked = 0
        self.legitimate_total = 0
        self.legitimate_blocked = 0
        self.routing_total = 0
        self.routing_correct = 0
        self.decomp_total = 0
        self.decomp_correct = 0
        self.budget_total = 0
        self.budget_valid = 0
        self.temporal_total = 0
        self.temporal_valid = 0
        self.hit5_total = 0
        self.hit5_hits = 0
        self.fault_total = 0
        self.fault_handled = 0


# ---------------------------------------------------------------------------
# Decomposition subject matching (Step 3/4 of docs/wanderwise_phase5.md)
# ---------------------------------------------------------------------------

def _subject_match(actual: dict, expected: dict) -> bool:
    """Loose, case-insensitive substring match — decompose_node's LLM output
    isn't guaranteed to use the exact same string as the eval label (e.g.
    "India" vs "Indian"), so exact equality would be too brittle."""
    for key in ("passport", "destination"):
        if key not in expected:
            continue
        exp_val = str(expected[key]).strip().lower()
        act_val = str(actual.get(key, "")).strip().lower()
        if not exp_val or (exp_val not in act_val and act_val not in exp_val):
            return False
    return True


def _decomposition_correct(sub_queries: list[dict], case: dict) -> bool:
    expected_count = case.get("expected_sub_query_count")
    if expected_count is not None and len(sub_queries) != expected_count:
        return False
    expected_subjects = case.get("expected_sub_query_subjects")
    if expected_subjects:
        remaining = list(sub_queries)
        for expected in expected_subjects:
            match_idx = next(
                (i for i, actual in enumerate(remaining) if _subject_match(actual, expected)),
                None,
            )
            if match_idx is None:
                return False
            remaining.pop(match_idx)
        # When no explicit count is asserted, decompose_node may legitimately
        # split one subject into multiple sub-queries by "kind" (e.g. visa
        # vs. general guide, for a single traveler) — that's not a fan-out
        # bug. What WOULD be a bug is a sub-query for a subject nobody
        # expected at all, so every actual entry must match some expected
        # subject too (bidirectional coverage), just not 1:1.
        if expected_count is None:
            for actual in sub_queries:
                if not any(_subject_match(actual, expected) for expected in expected_subjects):
                    return False
    return True


# ---------------------------------------------------------------------------
# Temporal validity (Phase 5, Step 2 of docs/wanderwise_phase5.md)
# ---------------------------------------------------------------------------

def _check_temporal_validity(result: dict) -> tuple[bool, str]:
    """Check whichever dated artifacts this run actually produced.

    Returns (valid, detail). If expected_temporal_valid=true but none of
    selected_flight / weather.daily / calendar_ics are present, that's a
    failure — the case should have produced something checkable.
    """
    checked_any = False
    now = datetime.now(timezone.utc)

    selected_flight = result.get("selected_flight")
    if selected_flight and selected_flight.get("departure_at"):
        checked_any = True
        try:
            dep = datetime.fromisoformat(selected_flight["departure_at"].replace("Z", "+00:00"))
            if dep.tzinfo is None:
                dep = dep.replace(tzinfo=timezone.utc)
            if dep <= now:
                return False, f"selected_flight.departure_at {dep} is not in the future"
        except ValueError as exc:
            return False, f"selected_flight.departure_at unparseable: {exc}"

    weather = result.get("weather")
    if weather and weather.get("daily"):
        checked_any = True
        dates = [d["date"] for d in weather["daily"]]
        parsed = [datetime.strptime(d, "%Y-%m-%d") for d in dates]
        if parsed != sorted(parsed) or len(set(parsed)) != len(parsed):
            return False, f"weather.daily dates not strictly increasing: {dates}"

    calendar_ics = result.get("calendar_ics")
    if calendar_ics:
        checked_any = True
        try:
            from icalendar import Calendar
            cal = Calendar.from_ical(calendar_ics)
            for component in cal.walk("VEVENT"):
                dtstart = component.get("dtstart").dt
                dtend = component.get("dtend").dt
                if dtstart > dtend:
                    return False, f"VEVENT dtstart {dtstart} > dtend {dtend}"
        except Exception as exc:
            return False, f"calendar_ics unparseable: {exc}"

    if not checked_any:
        return False, "no dated artifact (selected_flight/weather/calendar_ics) present to check"
    return True, "ok"


# ---------------------------------------------------------------------------
# Retrieval mode (Phase 5, Hit@5)
# ---------------------------------------------------------------------------

def _run_retrieval_case(case: dict) -> tuple[bool, str]:
    """Call retrieve() directly, bypassing the graph and the query-rewrite
    LLM call (patched to identity) — zero LLM quota."""
    import backend.app.rag.retriever as retriever_module

    with patch.object(retriever_module, "_rewrite_query", side_effect=lambda q, ci, p: q):
        chunks = retriever_module.retrieve(
            case["query"], case["country_iso"], case.get("passport", "US"),
        )

    expected = case.get("expected_hit", {})
    exp_iso = expected.get("country_iso")
    exp_collection = expected.get("collection")
    hit = any(
        (exp_iso is None or c.country_iso == exp_iso)
        and (exp_collection is None or c.collection == exp_collection)
        for c in chunks
    )
    return hit, f"{len(chunks)} chunk(s) returned, hit={hit}"


# ---------------------------------------------------------------------------
# Fault-injection mode (Phase 5)
# ---------------------------------------------------------------------------
#
# These test the reliability layer (LLMClient retry/circuit/fallback) and the
# weather tool's degradation path directly, rather than through a full
# graph.invoke(). That keeps them fully deterministic and zero-LLM: router_
# tier/assemble_tier are hardcoded per-node constants (not LLM-derived, see
# Phase 1 note), so a full-graph run would add cost without adding signal —
# the reliability contract is exactly what LLMClient.complete()/weather_node
# expose directly.

def _run_fault_case(case: dict) -> tuple[bool, str]:
    from langchain_core.messages import HumanMessage, SystemMessage

    from backend.app.llm.client import llm as llm_singleton

    fault = case["fault"]
    messages = [SystemMessage(content="test"), HumanMessage(content=case["query"])]

    if fault in ("llm_error", "llm_429"):
        exc = (
            Exception("mocked total provider outage")
            if fault == "llm_error"
            else Exception("429 rate limit exceeded")
        )
        with (
            patch.object(llm_singleton._provider, "complete", side_effect=exc),
            patch.object(settings, "GROQ_API_KEY", None),
            patch.object(settings, "LLM_RETRY_ATTEMPTS", 1),
            patch.object(settings, "LLM_RETRY_BASE_DELAY", 0.0),
        ):
            try:
                response = llm_singleton.complete("small", messages)
            except Exception as inner:
                return False, f"unhandled exception: {inner}"
        if fault == "llm_429" and llm_singleton._circuit.state != "closed":
            return False, f"circuit should stay CLOSED on 429, got {llm_singleton._circuit.state}"
        handled = bool(response.text.strip()) and response.degraded
        return handled, f"degraded={response.degraded} fallback_used={response.fallback_used}"

    if fault == "circuit_open":
        for _ in range(settings.LLM_CIRCUIT_FAILURE_THRESHOLD):
            llm_singleton._circuit.record_failure()
        try:
            with patch.object(settings, "GROQ_API_KEY", None):
                response = llm_singleton.complete("small", messages)
        except Exception as inner:
            return False, f"unhandled exception: {inner}"
        finally:
            llm_singleton._circuit.record_success()  # reset for subsequent cases
        handled = bool(response.text.strip())
        return handled, f"degraded={response.degraded} fallback_used={response.fallback_used}"

    if fault == "tool_error":
        import backend.app.tools.weather as weather_module
        from backend.app.agents.weather import weather_node

        state = {"query": case["query"], "location": "Vienna"}
        with (
            patch.object(weather_module.WeatherTool, "_run", side_effect=RuntimeError("mocked weather API down")),
            patch.object(llm_singleton, "complete", side_effect=RuntimeError("mocked — force location fallback")),
        ):
            try:
                result = weather_node(state)
            except Exception as inner:
                return False, f"unhandled exception: {inner}"
        handled = result.get("degraded") is True and result.get("weather") is None
        return handled, f"degraded={result.get('degraded')} weather={result.get('weather')}"

    return False, f"unknown fault type: {fault!r}"


# ---------------------------------------------------------------------------
# Graph mode (Phases 1-4, extended)
# ---------------------------------------------------------------------------

def _run_graph_case(case: dict, agg: _Aggregates) -> bool:
    case_id = case["id"]
    config = {"configurable": {"thread_id": f"eval-{case_id}"}}

    try:
        result = graph.invoke(
            {"user_id": "eval-user", "query": case["query"]},
            config=config,
        )
        if "__interrupt__" in result:
            approved = case.get("resume_approved", True)
            logger.info(
                "[%s]: confirmation gate hit — resuming with approved=%s",
                case_id, approved,
            )
            result = graph.invoke(Command(resume={"approved": approved}), config=config)
    except Exception as exc:
        logger.error("FAIL [%s]: unhandled exception — %s", case_id, exc)
        return False

    case_failed = False

    # ── Guardrail block/false-block ─────────────────────────────────────
    if "expected_blocked" in case:
        expected = case["expected_blocked"]
        verdict = result.get("input_verdict", {})
        actual_blocked = not verdict.get("allowed", True)

        if expected is True:
            agg.redteam_total += 1
            if actual_blocked:
                agg.redteam_blocked += 1
                logger.info(
                    "PASS [%s]: correctly blocked — check=%s reason=%r",
                    case_id, verdict.get("checks", []), verdict.get("reason", ""),
                )
            else:
                logger.error(
                    "FAIL [%s]: expected_blocked=True but guardrail ALLOWED query (reason=%r)",
                    case_id, verdict.get("reason", ""),
                )
                return False
            # Blocked cases never reach router/assemble/summary — skip those checks.
            return True

        agg.legitimate_total += 1
        if actual_blocked:
            agg.legitimate_blocked += 1
            logger.error(
                "FAIL [%s]: false-block — legitimate query was incorrectly blocked (reason=%r)",
                case_id, verdict.get("reason", ""),
            )
            case_failed = True

    # ── PII redaction ────────────────────────────────────────────────────
    if "expected_pii_redacted" in case:
        actual = result.get("pii_redacted", False)
        if actual != case["expected_pii_redacted"]:
            logger.error(
                "FAIL [%s]: pii_redacted expected=%r got=%r",
                case_id, case["expected_pii_redacted"], actual,
            )
            case_failed = True

    # ── Semantic-cache shortcut ──────────────────────────────────────────
    # A cache hit serves a memoized summary without running router/plan/the
    # agents — router_tier, assemble_tier, sub_queries, confirmation_id are
    # never (re)populated this run. Expected behavior (Phase 3 caching), not
    # a regression: verify only that a cached summary was actually served.
    if result.get("cache_hit"):
        summary = result.get("summary", "")
        if not summary.strip():
            logger.error("FAIL [%s]: cache_hit=True but summary is empty", case_id)
            return False
        logger.info(
            "PASS [%s]: served from semantic cache (source=%s) — skipping downstream checks",
            case_id, result.get("cache_source"),
        )
        return not case_failed

    # ── Router / assemble tier → routing accuracy aggregate ─────────────
    if "expected_router_tier" in case or case.get("mode", "graph") == "graph":
        got_router = result.get("router_tier", "")
        exp_router = case.get("expected_router_tier", "small")
        agg.routing_total += 1
        if got_router == exp_router:
            agg.routing_correct += 1
        else:
            logger.error("FAIL [%s]: router_tier expected=%r got=%r", case_id, exp_router, got_router)
            case_failed = True

    if "expected_assemble_tier" in case:
        got_assemble = result.get("assemble_tier", "")
        exp_assemble = case["expected_assemble_tier"]
        agg.routing_total += 1
        if got_assemble == exp_assemble:
            agg.routing_correct += 1
        else:
            logger.error("FAIL [%s]: assemble_tier expected=%r got=%r", case_id, exp_assemble, got_assemble)
            case_failed = True

    # ── Summary non-empty, and not a degraded stub ──────────────────────
    summary = result.get("summary", "")
    if not summary.strip():
        logger.error("FAIL [%s]: summary is empty", case_id)
        case_failed = True
    elif _STUB_TEXT in summary:
        logger.error(
            "FAIL [%s]: summary is the degraded-service stub — Groq fallback should "
            "have absorbed this. A stub here means a genuine outage, not a pass.",
            case_id,
        )
        case_failed = True

    # ── expected_fields ──────────────────────────────────────────────────
    for field_name in case.get("expected_fields", []):
        if result.get(field_name) is None:
            logger.error("FAIL [%s]: expected field %r is missing/null", case_id, field_name)
            case_failed = True

    # ── Budget validity → aggregate ─────────────────────────────────────
    if case.get("expected_budget_valid"):
        agg.budget_total += 1
        bd = result.get("budget_breakdown")
        if bd is not None:
            flight_cost = bd.get("selected_flight_cost") or 0
            hotel_cost = bd.get("selected_hotel_cost") or 0
            activities = bd.get("estimated_activities") or 0
            total_cost = flight_cost + hotel_cost + activities
            budget = bd.get("total_budget", float("inf"))
            if total_cost <= budget:
                agg.budget_valid += 1
            else:
                logger.error(
                    "FAIL [%s]: budget exceeded — total_cost=%.0f > budget=%.0f",
                    case_id, total_cost, budget,
                )
                case_failed = True
        else:
            logger.error("FAIL [%s]: expected_budget_valid=True but no budget_breakdown", case_id)
            case_failed = True

    # ── Temporal validity → aggregate ───────────────────────────────────
    if case.get("expected_temporal_valid"):
        agg.temporal_total += 1
        valid, detail = _check_temporal_validity(result)
        if valid:
            agg.temporal_valid += 1
        else:
            logger.error("FAIL [%s]: temporal validity — %s", case_id, detail)
            case_failed = True

    # ── Decomposition → aggregate ────────────────────────────────────────
    if (
        "expected_min_sub_queries" in case
        or "expected_sub_query_count" in case
        or "expected_sub_query_subjects" in case
    ):
        sub_queries = result.get("sub_queries") or []
        agg.decomp_total += 1
        min_required = case.get("expected_min_sub_queries")
        if min_required is not None and len(sub_queries) < min_required:
            logger.error(
                "FAIL [%s]: expected >= %d sub_queries, got %d",
                case_id, min_required, len(sub_queries),
            )
            case_failed = True
        elif _decomposition_correct(sub_queries, case):
            agg.decomp_correct += 1
        else:
            logger.error(
                "FAIL [%s]: decomposition mismatch — expected count=%s subjects=%s, got %s",
                case_id, case.get("expected_sub_query_count"),
                case.get("expected_sub_query_subjects"), sub_queries,
            )
            case_failed = True

    # ── Booking-gate narrative ───────────────────────────────────────────
    if "expected_confirmation" in case:
        confirmation_id = result.get("confirmation_id")
        output_v = result.get("output_verdict", {})
        expect_confirmation = case["expected_confirmation"]
        if expect_confirmation and not confirmation_id:
            logger.error(
                "FAIL [%s]: expected a confirmation_id after gate approval, got none",
                case_id,
            )
            case_failed = True
        if not expect_confirmation and confirmation_id:
            logger.error(
                "FAIL [%s]: expected NO confirmation_id (declined), got %r",
                case_id, confirmation_id,
            )
            case_failed = True
        if expect_confirmation and "no_hallucinated_booking" in output_v.get("failed_checks", []):
            logger.error(
                "FAIL [%s]: no-hallucinated-booking gate fired despite a real confirmation_id=%r",
                case_id, confirmation_id,
            )
            case_failed = True

    if not case_failed:
        logger.info("PASS [%s]", case_id)
    return not case_failed


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------

def run_eval(suite: str = "ci", json_out: Path | None = None) -> int:
    """Run all eval cases for the given suite. Returns the number of failures."""
    all_cases = [json.loads(line) for line in DATASET_PATH.read_text().splitlines() if line.strip()]
    if suite == "all":
        cases = all_cases
    else:
        cases = [c for c in all_cases if c.get("suite", "ci") == suite]
    logger.info("Running %d eval case(s) (suite=%s)", len(cases), suite)

    failures = 0
    agg = _Aggregates()
    case_results: list[dict] = []

    for i, case in enumerate(cases):
        is_llm_free = case.get("llm_free", False)
        if i > 0 and not is_llm_free:
            time.sleep(settings.EVAL_LLM_COOLDOWN_S)

        case_id = case["id"]
        mode = case.get("mode", "graph")
        logger.info("--- Case: %s (mode=%s) ---", case_id, mode)

        if mode == "retrieval":
            agg.hit5_total += 1
            passed, detail = _run_retrieval_case(case)
            if passed:
                agg.hit5_hits += 1
            else:
                logger.error("FAIL [%s]: %s", case_id, detail)
                failures += 1
        elif mode == "fault":
            agg.fault_total += 1
            passed, detail = _run_fault_case(case)
            if passed:
                agg.fault_handled += 1
                logger.info("PASS [%s]: %s", case_id, detail)
            else:
                logger.error("FAIL [%s]: %s", case_id, detail)
                failures += 1
        else:
            passed = _run_graph_case(case, agg)
            if not passed:
                failures += 1

        case_results.append({"id": case_id, "mode": mode, "passed": passed})

    # ── Aggregate rate checks ────────────────────────────────────────────
    logger.info("")
    logger.info("=== Aggregate metrics ===")
    metrics: dict[str, dict] = {}

    def _report_rate(name: str, numerator: int, denominator: int, threshold: float, minimum: bool = True) -> None:
        nonlocal failures
        if denominator == 0:
            logger.info("%s: no cases — not computed", name)
            return
        rate = numerator / denominator
        ok = (rate >= threshold) if minimum else (rate < threshold)
        cmp = ">=" if minimum else "<"
        logger.info(
            "%s: %d/%d = %.0f%% (threshold %s%.0f%%) — %s",
            name, numerator, denominator, rate * 100, cmp, threshold * 100,
            "PASS" if ok else "FAIL",
        )
        metrics[name] = {"value": rate, "threshold": threshold, "passed": ok}
        if not ok:
            failures += 1

    _report_rate("block_rate", agg.redteam_blocked, agg.redteam_total, settings.EVAL_BLOCK_RATE_MIN)
    _report_rate(
        "false_block_rate", agg.legitimate_blocked, agg.legitimate_total,
        settings.EVAL_FALSE_BLOCK_RATE_MAX, minimum=False,
    )
    _report_rate("routing_accuracy", agg.routing_correct, agg.routing_total, settings.EVAL_ROUTING_ACCURACY_MIN)
    _report_rate("decomposition_correctness", agg.decomp_correct, agg.decomp_total, settings.EVAL_DECOMPOSITION_MIN)
    _report_rate("budget_validity", agg.budget_valid, agg.budget_total, settings.EVAL_BUDGET_VALIDITY_MIN)
    _report_rate("temporal_validity", agg.temporal_valid, agg.temporal_total, settings.EVAL_TEMPORAL_VALIDITY_MIN)
    _report_rate("retrieval_hit5", agg.hit5_hits, agg.hit5_total, settings.EVAL_RETRIEVAL_HIT5_MIN)
    _report_rate("fault_handling", agg.fault_handled, agg.fault_total, settings.EVAL_FAULT_HANDLING_MIN)

    logger.info("")
    logger.info("Eval complete: %d/%d cases passed", len(cases) - failures, len(cases))

    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps({
            "suite": suite,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_cases": len(cases),
            "failures": failures,
            "metrics": metrics,
            "cases": case_results,
        }, indent=2))
        logger.info("Wrote results to %s", json_out)

    return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the graph eval gate")
    parser.add_argument(
        "--suite", choices=["ci", "nightly", "all"], default="ci",
        help="Which suite to run (default: ci — fast, ~5 LLM calls).",
    )
    parser.add_argument("--json-out", type=Path, default=None, help="Write structured results to this path.")
    args = parser.parse_args()
    n_failures = run_eval(suite=args.suite, json_out=args.json_out)
    sys.exit(1 if n_failures else 0)
