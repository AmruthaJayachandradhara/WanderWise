"""Query decomposition — the multi-passport / multi-city fan-out (Phase 4).

A small-tier node between router and plan that splits a multi-part query
into per-(passport, destination) sub-queries the RAG agent retrieves
independently: "one US passport, one Indian passport → Japan" becomes two
visa lookups (US→JP, IN→JP); "Tokyo then Kyoto then Osaka" becomes
per-city retrieval. Single-subject queries yield exactly one sub-query —
the degenerate case is byte-identical to the Phase 2/3 path.

Also extracts booking_requested (piggybacked — no second intent call),
which gates the Action agent's high-risk pending_actions.
"""

import json
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.llm.client import llm
from backend.app.orchestrator.state import GraphState
from backend.app.prompts.registry import render

logger = logging.getLogger(__name__)

_DECOMPOSE_TIER = "small"
_PROMPT_ID = "orchestrator/decompose_query"

# Deterministic fallback signal for booking intent when the LLM parse fails
_BOOKING_RE = re.compile(r"\b(book|reserve|reservation)\w*\b", re.IGNORECASE)


def _fallback(query: str, passport: str, location: str) -> dict:
    return {
        "sub_queries": [
            {
                "query": query,
                "passport": passport,
                "destination": location,
                "kind": "visa",
            }
        ],
        "booking_requested": bool(_BOOKING_RE.search(query)),
        "decompose_tier": _DECOMPOSE_TIER,
    }


def decompose_node(state: GraphState) -> dict:
    """Split the query into sub-queries; detect booking intent."""
    query = state.get("query", "")
    passport = state.get("passport_country", "US")
    location = state.get("location", "")

    context = (
        f"Query: {query}\n"
        f"Profile passport: {passport}\n"
        f"Destination hint: {location or 'unknown'}"
    )
    messages = [
        SystemMessage(content=render(_PROMPT_ID)),
        HumanMessage(content=context),
    ]

    try:
        response = llm.complete(_DECOMPOSE_TIER, messages)
        parsed = json.loads(response.text.strip())
        raw_subs = parsed.get("sub_queries")
        if not isinstance(raw_subs, list) or not raw_subs:
            raise ValueError("missing or empty sub_queries")
        sub_queries = [
            {
                "query": s.get("query") or query,
                "passport": s.get("passport") or passport,
                "destination": s.get("destination") or location,
                "kind": s.get("kind") or "visa",
            }
            for s in raw_subs
            if isinstance(s, dict)
        ]
        if not sub_queries:
            raise ValueError("no dict entries in sub_queries")
        booking_requested = bool(parsed.get("booking_requested", False))
    except Exception as exc:
        logger.warning("Decompose: parse failed (%s) — single sub-query fallback", exc)
        return _fallback(query, passport, location)

    logger.info(
        "Decompose: %d sub-quer%s, booking_requested=%s — %s",
        len(sub_queries),
        "y" if len(sub_queries) == 1 else "ies",
        booking_requested,
        [(s["passport"], s["destination"]) for s in sub_queries],
    )
    return {
        "sub_queries": sub_queries,
        "booking_requested": booking_requested,
        "decompose_tier": _DECOMPOSE_TIER,
    }
