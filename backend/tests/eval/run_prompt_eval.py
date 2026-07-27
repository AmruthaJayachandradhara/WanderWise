"""Per-prompt isolated eval runner.

Runs each prompt in isolation against its own eval dataset (declared in the
prompt's YAML under `eval.dataset`), checks the declared metric against the
declared threshold, and exits non-zero if any prompt is below threshold.

Usage:
    # Run a single prompt:
    python run_prompt_eval.py orchestrator/router_intent

    # Run all active prompts (CI mode: llm_judge prompts are SKIPPED by
    # default — they only run with --judge, off the PR path):
    python run_prompt_eval.py

    # Include llm_judge prompts, sampled (nightly mode):
    python run_prompt_eval.py --judge --sample 0.5

Metrics:
    schema_valid — if output_schema defined: parse as JSON and check required
                   fields are present; otherwise check the output is non-empty.
    exact_match  — parse output as JSON and compare against the case's
                   `expected` dict field-by-field.
    llm_judge    — dispatches to a hand-rolled judge (backend.tests.eval.judges)
                   keyed by prompt_id. Sampled and off the PR path by default
                   (Phase 5, Step 3 of docs/wanderwise_phase5.md) — a flaky
                   judge shouldn't fail an unrelated PR.

Exits non-zero if any prompt's pass rate is below its declared threshold.
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from backend.app.logging_config import setup_logging
from backend.app.observability.tracing import init_tracing

setup_logging("INFO")
os.environ["LANGSMITH_TRACING"] = "false"
init_tracing()

from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from langchain_core.tracers.context import collect_runs  # noqa: E402

from backend.app.config import settings  # noqa: E402
from backend.app.llm.client import llm  # noqa: E402
from backend.app.llm.parsing import parse_json_dict  # noqa: E402
from backend.app.prompts.registry import get_prompt, render  # noqa: E402
from backend.app.prompts.schema import PromptDefinition  # noqa: E402
from backend.tests.eval import judges  # noqa: E402

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parents[3]
CASES_BASE = Path(__file__).parent / "cases"

# Prompts whose metric is llm_judge and how to score their output. Each
# dispatcher takes (output, case) and returns a judges.JudgeResult.
_JUDGE_DISPATCH = {
    "guardrails/output_grounding": lambda output, case: judges.JudgeResult(
        score=1.0 if parse_json_dict(output, context="output_grounding").get("grounded")
        == case.get("expected", {}).get("grounded") else 0.0,
        passed=parse_json_dict(output, context="output_grounding").get("grounded")
        == case.get("expected", {}).get("grounded"),
        reasoning=(
            f"expected grounded={case.get('expected', {}).get('grounded')} "
            f"got={parse_json_dict(output, context='output_grounding').get('grounded')}"
        ),
        judge_key="grounding_label_agreement",
    ),
    "rag/synthesis": lambda output, case: judges.judge_faithfulness(
        answer=output, context=case["human_input"],
    ),
    "orchestrator/assemble_itinerary": lambda output, case: judges.judge_helpfulness(
        query=case["human_input"], summary=output,
    ),
}


def _discover_all_prompts() -> list[str]:
    """Walk the prompt library and return all active prompt IDs."""
    library = REPO_ROOT / "backend" / "app" / "prompts" / "library"
    ids = []
    for yaml_file in sorted(library.rglob("*.yaml")):
        rel = yaml_file.relative_to(library).with_suffix("")
        prompt_id = str(rel)
        try:
            p = get_prompt(prompt_id)
            if p.status == "active":
                ids.append(prompt_id)
        except Exception as exc:
            logger.warning("Skipping %s — could not load: %s", prompt_id, exc)
    return ids


def _check_schema_valid(output: str, p: PromptDefinition) -> tuple[bool, str]:
    """Return (passed, reason)."""
    if p.output_schema:
        try:
            parsed = json.loads(output.strip())
        except json.JSONDecodeError as exc:
            return False, f"output is not valid JSON: {exc}"
        required = p.output_schema.get("required", [])
        missing = [k for k in required if k not in parsed]
        if missing:
            return False, f"JSON missing required keys: {missing}"
        return True, "JSON valid with required keys"
    # No output_schema — just check non-empty
    if output.strip():
        return True, "non-empty output"
    return False, "output is empty"


def _check_exact_match(output: str, case: dict) -> tuple[bool, str]:
    """Parse output as JSON and compare against case['expected'] field-by-field."""
    expected = case.get("expected", {})
    try:
        parsed = json.loads(output.strip())
    except json.JSONDecodeError as exc:
        return False, f"output is not valid JSON: {exc}"
    mismatches = {k: (v, parsed.get(k)) for k, v in expected.items() if parsed.get(k) != v}
    if mismatches:
        return False, f"field mismatches: {mismatches}"
    return True, "all expected fields matched"


def run_prompt(prompt_id: str, *, use_judge: bool, sample_rate: float) -> tuple[int, list[dict]]:
    """Run per-prompt eval. Returns (failures, per_case_results)."""
    logger.info("=== Prompt eval: %s ===", prompt_id)
    p = get_prompt(prompt_id)

    if p.eval is None:
        logger.warning("Prompt %s has no eval config — skipping", prompt_id)
        return 0, []

    metric = p.eval.metric
    if metric == "llm_judge" and not use_judge:
        logger.info("Prompt %s is metric=llm_judge — skipped (pass --judge to include)", prompt_id)
        return 0, []

    cases_path = CASES_BASE / f"{prompt_id}.jsonl"
    if not cases_path.exists():
        logger.error("No eval cases found at %s", cases_path)
        return 1, []

    cases = [json.loads(line) for line in cases_path.read_text().splitlines() if line.strip()]
    if not cases:
        logger.warning("No cases in %s — skipping", cases_path)
        return 0, []

    if metric == "llm_judge":
        cases = judges.sample_cases(cases, sample_rate)

    logger.info(
        "Running %d case(s) for %s (metric=%s threshold=%.2f)",
        len(cases), prompt_id, metric, p.eval.threshold,
    )

    failures = 0
    total = len(cases)
    case_results: list[dict] = []

    for i, case in enumerate(cases):
        if i > 0:
            time.sleep(3)
        case_id = case["id"]
        try:
            system_prompt = render(prompt_id, **case.get("inputs", {}))
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=case["human_input"]),
            ]
            with collect_runs() as run_cb:
                response = llm.complete(p.tier, messages, json_mode=bool(p.output_schema))
            output = response.text.strip()
            run_id = str(run_cb.traced_runs[0].id) if run_cb.traced_runs else None
        except Exception as exc:
            logger.error("FAIL [%s/%s]: exception — %s", prompt_id, case_id, exc)
            failures += 1
            case_results.append({"id": case_id, "passed": False, "reason": str(exc)})
            continue

        if metric == "schema_valid":
            passed, reason = _check_schema_valid(output, p)
        elif metric == "exact_match":
            passed, reason = _check_exact_match(output, case)
        elif metric == "llm_judge":
            dispatch = _JUDGE_DISPATCH.get(prompt_id)
            if dispatch is None:
                passed, reason = False, f"no judge dispatcher registered for {prompt_id}"
            else:
                result = dispatch(output, case)
                passed, reason = result.passed, f"score={result.score:.2f} — {result.reasoning}"
                judges.log_feedback(run_id, result)
        else:
            passed, reason = False, f"unknown metric: {metric!r}"

        if passed:
            logger.info("PASS [%s/%s]: %s", prompt_id, case_id, reason)
        else:
            logger.error("FAIL [%s/%s]: %s | output=%r", prompt_id, case_id, reason, output[:200])
            failures += 1
        case_results.append({"id": case_id, "passed": passed, "reason": reason})

    pass_rate = (total - failures) / total if total else 1.0
    threshold = p.eval.threshold
    if pass_rate < threshold:
        logger.error(
            "BELOW THRESHOLD [%s]: pass_rate=%.2f threshold=%.2f (%d/%d failed)",
            prompt_id, pass_rate, threshold, failures, total,
        )
        return failures, case_results
    logger.info("PASSED [%s]: pass_rate=%.2f threshold=%.2f", prompt_id, pass_rate, threshold)
    return 0, case_results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the per-prompt eval gate")
    parser.add_argument("prompt_ids", nargs="*", help="Specific prompt IDs to run (default: auto-discover all active prompts)")
    parser.add_argument("--judge", action="store_true", help="Include metric=llm_judge prompts (off the PR path by default)")
    parser.add_argument("--sample", type=float, default=None, help="Sample rate for llm_judge cases (default: settings.JUDGE_SAMPLE_RATE)")
    parser.add_argument("--json-out", type=Path, default=None, help="Write structured results to this path")
    args = parser.parse_args()

    sample_rate = args.sample if args.sample is not None else settings.JUDGE_SAMPLE_RATE

    prompt_ids = args.prompt_ids or _discover_all_prompts()
    if not args.prompt_ids:
        logger.info("Discovered %d active prompt(s)", len(prompt_ids))

    total_failures = 0
    all_results: dict[str, list[dict]] = {}
    for prompt_id in prompt_ids:
        failures, case_results = run_prompt(prompt_id, use_judge=args.judge, sample_rate=sample_rate)
        total_failures += failures
        if case_results:
            all_results[prompt_id] = case_results

    if total_failures:
        logger.error("Per-prompt eval FAILED: %d failure(s) across prompts", total_failures)
    else:
        logger.info("Per-prompt eval PASSED: all prompts meet their thresholds")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "judge_included": args.judge,
            "total_failures": total_failures,
            "prompts": all_results,
        }, indent=2))
        logger.info("Wrote results to %s", args.json_out)

    return 1 if total_failures else 0


if __name__ == "__main__":
    sys.exit(main())
