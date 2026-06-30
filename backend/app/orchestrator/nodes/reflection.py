"""Self-reflection / critique-and-retry node (Phase 3, Step 6).

Graph cycle:
  assemble → output_guardrail → (ok → END)
                              → (reflect → reflection → output_guardrail → ...)

On a failed output guardrail the reflection node:
  1. Reads output_verdict to understand what failed.
  2. Calls a large-tier critique-and-fix LLM pass that returns both the
     critique AND a corrected output in one structured JSON response.
  3. Writes corrected summary / visa_answer back to state so the next
     output_guardrail pass validates the corrected version.
  4. Increments reflection_attempts — the cap is enforced by route_output
     in guardrails/output.py, which routes "ok" → END once the cap is hit.

Why critique-and-fix in one call (vs separate critique then regenerate):
  Two calls per attempt × 2 attempts = 4 extra large-tier calls per graph run.
  One call per attempt × 2 = 2. The combined call still produces a visible
  critique in state (→ trace) so the demo shows the self-correction clearly.

The failed verdict, critique, and corrected output are all visible as
separate fields in the LangSmith trace for this node's state update.
"""

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.config import settings
from backend.app.llm import llm
from backend.app.orchestrator.state import GraphState
from backend.app.prompts.registry import render

logger = logging.getLogger(__name__)

_PROMPT_ID = "orchestrator/self_reflection_critique"


def reflection_node(state: GraphState) -> dict:
    """Critique the failed output and return a corrected version.

    Returns state updates: critique, corrected summary/visa_answer,
    incremented reflection_attempts. route_output enforces the cap.
    """
    output_verdict = state.get("output_verdict", {})
    failed_checks = output_verdict.get("failed_checks", [])
    detail = output_verdict.get("detail", "")
    current_summary = state.get("summary", "")
    visa_answer = state.get("visa_answer") or ""
    rag_results = state.get("rag_results") or []
    attempts = state.get("reflection_attempts", 0)

    logger.info(
        "reflection_node: attempt %d — failed_checks=%s detail=%r",
        attempts + 1,
        failed_checks,
        detail[:120],
    )

    # Build source context so the model can ground its corrections
    source_context = ""
    if rag_results:
        source_context = "Available retrieved sources (ground your answer ONLY in these):\n" + "\n\n".join(
            f"[{i}] {r.get('text', '')}\nSource: {r.get('source_url', '')} "
            f"(verified {r.get('last_verified', '')})"
            for i, r in enumerate(rag_results, start=1)
        )

    human_content = (
        f"Failed quality checks: {failed_checks}\n"
        f"Failure reason: {detail}\n\n"
        f"Current assistant summary:\n{current_summary}\n\n"
        f"Current visa/advisory answer:\n{visa_answer or 'N/A'}\n"
    )
    if source_context:
        human_content += f"\n{source_context}\n"
    human_content += (
        "\nIdentify what is wrong, then produce a fully corrected version.\n"
        "Respond with valid JSON only — no markdown, no extra text:\n"
        '{"critique": "<what is wrong and why>", '
        '"corrected_summary": "<full corrected itinerary summary>", '
        '"corrected_visa_answer": "<corrected visa answer, or null if unchanged>"}'
    )

    messages = [
        SystemMessage(content=render(_PROMPT_ID)),
        HumanMessage(content=human_content),
    ]

    updates: dict = {"reflection_attempts": attempts + 1}

    try:
        response = llm.complete("large", messages)
        parsed = json.loads(response.text.strip())

        critique = str(parsed.get("critique", ""))
        corrected_summary = str(parsed.get("corrected_summary") or current_summary)
        corrected_visa = parsed.get("corrected_visa_answer")

        updates["critique"] = critique
        updates["summary"] = corrected_summary
        if corrected_visa:
            updates["visa_answer"] = str(corrected_visa)

        logger.info(
            "reflection_node: corrected — critique=%r",
            critique[:120],
        )

    except Exception as exc:
        logger.warning(
            "reflection_node: failed to parse LLM response (%s) — keeping original output",
            exc,
        )
        updates["critique"] = f"parse_error: {exc}"
        # Cap check: if this was the last allowed attempt, append a caveat
        if attempts + 1 >= settings.GUARDRAIL_MAX_REFLECTION_ATTEMPTS:
            caveat = (
                "\n\n*Note: Some information in this response could not be fully "
                "verified against retrieved sources. Please confirm details with "
                "official sources before travelling.*"
            )
            updates["summary"] = current_summary + caveat
            updates["degraded_flags"] = list(state.get("degraded_flags") or []) + [
                "reflection_parse_error"
            ]

    return updates
