"""RAG agent node — retrieves and synthesises a cited visa/advisory answer.

Resolves the destination country to an ISO code, retrieves pre-filtered
chunks (country + passport), and synthesises a grounded answer on the large
tier with citations and a verify-with-official-sources disclaimer.

Single-subject scope: one passport, one destination. Multi-passport
decomposition is Phase 4.
"""

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.llm.client import llm
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


def rag_node(state: GraphState) -> dict:
    """Retrieve and synthesise a cited visa/advisory answer."""
    query = state.get("query", "")
    location = state.get("location", "")
    passport = state.get("passport_country", "US")

    country_iso = _resolve_country_iso(location, query)
    logger.info("RAG: resolved country_iso=%s passport=%s", country_iso, passport)

    chunks = retrieve(query, country_iso, passport)

    if not chunks:
        logger.info("RAG: no chunks retrieved for %s/%s", country_iso, passport)
        return {
            "rag_results": [],
            "visa_answer": None,
            "rag_degraded": False,
            "rag_tier": _SYNTHESIS_TIER,
        }

    context = "\n\n".join(
        f"[{i}] {c.text}\nSource: {c.source_url} (verified {c.last_verified})"
        for i, c in enumerate(chunks, start=1)
    )

    messages = [
        SystemMessage(content=render(_SYNTHESIS_PROMPT)),
        HumanMessage(content=(
            f"Passport: {passport}\nDestination ISO: {country_iso}\n"
            f"Question: {query}\n\nRetrieved sources:\n{context}"
        )),
    ]
    response = llm.complete(_SYNTHESIS_TIER, messages)
    visa_answer = response.text.strip() + _DISCLAIMER

    rag_results = [
        {
            "text": c.text,
            "score": c.score,
            "source_url": c.source_url,
            "country_iso": c.country_iso,
            "last_verified": c.last_verified,
            "advisory_level": c.advisory_level,
        }
        for c in chunks
    ]

    logger.info("RAG: synthesised answer from %d chunks", len(chunks))
    return {
        "rag_results": rag_results,
        "visa_answer": visa_answer,
        "rag_degraded": False,
        "rag_tier": _SYNTHESIS_TIER,
    }
