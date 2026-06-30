"""Short-term rolling session summary (Phase 3, Step 7).

Keeps multi-turn sessions within the context window without silently dropping
constraints the user stated early.

Design:
  - Conversation turns are stored per user_id in _SESSION_STORE (in-memory
    for Phase 3; Step 8 replaces the backing store with SQLite).
  - Once MAX_RAW_TURNS accumulate, the oldest half are compressed by a
    small-tier LLM into session_summary.
  - Hard constraints (budget, diet, passports, group, seat) are extracted
    from every turn and kept in pinned_constraints — they are NEVER
    compressed and are always re-injected verbatim into context.

The failure mode this prevents: summarising away "my budget is $3000" stated
in turn 1, then generating an over-budget itinerary in turn 10.
"""

import json
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.llm import llm

logger = logging.getLogger(__name__)

# Roll older turns into a summary once this many raw turns accumulate
MAX_RAW_TURNS = 6
# Keep this many recent turns raw (never compress the most recent N)
KEEP_RECENT_TURNS = 2

# Regex keywords that suggest a turn might contain a user constraint
_CONSTRAINT_SIGNALS = re.compile(
    r"\b(vegetarian|vegan|halal|kosher|gluten|allerg|budget|passport|citizen|"
    r"nationality|aisle|window|business class|first class|solo|couple|family|"
    r"child|kid|infant|wheelchair|dietary|prefer)\b",
    re.IGNORECASE,
)

# In-memory backing store: user_id → session data
# Step 8 replaces this with SQLite reads/writes via longterm_store.
_SESSION_STORE: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Constraint extraction
# ---------------------------------------------------------------------------

def _extract_constraints_llm(texts: list[str]) -> dict:
    """Call a small-tier LLM to extract hard constraints from conversation text."""
    combined = "\n".join(texts)
    messages = [
        SystemMessage(
            content=(
                "You are an information extractor. Extract any hard travel constraints "
                "stated by the user. Return ONLY a JSON object with these optional keys "
                "(omit keys that aren't mentioned): "
                "diet (string), budget (string e.g. '3000 USD'), "
                "passports (list of country codes), group (string), seat (string), "
                "other_constraints (list of strings). "
                "If no constraints exist return {}."
            )
        ),
        HumanMessage(content=combined),
    ]
    try:
        response = llm.complete("small", messages)
        parsed = json.loads(response.text.strip())
        return {k: v for k, v in parsed.items() if v}
    except Exception as exc:
        logger.warning("extract_constraints: failed (%s), returning {}", exc)
        return {}


def extract_constraints(texts: list[str]) -> dict:
    """Extract hard constraints from user utterances.

    Cheap regex pre-screen avoids LLM calls on turns with no constraint signal.
    """
    relevant = [t for t in texts if _CONSTRAINT_SIGNALS.search(t)]
    if not relevant:
        return {}
    return _extract_constraints_llm(relevant)


# ---------------------------------------------------------------------------
# Rolling summary
# ---------------------------------------------------------------------------

def roll_summary(turns: list[dict], existing_summary: str, pinned: dict) -> str:
    """Compress old turns into a running summary, excluding pinned constraints.

    Pinned constraints are stored separately and injected verbatim — they
    must NOT be included in what gets summarised (they'd be at risk of
    paraphrase/omission during compression).
    """
    if not turns:
        return existing_summary

    turns_text = "\n".join(
        f"User: {t.get('query', '')}\nAssistant: {t.get('response', '')}"
        for t in turns
    )
    prior = f"\nPrior summary: {existing_summary}" if existing_summary else ""

    messages = [
        SystemMessage(
            content=(
                "You are summarising a travel planning conversation. "
                "Write a concise factual summary (3-5 sentences) of what was "
                "discussed. Do NOT include budget amounts, dietary requirements, "
                "or passport details — those are tracked separately. "
                "Focus on: destinations discussed, trip ideas explored, "
                "options considered and rejected."
            )
        ),
        HumanMessage(content=f"{prior}\n\nNew turns to summarise:\n{turns_text}"),
    ]
    try:
        response = llm.complete("small", messages)
        return response.text.strip()
    except Exception as exc:
        logger.warning("roll_summary: LLM failed (%s), appending plain text", exc)
        return (existing_summary + " " + turns_text[:500]).strip()


