"""Graph state schema — the two-way data contract for every node.

Designed multi-user from day one: user_id is threaded through the state
so adding real auth in Phase 2+ is purely additive (no schema change).

TypedDict is used because LangGraph works natively with it and the fields
stay plain Python — no Pydantic overhead on every state transition.

Do NOT shortcut this schema. The node boundaries and field names chosen
here are extended (not rebuilt) by every later phase.
"""

from typing import TypedDict


class GraphState(TypedDict, total=False):
    # --- Identity ---
    user_id: str        # FK thread for multi-user; seeded from request

    # --- Input ---
    query: str          # raw user query

    # --- Router output ---
    task_type: str      # Phase 1: always "weather"; more types in Phase 2+
    tier: str           # tier chosen for the lookup step ("small"/"large")
    location: str       # destination extracted by the router

    # --- Tool results ---
    weather: dict       # serialised WeatherForecast (or None on degraded)
    degraded: bool      # True if any tool returned a degraded result

    # --- Final output ---
    summary: str        # natural-language answer assembled from tool results

    # --- Observability ---
    run_id: str         # LangSmith run / trace id (set by the graph entrypoint)

    # --- Tier tracking (used by eval + LangSmith) ---
    router_tier: str    # tier used in the router node
    assemble_tier: str  # tier used in the assemble node
