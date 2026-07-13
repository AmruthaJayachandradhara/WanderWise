"""RAG agent node — retrieves and synthesises a cited visa/advisory answer.

Fans out over the decompose node's sub-queries (Phase 4): each
(passport, destination) pair is resolved and retrieved independently
through the Phase 2 pipeline, then a single large-tier synthesis call
merges the labeled per-subquery sources into one per-traveler/per-city
answer. A single-subject query is the degenerate one-sub-query case and
behaves exactly as before.
"""

import hashlib
import json
import logging
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.config import settings
from backend.app.llm.client import llm
from backend.app.llm.parsing import parse_json_dict
from backend.app.memory.cache import api_get, api_set
from backend.app.orchestrator.state import GraphState
from backend.app.prompts.registry import render
from backend.app.rag.retriever import retrieve

logger = logging.getLogger(__name__)

_SYNTHESIS_TIER = "large"
_RESOLVE_TIER = "small"
_SYNTHESIS_PROMPT = "rag/synthesis"
_DISCLAIMER = (
    "\n\n*Verify all visa and travel requirements with official government "
    "sources before travel.*"
)

# City / country name → ISO, covering the 50 curated countries in
# scripts/ingest_corpus.py. Lower-cased keys; checked by substring match.
_LOCATION_TO_ISO: dict[str, str] = {
    "united states": "US", "usa": "US", "new york": "US", "los angeles": "US",
    "united kingdom": "GB", "uk": "GB", "london": "GB", "england": "GB",
    "france": "FR", "paris": "FR", "germany": "DE", "berlin": "DE", "munich": "DE",
    "italy": "IT", "rome": "IT", "milan": "IT", "spain": "ES", "madrid": "ES", "barcelona": "ES",
    "portugal": "PT", "lisbon": "PT", "netherlands": "NL", "amsterdam": "NL",
    "belgium": "BE", "brussels": "BE", "switzerland": "CH", "zurich": "CH", "geneva": "CH",
    "austria": "AT", "vienna": "AT", "sweden": "SE", "stockholm": "SE",
    "norway": "NO", "oslo": "NO", "denmark": "DK", "copenhagen": "DK",
    "finland": "FI", "helsinki": "FI", "poland": "PL", "warsaw": "PL",
    "czech": "CZ", "prague": "CZ", "hungary": "HU", "budapest": "HU",
    "greece": "GR", "athens": "GR", "romania": "RO", "bucharest": "RO",
    "japan": "JP", "tokyo": "JP", "osaka": "JP", "kyoto": "JP",
    "korea": "KR", "seoul": "KR", "china": "CN", "beijing": "CN", "shanghai": "CN",
    "thailand": "TH", "bangkok": "TH", "vietnam": "VN", "hanoi": "VN",
    "singapore": "SG", "malaysia": "MY", "kuala lumpur": "MY",
    "indonesia": "ID", "bali": "ID", "jakarta": "ID",
    "philippines": "PH", "manila": "PH", "india": "IN", "delhi": "IN", "mumbai": "IN",
    "australia": "AU", "sydney": "AU", "melbourne": "AU",
    "new zealand": "NZ", "auckland": "NZ", "canada": "CA", "toronto": "CA", "vancouver": "CA",
    "mexico": "MX", "mexico city": "MX", "cancun": "MX",
    "brazil": "BR", "rio": "BR", "sao paulo": "BR",
    "argentina": "AR", "buenos aires": "AR", "chile": "CL", "santiago": "CL",
    "colombia": "CO", "bogota": "CO", "peru": "PE", "lima": "PE",
    "south africa": "ZA", "cape town": "ZA", "johannesburg": "ZA",
    "nigeria": "NG", "lagos": "NG", "kenya": "KE", "nairobi": "KE",
    "egypt": "EG", "cairo": "EG", "morocco": "MA", "marrakech": "MA",
    "united arab emirates": "AE", "uae": "AE", "dubai": "AE", "abu dhabi": "AE",
    "saudi arabia": "SA", "riyadh": "SA", "turkey": "TR", "istanbul": "TR",
    "israel": "IL", "tel aviv": "IL", "jerusalem": "IL",
    "jordan": "JO", "amman": "JO", "qatar": "QA", "doha": "QA",
}


def _resolve_country_iso(location: str, query: str) -> str:
    """Resolve a destination to an ISO code: dict → substring → small LLM."""
    loc = (location or "").lower().strip()
    if loc in _LOCATION_TO_ISO:
        return _LOCATION_TO_ISO[loc]

    haystack = f"{loc} {query}".lower()
    for name, iso in _LOCATION_TO_ISO.items():
        if name in haystack:
            return iso

    # Small-LLM fallback — ask for a bare ISO-3166 alpha-2 code
    try:
        messages = [
            SystemMessage(content=(
                "Return only the ISO 3166-1 alpha-2 country code (two uppercase "
                "letters) for the destination in the user's text. No other words."
            )),
            HumanMessage(content=f"Location: {location}\nQuery: {query}"),
        ]
        response = llm.complete(_RESOLVE_TIER, messages)
        code = response.text.strip().upper()[:2]
        if len(code) == 2 and code.isalpha():
            return code
    except Exception:
        pass
    return "US"


