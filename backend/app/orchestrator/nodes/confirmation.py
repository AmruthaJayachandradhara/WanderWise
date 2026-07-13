"""Confirmation gate + booking execution (Phase 4).

The gate is a GRAPH EDGE, not a model decision: confirmation_gate calls
langgraph's interrupt(), which pauses the run at a checkpoint and surfaces
the pending actions to the API layer. The graph only continues when the
user resumes with an explicit approve/decline — the high-risk path
structurally cannot complete without passing this node.

booking_execution is the ONLY place a BookingProvider executes. It runs
strictly after an approval and is the sole writer of confirmation_id —
the field the no-hallucinated-booking guardrail keys on.
"""

import logging

from langgraph.types import interrupt

from backend.app.booking.provider import ReservationRequest, get_provider
from backend.app.orchestrator.state import GraphState

logger = logging.getLogger(__name__)

# action_type → BookingProvider booking type
_BOOKING_TYPES = {
    "flight_booking": "flight",
    "hotel_booking": "hotel",
    "restaurant_reservation": "restaurant",
}


def route_action(state: GraphState) -> str:
    """After the action node: anything pending → the gate; else assemble."""
    return "confirm" if state.get("pending_actions") else "skip"


def confirmation_gate_node(state: GraphState) -> dict:
    """Pause the graph and ask the user to approve the pending actions."""
    decision = interrupt(
        {
            "pending_actions": state.get("pending_actions", []),
            "email_draft": state.get("email_draft"),
        }
    )
    approved = bool(decision.get("approved")) if isinstance(decision, dict) else bool(decision)
    if approved:
        logger.info("Confirmation gate: user APPROVED %d action(s)",
                    len(state.get("pending_actions", [])))
        return {"actions_approved": True}
    logger.info("Confirmation gate: user DECLINED — pending actions discarded")
    return {
        "actions_approved": False,
        "pending_actions": [],
        "email_status": "discarded",
    }


def route_confirmation(state: GraphState) -> str:
    return "execute" if state.get("actions_approved") else "skip"


def booking_execution_node(state: GraphState) -> dict:
    """Execute approved actions through their BookingProviders.

    reserve() then confirm() per action; every confirmation carries the
    provider-issued confirmation_id. Failures degrade per-action — one
    failed booking never aborts the rest.
    """
    user_id = state.get("user_id", "anon")
    confirmations: list[dict] = []
    degraded_flags = list(state.get("degraded_flags", []))
    email_status = state.get("email_status", "none")

    for action in state.get("pending_actions", []):
        action_type = action.get("action_type", "")
        if action_type == "email_send":
            # Approval releases the draft; actual SMTP delivery is out of
            # scope by design (no real send in Phase 4).
            email_status = "approved"
            continue

        booking_type = _BOOKING_TYPES.get(action_type)
        if booking_type is None:
            logger.warning("booking_execution: unknown action type %r", action_type)
            continue

        provider = get_provider(booking_type)
        req = ReservationRequest(
            booking_type=booking_type,
            offer_id=action.get("offer_id", ""),
            idempotency_key=f"{user_id}:{booking_type}:{action.get('offer_id', '')}",
            details=action.get("details", {}),
        )
        reserved = provider.reserve(req)
        if not reserved.success:
            logger.warning(
                "booking_execution: %s reserve failed: %s", booking_type, reserved.error
            )
            degraded_flags.append(f"booking_{booking_type}")
            continue

        confirmed = provider.confirm(reserved.data.reservation_id)
        if not confirmed.success:
            logger.warning(
                "booking_execution: %s confirm failed: %s", booking_type, confirmed.error
            )
            degraded_flags.append(f"booking_{booking_type}_confirm")
            continue

        confirmations.append(
            {
                "booking_type": booking_type,
                "provider": provider.provider_name,
                "reservation_id": reserved.data.reservation_id,
                "confirmation_id": confirmed.data.confirmation_id,
                "description": action.get("description", ""),
            }
        )
        logger.info(
            "booking_execution: %s confirmed via %s → %s",
            booking_type,
            provider.provider_name,
            confirmed.data.confirmation_id,
        )

    return {
        "confirmations": confirmations,
        "confirmation_id": confirmations[0]["confirmation_id"] if confirmations else None,
        "email_status": email_status,
        "degraded_flags": degraded_flags,
    }
