"""One-shot: push/refresh LangSmith dashboard metrics (Phase 5, Step 6 of
docs/wanderwise_phase5.md).

Always does two things regardless of what the LangSmith account/plan
supports:
  1. Prints a console summary of the Step-7 aggregates (backend.app.
     observability.metrics) — this always works since it's just reading
     runs/feedback, and is useful on its own for a quick health check.
  2. Attempts best-effort custom chart creation via LangSmith's charts API
     for the five metric families. This API is marked legacy in LangSmith's
     docs and its availability varies by plan/region — on failure (401/403/
     404/405), this prints the exact manual dashboard-panel recipe instead
     of failing. Either way, screenshot the result for the README (Phase 6).

Usage:
    uv run python scripts/run_dashboards.py
"""

import logging
import sys

from backend.app.config import settings
from backend.app.logging_config import setup_logging
from backend.app.observability import metrics

setup_logging("INFO")
logger = logging.getLogger(__name__)

# (title, metric key, LangSmith metric name, filter description) — the five
# families from docs/wanderwise_phase5.md Step 6, plus the per-prompt panel.
_CHART_SPECS = [
    {
        "title": "WanderWise — Latency (p50/p95)",
        "chart_type": "line",
        "series": [{"metric": "latency_p50"}, {"metric": "latency_p95"}],
        "manual_recipe": (
            "Chart type: Line. Metric: Latency (p50 and p95). "
            "Filter: project=wanderwise, is_root=true."
        ),
    },
    {
        "title": "WanderWise — Token cost by tier",
        "chart_type": "bar",
        "series": [{"metric": "total_tokens", "group_by": "metadata.tier"}],
        "manual_recipe": (
            "Chart type: Bar, grouped by metadata.tier. Metric: Total tokens "
            "(or cost, if your plan exposes it). Filter: project=wanderwise, run_type=llm."
        ),
    },
    {
        "title": "WanderWise — Cache hit rate",
        "chart_type": "line",
        "series": [{"metric": "feedback_score_avg", "key": "cache_hit"}],
        "manual_recipe": (
            "Chart type: Line. Metric: % of root runs with output field "
            "cache_hit=true. Filter: project=wanderwise, is_root=true."
        ),
    },
    {
        "title": "WanderWise — Retry / degradation rate",
        "chart_type": "line",
        "series": [{"metric": "error_rate"}],
        "manual_recipe": (
            "Chart type: Line. Metric: % of root runs with a non-empty "
            "degraded_flags output field. Filter: project=wanderwise, is_root=true."
        ),
    },
    {
        "title": "WanderWise — Eval scores over time",
        "chart_type": "line",
        "series": [{"metric": "feedback_score_avg", "key": "faithfulness"},
                   {"metric": "feedback_score_avg", "key": "merge_quality"},
                   {"metric": "feedback_score_avg", "key": "helpfulness"}],
        "manual_recipe": (
            "Chart type: Line, one series per feedback key (faithfulness, "
            "merge_quality, helpfulness, grounding_label_agreement). "
            "Filter: project=wanderwise. This is populated automatically once "
            "judges.log_feedback() has written scores via run_prompt_eval.py --judge."
        ),
    },
    {
        "title": "WanderWise — Per-prompt eval score breakdown",
        "chart_type": "bar",
        "series": [{"metric": "feedback_score_avg", "group_by": "metadata.prompt_id"}],
        "manual_recipe": (
            "Chart type: Bar, grouped by metadata.prompt_id (and metadata.prompt_version "
            "as a secondary split if your plan supports it). Metric: average feedback score. "
            "This makes a prompt regression attributable to a specific prompt+version, "
            "e.g. 'faithfulness dropped on rag/synthesis v3, not on the retriever.'"
        ),
    },
]


def print_console_summary() -> None:
    print("=" * 70)
    print("WanderWise observability summary (last 7 days)")
    print("=" * 70)

    cost = metrics.cost_by_tier(7)
    if cost:
        print(f"Cost by tier (list-price equivalent): {cost.tier_cost_usd}")
        print(f"  Total: ${cost.total_cost_usd:.4f} vs. all-large counterfactual "
              f"${cost.all_large_counterfactual_usd:.4f} — {cost.savings_pct:.1f}% saved")
    else:
        print("Cost by tier: unavailable")

    cache = metrics.cache_hit_rate(7)
    print(f"Cache hit rate: {cache.rate:.1%} ({cache.hits}/{cache.total})" if cache else "Cache hit rate: unavailable")

    retry = metrics.retry_rate(7)
    if retry:
        print(f"Retry/degradation rate: {retry.rate:.1%} ({retry.degraded}/{retry.total}), "
              f"reflection rate: {retry.reflection_rate:.1%}")
    else:
        print("Retry rate: unavailable")

    latency = metrics.latency_stats(7)
    if latency:
        print(f"Latency: p50={latency.p50_ms:.0f}ms p95={latency.p95_ms:.0f}ms mean={latency.mean_ms:.0f}ms n={latency.count}")
    else:
        print("Latency: unavailable")

    scores = metrics.eval_scores_over_time(30)
    if scores and scores.scores:
        for key, points in scores.scores.items():
            print(f"Eval score '{key}': {len(points)} data point(s) over the last 30 days")
    else:
        print("Eval scores over time: no feedback recorded yet (run --judge nightly to populate)")
    print()


def try_create_charts() -> None:
    if not settings.LANGSMITH_API_KEY:
        print("LANGSMITH_API_KEY not set — skipping chart creation, printing manual recipes.\n")
        _print_manual_recipes()
        return

    try:
        from langsmith import Client
        client = Client()
    except Exception as exc:
        print(f"Could not construct LangSmith client ({exc}) — printing manual recipes.\n")
        _print_manual_recipes()
        return

    created, failed = 0, 0
    for spec in _CHART_SPECS:
        try:
            client.request_with_retries(
                "POST",
                "/charts",
                request_kwargs={"json": {
                    "title": spec["title"],
                    "chart_type": spec["chart_type"],
                    "series": spec["series"],
                }},
            )
            print(f"Created/updated chart: {spec['title']}")
            created += 1
        except Exception as exc:
            logger.warning("Chart creation failed for %r — %s", spec["title"], exc)
            failed += 1

    if failed:
        print(
            f"\n{failed}/{len(_CHART_SPECS)} chart(s) could not be created via the API "
            "(LangSmith's custom-dashboard API is marked legacy and its availability "
            "varies by plan/region — this is expected on some accounts). "
            "Manual setup recipe for the failed panels:\n"
        )
        _print_manual_recipes()
    else:
        print(f"\nAll {created} charts created/refreshed successfully.")


def _print_manual_recipes() -> None:
    print(
        "LangSmith's prebuilt per-project dashboard (Projects > wanderwise > "
        "Monitor tab) already shows run count, latency p50/p99, token usage, "
        "cost, and error rate with zero setup — start there. For the panels "
        "below, add a custom chart (Dashboards > New Dashboard > Add Chart):\n"
    )
    for spec in _CHART_SPECS:
        print(f"  - {spec['title']}\n      {spec['manual_recipe']}\n")
    print(
        "Screenshot the resulting dashboard(s) for the README (Phase 6 — "
        "the story survives an interview even if the live dashboard is "
        "mid-refresh)."
    )


def main() -> int:
    print_console_summary()
    try_create_charts()
    return 0


if __name__ == "__main__":
    sys.exit(main())