def _staleness_warning(rag_results: list[dict]) -> tuple[bool, str]:
    """Check retrieved chunks against per-collection staleness thresholds.

    Returns (stale, warning_text). Computed at answer time — including on
    cache hits — so a chunk that aged past its threshold always warns.
    """
    now = datetime.now(timezone.utc)
    stale_dates = []
    for r in rag_results:
        threshold = settings.STALENESS_THRESHOLD_DAYS.get(r.get("collection", ""), 30)
        try:
            verified = datetime.fromisoformat(r.get("last_verified", ""))
        except (TypeError, ValueError):
            continue
        if (now - verified).days > threshold:
            stale_dates.append(r.get("last_verified", "")[:10])
    if not stale_dates:
        return False, ""
    return True, (
        f"\n\n⚠ Some of this information was last verified on {min(stale_dates)} "
        "and may be out of date — verify before travel."
    )


def rag_node(state: GraphState) -> dict:
    """Retrieve per sub-query, then synthesise one merged, cited answer."""
    query = state.get("query", "")
    location = state.get("location", "")
    passport = state.get("passport_country", "US")

    # Decompose fan-out (Phase 4). No sub_queries in state (e.g. direct node
    # invocation in tests) → single-subject degenerate case.
    sub_queries = state.get("sub_queries") or [
        {"query": query, "passport": passport, "destination": location, "kind": "visa"}
    ]

    # Resolve each (passport, destination) pair up front — the cache key and
    # the retrieval filters both need the ISO codes.
    subjects = []
    for sq in sub_queries:
        iso = _resolve_country_iso(sq.get("destination", ""), sq.get("query", query))
        subjects.append((sq, iso, sq.get("passport") or passport))
    logger.info(
        "RAG: %d sub-quer%s — %s",
        len(subjects),
        "y" if len(subjects) == 1 else "ies",
        [(p, iso) for _, iso, p in subjects],
    )

    # API cache — visa docs change slowly (TTL 24h), keyed by data version.
    # With one sub-query this key is identical to the Phase 3 format.
    _qhash = hashlib.sha256(query.encode()).hexdigest()[:12]
    _cache_key = (
        f"rag:{settings.RAG_DATA_VERSION}:{'-'.join(iso for _, iso, _ in subjects)}:"
        f"{'-'.join(p for _, _, p in subjects)}:{_qhash}"
    )
    cached = api_get(_cache_key)
    if cached:
        cached_data = parse_json_dict(cached, context="rag_cache")
        if "rag_results" in cached_data and "visa_answer" in cached_data:
            logger.info("RAG: cache HIT for %s", _cache_key)
            # Staleness is re-evaluated on every hit — cached answers age too
            stale, warning = _staleness_warning(cached_data["rag_results"])
            visa_answer = cached_data["visa_answer"]
            if visa_answer and stale:
                visa_answer += warning
            return {
                "rag_results": cached_data["rag_results"],
                "visa_answer": visa_answer,
                "rag_degraded": False,
                "rag_stale": stale,
                "rag_tier": _SYNTHESIS_TIER,
                "cache_source": "api",
            }
        logger.warning("RAG: cache entry malformed for %s — refetching", _cache_key)

    # Fan-out: retrieve per sub-query through the Phase 2 pipeline.
    # Sequential by design — retrieval is local (fastembed + Qdrant filter)
    # and 2-3 sub-queries don't justify Send-API state-merge complexity.
    sections = []          # (label, chunks) per sub-query with results
    rag_results = []
    for sq, iso, sq_passport in subjects:
        chunks = retrieve(sq.get("query", query), iso, sq_passport)
        label = f"{sq_passport} passport → {sq.get('destination') or iso}"
        if not chunks:
            logger.info("RAG: no chunks for %s", label)
            continue
        sections.append((label, chunks))
        rag_results.extend(
            {
                "subject": label,
                "text": c.text,
                "score": c.score,
                "source_url": c.source_url,
                "country_iso": c.country_iso,
                "last_verified": c.last_verified,
                "advisory_level": c.advisory_level,
                "collection": c.collection,
            }
            for c in chunks
        )

    if not sections:
        logger.info("RAG: no chunks retrieved for any sub-query")
        return {
            "rag_results": [],
            "visa_answer": None,
            "rag_degraded": False,
            "rag_tier": _SYNTHESIS_TIER,
        }

    # Merge: one synthesis call over labeled per-subquery source blocks.
    ref = 0
    blocks = []
    for label, chunks in sections:
        lines = [f"=== {label} ==="]
        for c in chunks:
            ref += 1
            lines.append(
                f"[{ref}] {c.text}\nSource: {c.source_url} (verified {c.last_verified})"
            )
        blocks.append("\n".join(lines))
    context = "\n\n".join(blocks)

    messages = [
        SystemMessage(content=render(_SYNTHESIS_PROMPT)),
        HumanMessage(content=(
            f"Question: {query}\n\nRetrieved sources by subject:\n{context}"
        )),
    ]
    response = llm.complete(_SYNTHESIS_TIER, messages)
    visa_answer = response.text.strip() + _DISCLAIMER

    logger.info(
        "RAG: synthesised answer from %d chunks across %d subject(s)",
        ref, len(sections),
    )
    # Cache the clean answer; the staleness warning is appended per-read
    # so it reflects chunk age at answer time, not at cache time.
    api_set(
        _cache_key,
        json.dumps({"rag_results": rag_results, "visa_answer": visa_answer}),
        ttl=settings.CACHE_TTL_VISA_DOCS,
    )
    stale, warning = _staleness_warning(rag_results)
    if stale:
        visa_answer += warning
        logger.info("RAG: staleness warning attached")
    return {
        "rag_results": rag_results,
        "visa_answer": visa_answer,
        "rag_degraded": False,
        "rag_stale": stale,
        "rag_tier": _SYNTHESIS_TIER,
    }
