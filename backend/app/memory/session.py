"""Basic session memory — Phase 2.

Loads the user profile into graph state at the start of every run so that
downstream nodes (travel search, budget, RAG) read traveller facts from
state instead of re-prompting.

This is *basic* memory only:
  - read-only — no write-back / preference promotion (Phase 3 long-term memory)
  - no cross-request persistence — no Redis/Upstash here (Phase 3)
  - reloaded per graph run, keyed by user_id

Run as a graph node (not seeded in main.py's initial_state) so the eval
harness — which invokes the graph directly with only {user_id, query} —
gets the profile too, and so the load is visible as its own step in traces.
"""

import logging

from backend.app.orchestrator.state import GraphState
from backend.app.state.profile import get_profile

logger = logging.getLogger(__name__)


def load_profile_node(state: GraphState) -> dict:
    """Load the user profile into state. First node after START."""
    user_id = state.get("user_id", "")
    profile = get_profile(user_id)

    logger.info(
        "Memory: loaded profile for user_id=%r home_airport=%s passport=%s budget=%.0f %s",
        user_id,
        profile.home_airport,
        profile.passport_country,
        profile.budget_default,
        profile.home_currency,
    )

    return {
        "home_airport": profile.home_airport,
        "passport_country": profile.passport_country,
        "budget_default": profile.budget_default,
        "home_currency": profile.home_currency,
        "interests": profile.interests,
        "preferences": profile.preferences,
    }