# ---------------------------------------------------------------------------
# Session store API
# ---------------------------------------------------------------------------

def _get_store(user_id: str) -> dict:
    if user_id not in _SESSION_STORE:
        _SESSION_STORE[user_id] = {
            "turns": [],
            "session_summary": "",
            "pinned_constraints": {},
        }
    return _SESSION_STORE[user_id]


def get_session_context(user_id: str) -> dict:
    """Return {session_summary, pinned_constraints} to inject into graph state.

    Both fields are empty/null for a fresh session — this is always safe to call.
    """
    store = _get_store(user_id)
    return {
        "session_summary": store["session_summary"],
        "pinned_constraints": dict(store["pinned_constraints"]),
    }


def add_turn(user_id: str, query: str, response: str) -> None:
    """Store a completed turn, extract constraints, and roll summary if needed.

    Called after a successful graph run (from session_update_node).
    Degrade-safe: any failure logs a warning but never raises.
    """
    try:
        store = _get_store(user_id)

        # Extract constraints from this turn and merge into pinned
        new_constraints = extract_constraints([query, response])
        if new_constraints:
            store["pinned_constraints"].update(new_constraints)
            logger.info(
                "session: extracted constraints for user=%r: %s",
                user_id, list(new_constraints.keys()),
            )

        # Append turn
        store["turns"].append({"query": query, "response": response})

        # Roll if we've accumulated too many raw turns
        if len(store["turns"]) > MAX_RAW_TURNS:
            to_compress = store["turns"][:-KEEP_RECENT_TURNS]
            keep = store["turns"][-KEEP_RECENT_TURNS:]
            logger.info(
                "session: rolling %d turns into summary for user=%r",
                len(to_compress), user_id,
            )
            store["session_summary"] = roll_summary(
                to_compress,
                store["session_summary"],
                store["pinned_constraints"],
            )
            store["turns"] = keep

    except Exception as exc:
        logger.warning("add_turn: failed for user=%r (%s)", user_id, exc)


# ---------------------------------------------------------------------------
# Graph node — write-back after a successful run
# ---------------------------------------------------------------------------

def session_update_node(state) -> dict:
    """Persist the completed turn — short-term rolling summary + long-term promotion.

    Runs on the ok path after output_guardrail — only on successful runs.
    Returns no state updates (side-effect only).

    Two writes happen here:
      1. Short-term: add_turn() keeps the rolling summary + pinned constraints.
      2. Long-term:  promote_to_longterm() applies the write policy and, if the
                     query contains an explicit preference ("I'm vegetarian"),
                     persists it to SQLite so it survives across sessions.

    Long-term import is lazy to avoid the circular dependency:
      summary.py → longterm.py → summary.py (extract_constraints).
    """
    user_id = state.get("user_id", "demo-user")
    query = state.get("query", "")
    summary = state.get("summary", "")

    # 1. Short-term rolling summary
    add_turn(user_id, query, summary)

    # 2. Long-term persistence (lazy import breaks the circular dep)
    try:
        from backend.app.memory.longterm import promote_to_longterm
        promote_to_longterm(user_id, query, summary)
    except Exception as exc:
        logger.warning("session_update: long-term promotion failed (%s)", exc)

    # 3. Semantic cache — store this result so near-duplicate queries get a fast hit
    #    Only cache non-cache-hit responses (don't re-cache already-cached answers)
    if not state.get("cache_hit") and summary:
        try:
            from backend.app.memory.cache import semantic_set
            semantic_set(query, summary)
        except Exception as exc:
            logger.warning("session_update: semantic cache store failed (%s)", exc)

    logger.info("session_update: turn persisted for user=%r", user_id)
    return {}
