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

    # --- Profile (loaded by the memory node at the start of every run) ---
    home_airport: str               # origin airport for travel search
    passport_country: str           # nationality for visa/advisory RAG
    budget_default: float           # default trip budget from the profile
    home_currency: str              # currency the budget is stated in
    interests: list[str]            # interest tags (food, history, ...)
    preferences: dict[str, str]     # durable prefs (diet, seat, ...)

    # --- Router output ---
    task_type: str      # Phase 1: always "weather"; more types in Phase 2+
    tier: str           # tier chosen for the lookup step ("small"/"large")
    location: str       # destination extracted by the router

    # --- Tool results ---
    weather: dict       # serialised WeatherForecast (or None on degraded)
    degraded: bool      # True if any tool returned a degraded result

    # --- Travel search results ---
    flights: list[dict]         # serialised FlightOffer dicts (or None on degraded)
    flights_degraded: bool      # True if Duffel flight search degraded
    travel_search_tier: str     # tier used for arg extraction (eval + traces)
    hotels: list[dict]          # serialised HotelOffer dicts (or None on degraded)
    hotels_degraded: bool       # True if Duffel Stays search degraded

    # --- Plan node output ---
    agents_needed: list[str]    # agents dispatched this run (tracing metadata)
    plan_tier: str              # tier used by plan_node

    # --- Agent-symmetry tier tracking ---
    weather_extraction_tier: str  # tier for weather's own location extraction

    # --- RAG results ---
    rag_results: list[dict] | None  # serialised RetrievedChunk list
    visa_answer: str | None         # synthesised cited visa/advisory answer
    rag_tier: str                   # tier used by RAG synthesis
    rag_degraded: bool              # True if RAG pipeline degraded
    rag_stale: bool                 # True if any retrieved chunk exceeded its staleness threshold (Phase 4)

    # --- Budget reasoning ---
    budget_breakdown: dict | None   # serialised BudgetBreakdown (or None)
    selected_flight: dict | None    # chosen FlightOffer dict
    selected_hotel: dict | None     # chosen HotelOffer dict
    budget_tier: str                # tier used by budget_node

    # --- Final output ---
    summary: str        # natural-language answer assembled from tool results

    # --- Observability ---
    run_id: str         # LangSmith run / trace id (set by the graph entrypoint)

    # --- Tier tracking (used by eval + LangSmith) ---
    router_tier: str    # tier used in the router node
    assemble_tier: str  # tier used in the assemble node

    # --- Guardrail verdicts (Phase 3) ---
    input_verdict: dict          # {allowed, reason, categories, checks}
    output_verdict: dict         # {passed, failed_checks, detail}
    refusal_message: str         # set when input is blocked
    pii_redacted: bool           # True if any PII was scrubbed from query

    # --- Reliability (Phase 3) ---
    degraded_flags: list[str]    # accumulates which subsystems degraded

    # --- Self-reflection / quality retry (Phase 3) ---
    reflection_attempts: int     # bounded ≤ 2
    critique: str                # last critic feedback (trace-visible)

    # --- Session memory (Phase 3) ---
    session_summary: str         # rolling summary of older turns
    pinned_constraints: dict     # hard constraints never summarised away

    # --- Caching (Phase 3) ---
    cache_hit: bool              # True if answer served from semantic cache
    cache_source: str            # "semantic" | "api" | None

    # --- Booking & confirmations (Phase 4) ---
    # Only booking_execution (via a BookingProvider) may write these; the
    # no-hallucinated-booking guardrail gates summaries on their presence.
    confirmations: list[dict]        # all confirmed reservations this run
    confirmation_id: str | None      # primary confirmation (read by output guardrail)

    # --- Query decomposition (Phase 4) ---
    sub_queries: list[dict]          # [{query, passport, destination, kind}] for RAG fan-out
    decompose_tier: str              # tier used by the decompose node

    # --- Activities (Phase 4) ---
    restaurants: list[dict] | None   # Overpass restaurant results
    events: list[dict] | None        # Ticketmaster events (deep links only)
    selected_restaurant: dict | None # proposed reservation {venue_id, name, slot, ...}
    activities_degraded: bool        # True if both search sources degraded
    activities_tier: str             # tier used for selection reasoning

    # --- Actions & confirmation gate (Phase 4) ---
    booking_requested: bool          # query asked to book (set by decompose)
    pending_actions: list[dict]      # queued high-risk actions awaiting the gate
    actions_approved: bool | None    # user decision from the interrupt
    calendar_ics: str | None         # auto-generated .ics hold (low-risk)
    email_draft: dict | None         # {subject, body} — drafted, never auto-sent
    email_status: str                # "none" | "drafted" | "approved" | "discarded"
    action_tier: str                 # tier used by the action agent
