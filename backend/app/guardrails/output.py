"""Output guardrails — schema, budget, grounding, and no-hallucinated-booking.

Checks are ordered cheap-first:
  1. Schema validation (deterministic Pydantic — free)
  2. Budget constraint (deterministic arithmetic — free)
  3. Grounding / faithfulness (large-tier LLM judge — expensive)
  4. No-hallucinated-booking structural seam (designed here, tested Phase 4)

The node short-circuits at the first failure: a schema error never reaches
the expensive LLM judge. Track false-block rate alongside block rate from day
one — over-blocking is just as bad as under-blocking.
"""

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.config import settings
from backend.app.llm import llm
from backend.app.orchestrator.state import GraphState
from backend.app.prompts.registry import get_prompt, render

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_verdict(passed: bool, failed_checks: list[str], detail: str) -> dict:
    return {"passed": passed, "failed_checks": failed_checks, "detail": detail}


# ---------------------------------------------------------------------------
# Check 1 — Schema validation (deterministic)
# ---------------------------------------------------------------------------

def validate_schema(state: GraphState) -> dict | None:
    """Return a failure verdict if structured outputs are malformed, else None."""
    from backend.app.orchestrator.nodes.budget import BudgetBreakdown

    summary = state.get("summary", "")
    if not summary or not summary.strip():
        return _make_verdict(False, ["schema"], "summary is empty")

    bd_raw = state.get("budget_breakdown")
    if bd_raw is not None:
        try:
            BudgetBreakdown(**bd_raw)
        except Exception as exc:
            return _make_verdict(False, ["schema"], f"budget_breakdown schema invalid: {exc}")

    return None  # passed


# ---------------------------------------------------------------------------
# Check 2 — Budget constraint (deterministic)
# ---------------------------------------------------------------------------

def validate_budget(state: GraphState) -> dict | None:
    """Return a failure verdict if the itinerary total exceeds the stated budget."""
    bd_raw = state.get("budget_breakdown")
    if bd_raw is None:
        return None  # no budget reasoning — nothing to check

    total_budget = bd_raw.get("total_budget", float("inf"))
    flight_cost = bd_raw.get("selected_flight_cost") or 0.0
    hotel_cost = bd_raw.get("selected_hotel_cost") or 0.0
    activities = bd_raw.get("estimated_activities") or 0.0
    total_cost = flight_cost + hotel_cost + activities

    if total_cost > total_budget:
        detail = (
            f"Total cost {total_cost:.0f} exceeds budget {total_budget:.0f} "
            f"(flight={flight_cost:.0f} hotel={hotel_cost:.0f} activities={activities:.0f})"
        )
        logger.warning("output_guardrail: budget exceeded — %s", detail)
        return _make_verdict(False, ["budget"], detail)

    return None  # passed


# ---------------------------------------------------------------------------
# Check 3 — Grounding / faithfulness (LLM judge, expensive)
# ---------------------------------------------------------------------------

def check_grounding(state: GraphState) -> dict | None:
    """Return a failure verdict if visa_answer contains ungrounded claims.

    Only runs when both visa_answer and rag_results are present — if there
    was no RAG call there is nothing to ground-check.
    """
    visa_answer = state.get("visa_answer")
    rag_results = state.get("rag_results")

    if not visa_answer or not rag_results:
        return None  # no RAG output to check

    # Build the source context (same format the synthesis prompt sees)
    context = "\n\n".join(
        f"[{i}] {r.get('text', '')}\nSource: {r.get('source_url', '')} "
        f"(verified {r.get('last_verified', '')})"
        for i, r in enumerate(rag_results, start=1)
    )

    p = get_prompt("guardrails/output_grounding")
    messages = [
        SystemMessage(content=render("guardrails/output_grounding")),
        HumanMessage(
            content=(
                f"Answer to evaluate:\n{visa_answer}\n\n"
                f"Retrieved sources:\n{context}"
            )
        ),
    ]
    try:
        response = llm.complete(p.tier, messages)
        parsed = json.loads(response.text.strip())
        grounded = bool(parsed.get("grounded", True))
        reason = str(parsed.get("reason", ""))
        ungrounded = list(parsed.get("ungrounded_claims", []))

        if not grounded:
            detail = f"Ungrounded claims detected: {ungrounded}. Reason: {reason}"
            logger.warning("output_guardrail: grounding failed — %s", detail)
            return _make_verdict(False, ["grounding"], detail)
    except Exception as exc:
        # Fail-open: parse error → don't block the response
        logger.warning("output_guardrail: grounding check parse error (%s), allowing", exc)

    return None  # passed


