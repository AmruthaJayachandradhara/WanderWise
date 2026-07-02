"""Long-term memory: write policy, cross-session persistence, semantic recall.
(Phase 3, Step 8)

Write policy — what gets promoted to long-term:
  PERSIST: explicit user preferences stated with first-person ownership
           ("I'm vegetarian", "I prefer aisle seats", "I have a US passport").
           Repeated behaviours are also eligible (detected by comparing
           against what the session already knows).
  DISCARD: ephemeral chatter, search results, temporal questions,
           assistant responses (only user utterances are evaluated).

The distinction "I persist explicit preferences and repeated behaviours, not
chatter" is the core interview answer for this module.

Semantic recall:
  Preferences and past trips are embedded via fastembed (same model used by
  RAG retrieval) and stored in the SQLite memories table. At query time the
  incoming query is embedded and cosine-compared against all memories for
  the user — returning the top-k most relevant prior experiences.
  If fastembed is unavailable (cold start / test env), falls back to
  returning the flat key-value preferences only.
"""

import json
import logging
import re

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Write policy signal detection
# ---------------------------------------------------------------------------

_EXPLICIT_PREF_RE = re.compile(
    r"\b("
    r"i'?m\s+(vegetarian|vegan|halal|kosher|gluten.free|diabetic|lactose)"
    r"|i\s+(prefer|want|need|require|always|only\s+eat|am\s+allergic)"
    r"|i\s+have\s+(a\s+)?(us|uk|eu|canadian|australian|indian)\s+passport"
    r"|my\s+(preference|diet|budget|seat)"
    r"|i\s+don'?t\s+(eat|like|drink)\b"
    r")",
    re.IGNORECASE,
)


def _should_persist_heuristic(query: str) -> bool:
    """Cheap pre-screen: does this query contain a preference signal?"""
    return bool(_EXPLICIT_PREF_RE.search(query))


def should_persist(query: str) -> tuple[bool, dict]:
    """Apply write policy to a user query.

    Returns (should_store, extracted_prefs).
    Only user queries are evaluated — assistant responses are not written
    to long-term memory directly.
    """
    if not query or not _should_persist_heuristic(query):
        return False, {}

    # Reuse constraint extraction from the session summary module
    # (avoids duplicating the LLM call logic)
    try:
        from backend.app.memory.summary import extract_constraints

        prefs = extract_constraints([query])
        if prefs:
            return True, prefs
    except Exception as exc:
        logger.warning("should_persist: extraction failed (%s)", exc)

    return False, {}


# ---------------------------------------------------------------------------
# Promotion: short-term → long-term
# ---------------------------------------------------------------------------

def promote_to_longterm(user_id: str, query: str, response: str) -> None:
    """Apply write policy; persist qualifying preferences + store memory.

    Called from session_update_node after every successful graph run.
    Degrade-safe — never raises.
    """
    from backend.app.state.longterm_store import add_memory, set_pref

    try:
        store_it, prefs = should_persist(query)
        if not store_it or not prefs:
            return

        for key, value in prefs.items():
            set_pref(user_id, key, str(value), source="explicit")
            logger.info(
                "longterm: promoted %r=%r for user=%r", key, value, user_id
            )

        # Store a compact memory entry for semantic recall
        memory_text = (
            f"User stated: {query[:200]}\n"
            f"Preferences extracted: {json.dumps(prefs)}"
        )
        embedding = _embed(memory_text)
        add_memory(user_id, memory_text, embedding)

    except Exception as exc:
        logger.warning("promote_to_longterm: failed for user=%r (%s)", user_id, exc)


# ---------------------------------------------------------------------------
# Load: SQLite → profile state
# ---------------------------------------------------------------------------

def load_longterm_prefs(user_id: str) -> dict:
    """Return all durable preferences from the SQLite store."""
    from backend.app.state.longterm_store import get_all_prefs

    return get_all_prefs(user_id)


# ---------------------------------------------------------------------------
# Semantic recall
# ---------------------------------------------------------------------------

def _embed(text: str) -> list[float] | None:
    """Embed text via fastembed. Returns None on any failure (degrade-safe)."""
    try:
        from fastembed import TextEmbedding

        model = TextEmbedding("BAAI/bge-small-en-v1.5")
        vectors = list(model.embed([text]))
        return vectors[0].tolist() if vectors else None
    except Exception as exc:
        logger.debug("longterm._embed: fastembed unavailable (%s)", exc)
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def semantic_recall(user_id: str, query: str, top_k: int = 3) -> list[str]:
    """Return the top-k past memories most similar to query.

    Falls back to an empty list if embeddings are unavailable — the flat
    key-value preferences (load_longterm_prefs) are the guaranteed path.
    """
    from backend.app.state.longterm_store import get_memories

    memories = get_memories(user_id)
    if not memories:
        return []

    query_vec = _embed(query)
    if query_vec is None:
        # No embeddings — return all memories as text (flat fallback)
        return [m["text"] for m in memories[:top_k]]

    scored = []
    for mem in memories:
        mem_vec = mem.get("embedding")
        if mem_vec:
            score = _cosine(query_vec, mem_vec)
        else:
            score = 0.0
        scored.append((score, mem["text"]))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [text for _, text in scored[:top_k]]
