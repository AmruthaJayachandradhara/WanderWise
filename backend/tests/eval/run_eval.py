"""Eval harness — deterministic checks on the compiled graph.

Phase 1 checks:
  1. Router uses the "small" tier (routing is cheap).
  2. Assemble uses the "large" tier (synthesis needs the stronger model).
  3. Summary is non-empty.
  4. No unhandled exception.

Exits non-zero if any case fails — this is the CI gate signal.
LLM-judge evals are Phase 5; deterministic checks are cheap and CI-safe.
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
# Disable tracing in eval runs to conserve LangSmith free-tier quota
os.environ["LANGSMITH_TRACING"] = "false"
init_tracing()

from backend.app.orchestrator.graph import graph  # noqa: E402

logger = logging.getLogger(__name__)

DATASET_PATH = Path(__file__).parent / "dataset.jsonl"


def run_eval() -> int:
    """Run all eval cases. Returns the number of failures."""
    cases = [json.loads(line) for line in DATASET_PATH.read_text().splitlines() if line.strip()]
    logger.info("Running %d eval cases", len(cases))

    failures = 0
    for i, case in enumerate(cases):
        if i > 0:
            # Brief pause between cases to stay within Gemini's rate limits
            time.sleep(5)
        case_id = case["id"]
        logger.info("--- Case: %s ---", case_id)
        try:
            result = graph.invoke({
                "user_id": "eval-user",
                "query": case["query"],
            })
        except Exception as exc:
            logger.error("FAIL [%s]: unhandled exception — %s", case_id, exc)
            failures += 1
            continue

        # Check router tier
        got_router = result.get("router_tier", "")
        exp_router = case.get("expected_router_tier", "small")
        if got_router != exp_router:
            logger.error(
                "FAIL [%s]: router_tier expected=%r got=%r",
                case_id, exp_router, got_router,
            )
            failures += 1

        # Check assemble tier
        got_assemble = result.get("assemble_tier", "")
        exp_assemble = case.get("expected_assemble_tier", "large")
        if got_assemble != exp_assemble:
            logger.error(
                "FAIL [%s]: assemble_tier expected=%r got=%r",
                case_id, exp_assemble, got_assemble,
            )
            failures += 1

        # Check summary is non-empty
        summary = result.get("summary", "")
        if not summary.strip():
            logger.error("FAIL [%s]: summary is empty", case_id)
            failures += 1

        if not (got_router != exp_router or got_assemble != exp_assemble or not summary.strip()):
            logger.info(
                "PASS [%s]: router=%s assemble=%s summary_len=%d",
                case_id, got_router, got_assemble, len(summary),
            )

    logger.info("Eval complete: %d/%d passed", len(cases) - failures, len(cases))
    return failures


if __name__ == "__main__":
    n_failures = run_eval()
    sys.exit(1 if n_failures else 0)
