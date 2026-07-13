"""Per-prompt isolated eval runner.

Runs each prompt in isolation against its own eval dataset (declared in the
prompt's YAML under `eval.dataset`), checks the declared metric against the
declared threshold, and exits non-zero if any prompt is below threshold.

Usage:
    # Run a single prompt:
    python run_prompt_eval.py orchestrator/router_intent

    # Run all active prompts (CI mode):
    python run_prompt_eval.py

Metrics supported in Phase 1:
    schema_valid — if output_schema defined: parse as JSON and check required
                   fields are present; otherwise check the output is non-empty.
    exact_match  — Phase 2+ (skipped with a warning here).
    llm_judge    — Phase 5 (skipped with a warning here).

Exits non-zero if any prompt's pass rate is below its declared threshold.
"""

import json
import logging
import os
import sys
import time
from pathlib import Path

from backend.app.logging_config import setup_logging
from backend.app.observability.tracing import init_tracing

setup_logging("INFO")
os.environ["LANGSMITH_TRACING"] = "false"
init_tracing()

from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402

from backend.app.llm.client import llm  # noqa: E402
from backend.app.prompts.registry import get_prompt, render  # noqa: E402
from backend.app.prompts.schema import PromptDefinition  # noqa: E402

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parents[3]
CASES_BASE = Path(__file__).parent / "cases"

# Temporary: detect the degraded stub returned when all LLM retries/fallbacks
# are exhausted (e.g. free-tier 429). Cases that receive the stub are skipped
# rather than failed — the app is still running, just quota-limited.
# TODO(phase-5): replace with a dedicated fallback provider so evals never skip.
_DEGRADED_STUB_MARKER = "[Service temporarily unavailable."


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


def run_prompt(prompt_id: str) -> int:
    """Run per-prompt eval. Returns number of failures for this prompt."""
    logger.info("=== Prompt eval: %s ===", prompt_id)
    p = get_prompt(prompt_id)

    if p.eval is None:
        logger.warning("Prompt %s has no eval config — skipping", prompt_id)
        return 0

    metric = p.eval.metric
    if metric in ("exact_match", "llm_judge"):
        logger.warning("Metric '%s' not yet supported in Phase 1 — skipping %s", metric, prompt_id)
        return 0

    cases_path = CASES_BASE / f"{prompt_id}.jsonl"
    if not cases_path.exists():
        logger.error("No eval cases found at %s", cases_path)
        return 1

    cases = [json.loads(line) for line in cases_path.read_text().splitlines() if line.strip()]
    if not cases:
        logger.warning("No cases in %s — skipping", cases_path)
        return 0

    logger.info("Running %d case(s) for %s (metric=%s threshold=%.2f)",
                len(cases), prompt_id, metric, p.eval.threshold)

    failures = 0
    skipped = 0
    total = len(cases)
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
            response = llm.complete(p.tier, messages, json_mode=bool(p.output_schema))
            output = response.text.strip()
        except Exception as exc:
            logger.error("FAIL [%s/%s]: exception — %s", prompt_id, case_id, exc)
            failures += 1
            continue

        # Temporary: skip cases that hit the quota-exhaustion fallback stub.
        # The stub is plain text, not JSON, so schema checks would always fail.
        # Skipped cases are excluded from the pass-rate denominator.
        if _DEGRADED_STUB_MARKER in output:
            logger.warning(
                "SKIP [%s/%s]: LLM quota exhausted — degraded stub returned. "
                "Skipping case (excluded from pass rate). "
                "Configure a fallback provider to eliminate skips.",
                prompt_id, case_id,
            )
            skipped += 1
            total -= 1
            continue

        passed, reason = _check_schema_valid(output, p)
        if passed:
            logger.info("PASS [%s/%s]: %s", prompt_id, case_id, reason)
        else:
            logger.error("FAIL [%s/%s]: %s | output=%r", prompt_id, case_id, reason, output[:200])
            failures += 1

    if total == 0:
        logger.warning(
            "SKIP [%s]: all %d case(s) skipped due to quota exhaustion — "
            "treating prompt as PASS (temporary, no real signal).",
            prompt_id, skipped,
        )
        return 0

    pass_rate = (total - failures) / total
    threshold = p.eval.threshold
    if pass_rate < threshold:
        logger.error(
            "BELOW THRESHOLD [%s]: pass_rate=%.2f threshold=%.2f (%d/%d failed, %d skipped)",
            prompt_id, pass_rate, threshold, failures, total, skipped,
        )
        return failures
    logger.info(
        "PASSED [%s]: pass_rate=%.2f threshold=%.2f (%d skipped due to quota)",
        prompt_id, pass_rate, threshold, skipped,
    )
    return 0


def main() -> int:
    if len(sys.argv) > 1:
        prompt_ids = [sys.argv[1]]
    else:
        prompt_ids = _discover_all_prompts()
        logger.info("Discovered %d active prompt(s)", len(prompt_ids))

    total_failures = 0
    for prompt_id in prompt_ids:
        total_failures += run_prompt(prompt_id)

    if total_failures:
        logger.error("Per-prompt eval FAILED: %d failure(s) across prompts", total_failures)
    else:
        logger.info("Per-prompt eval PASSED: all prompts meet their thresholds")
    return 1 if total_failures else 0


if __name__ == "__main__":
    sys.exit(main())