# ---------------------------------------------------------------------------
# Check 4 — No-hallucinated-booking seam (design only — tested in Phase 4)
# ---------------------------------------------------------------------------

def check_no_hallucinated_booking(state: GraphState) -> dict | None:
    """Structural rule: only the Booking/Action agent may assert a reservation.

    The Booking/Action agent does not exist until Phase 4, so this check
    always passes in Phase 3. The seam is wired now so Phase 4 can enforce
    it without touching the guardrail node.

    Rule: if the summary claims a confirmed reservation (booking ID, confirmed
    booking, etc.) but no confirmation_id exists in state, that is a violation.
    """
    # Phase 3: seam only — the Booking agent and confirmation_id aren't wired yet
    confirmation_id = state.get("confirmation_id")  # will be populated by Phase 4 Booking agent
    summary = state.get("summary", "")

    booking_claim_keywords = ["confirmed booking", "reservation confirmed", "booking id", "confirmation number"]
    claims_booking = any(kw in summary.lower() for kw in booking_claim_keywords)

    if claims_booking and not confirmation_id:
        detail = "Summary claims a confirmed booking without a confirmation_id from the Booking agent"
        logger.warning("output_guardrail: no-hallucinated-booking rule violated — %s", detail)
        return _make_verdict(False, ["no_hallucinated_booking"], detail)

    return None  # passed (or seam not triggered)


# ---------------------------------------------------------------------------
# Graph node
# ---------------------------------------------------------------------------

def output_guardrail_node(state: GraphState) -> dict:
    """Run all output checks, cheap-first. Writes output_verdict to state.

    A failed check short-circuits: later (more expensive) checks are skipped.
    The verdict drives the conditional edge: ok → END, reflect → reflection.
    """
    # 1. Schema (free)
    failure = validate_schema(state)
    if failure:
        logger.info("output_guardrail: schema check failed")
        return {"output_verdict": failure}

    # 2. Budget (free)
    failure = validate_budget(state)
    if failure:
        logger.info("output_guardrail: budget check failed")
        return {"output_verdict": failure}

    # 3. Grounding (LLM judge — only runs after deterministic pass)
    failure = check_grounding(state)
    if failure:
        logger.info("output_guardrail: grounding check failed")
        return {"output_verdict": failure}

    # 4. No-hallucinated-booking seam
    failure = check_no_hallucinated_booking(state)
    if failure:
        logger.info("output_guardrail: no-hallucinated-booking rule triggered")
        return {"output_verdict": failure}

    verdict = _make_verdict(True, [], "all checks passed")
    logger.info("output_guardrail: all checks passed")
    return {"output_verdict": verdict}


# ---------------------------------------------------------------------------
# Conditional edge router
# ---------------------------------------------------------------------------

def route_output(state: GraphState) -> str:
    """LangGraph conditional edge: 'reflect' if any check failed, 'ok' otherwise.

    'reflect' is only returned while reflection_attempts < cap. Once the cap
    is reached the loop exits gracefully and serves the last-corrected output.
    """
    verdict = state.get("output_verdict", {})
    if verdict.get("passed", True):
        return "ok"
    attempts = state.get("reflection_attempts", 0)
    if attempts >= settings.GUARDRAIL_MAX_REFLECTION_ATTEMPTS:
        logger.info(
            "route_output: reflection cap reached (%d/%d), degrading gracefully",
            attempts,
            settings.GUARDRAIL_MAX_REFLECTION_ATTEMPTS,
        )
        return "ok"
    return "reflect"
