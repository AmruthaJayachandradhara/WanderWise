"""Session memory — Phase 3 extended.

Loads the user profile AND the rolling session context (summary + pinned
constraints) into graph state at the start of every run.

Phase 3 additions vs Phase 2:
  - Loads session_summary and pinned_constraints from the in-memory session
    store (backed by summary.py; Step 8 replaces the store with SQLite).
  - Merges durable long-term preferences from the SQLite store (Step 8).
  - Preferences from long-term store overwrite the demo profile defaults.

Run as a graph node (not seeded in main.py's initial_state) so the eval
harness — which invokes the graph directly with only {user_id, query} —
gets the full context too, and the load is visible in traces.
"""

import logging

from backend.app.memory.longterm import load_longterm_prefs
from backend.app.memory.summary import get_session_context
from backend.app.orchestrator.state import GraphState
from backend.app.state.profile import get_profile

logger = logging.getLogger(__name__)


def load_profile_node(state: GraphState) -> dict:
    """Load the user profile + rolling session context into state."""
    user_id = state.get("user_id", "")
    profile = get_profile(user_id)

    # Long-term durable preferences from SQLite (cross-session)
    longterm_prefs = load_longterm_prefs(user_id)

    # Short-term rolling session context (in-memory: summary + pinned)
    session_ctx = get_session_context(user_id)
    session_summary = session_ctx.get("session_summary", "")
    # Merge order: demo profile < long-term SQLite < session pinned (most recent wins)
    pinned: dict = {**longterm_prefs, **session_ctx.get("pinned_constraints", {})}

    # Merge into profile preferences so downstream agents honour them
    preferences = {**dict(profile.preferences), **longterm_prefs}
    if "diet" in pinned:
        preferences["diet"] = pinned["diet"]

    logger.info(
        "Memory: user=%r airport=%s passport=%s budget=%.0f "
        "longterm_prefs=%s has_summary=%s pinned=%s",
        user_id,
        profile.home_airport,
        profile.passport_country,
        profile.budget_default,
        list(longterm_prefs.keys()),
        bool(session_summary),
        list(pinned.keys()),
    )

    return {
        "home_airport": profile.home_airport,
        "passport_country": profile.passport_country,
        "budget_default": profile.budget_default,
        "home_currency": profile.home_currency,
        "interests": profile.interests,
        "preferences": preferences,
        "session_summary": session_summary,
        "pinned_constraints": pinned,
    }
