"""RAG corpus ingestion pipeline.

Fetches country travel data, chunks it per collection strategy, embeds
with fastembed, and upserts idempotently into Qdrant. Each chunk carries
full metadata so the retriever can filter by country + passport and the
staleness-detection hook (Phase 4) can check content_hash + last_verified.

Falls back to in-memory Qdrant when QDRANT_URL is not set — enables
offline unit tests without a live vector DB.
"""

import hashlib
import html.parser
import logging
from datetime import datetime, timezone

import httpx
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PayloadSchemaType, PointStruct, VectorParams

from backend.app.config import settings
from backend.app.rag.collections import COLLECTION_CONFIGS, chunk_text
from backend.app.rag.embeddings import embed_texts

logger = logging.getLogger(__name__)

_TIMEOUT_S = 10.0

# travel.state.gov migrated off the old /content/travel/en/traveladvisories/
# traveladvisories/{iso}.html scheme (now 404s) to a name-slugged path with
# no discoverable ISO-code mapping — hence this static table instead of a
# format string. Built by probing each of the 50 ingest_corpus.py countries
# live; entries not listed here (e.g. US has no self-advisory) or any future
# addition to that list will just skip the advisory/visa_entry source for
# that country (see fetch_country_sources), same as an unreachable URL would.
_ADVISORY_SLUGS: dict[str, str] = {
    "GB": "united-kingdom", "FR": "france", "DE": "germany", "IT": "italy", "ES": "spain",
    "PT": "portugal", "CH": "switzerland", "SE": "sweden", "NO": "norway", "FI": "finland",
    "CZ": "czechia", "HU": "hungary", "GR": "greece", "RO": "romania",
    "JP": "japan", "KR": "south-korea", "CN": "china", "VN": "vietnam", "SG": "singapore",
    "MY": "malaysia", "ID": "indonesia", "IN": "india",
    "NZ": "new-zealand", "CA": "canada", "MX": "mexico", "CL": "chile", "CO": "colombia",
    "ZA": "south-africa", "NG": "nigeria", "EG": "egypt", "SA": "saudi-arabia", "TR": "turkey",
    "JO": "jordan",
}
_ADVISORY_URL = "https://travel.state.gov/en/international-travel/travel-advisories/{slug}.html"

# v3.1 was retired; v5 requires a signup key (settings.RESTCOUNTRIES_API_KEY).
# https://restcountries.com/docs/countries
_RESTCOUNTRIES_URL = "https://api.restcountries.com/countries/v5/codes.alpha_2/{iso}"


_SKIP_TAGS = frozenset({"script", "style"})


class _HTMLStripper(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts)


def _strip_html(raw: str) -> str:
    stripper = _HTMLStripper()
    stripper.feed(raw)
    return " ".join(stripper.get_text().split())


def _get_client() -> QdrantClient:
    if settings.QDRANT_URL:
        return QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY)
    return QdrantClient(":memory:")


_FILTERABLE_FIELDS = ("country_iso", "passport_nationality", "source_url")


def _ensure_collection(client: QdrantClient, name: str, vector_size: int) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if name not in existing:
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )
        # retriever.py filters on country_iso/passport_nationality and
        # staleness.py additionally filters on source_url — this Qdrant
        # server rejects a filter on any payload field without an explicit
        # keyword index (fine on :memory:, enforced on Qdrant Cloud).
        for field in _FILTERABLE_FIELDS:
            client.create_payload_index(
                collection_name=name,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
            )


def fetch_country_sources(country_iso: str) -> tuple[list[tuple[str, str, str]], str | None]:
    """Fetch raw source texts for one country.

    Returns ([(collection_name, text, source_url)], advisory_level).
    Shared by ingest_country and the Phase 4 staleness refresh, so both
    always see identical source material for the hash comparison.
    """
    # Fetch advisory page
    advisory_text = ""
    advisory_level = None
    advisory_url = ""
    slug = _ADVISORY_SLUGS.get(country_iso.upper())
    if slug:
        advisory_url = _ADVISORY_URL.format(slug=slug)
        try:
            resp = httpx.get(advisory_url, timeout=_TIMEOUT_S, follow_redirects=True)
            if resp.status_code == 200:
                advisory_text = _strip_html(resp.text)[:8000]
                if "Level 1" in advisory_text:
                    advisory_level = "Level 1"
                elif "Level 2" in advisory_text:
                    advisory_level = "Level 2"
                elif "Level 3" in advisory_text:
                    advisory_level = "Level 3"
                elif "Level 4" in advisory_text:
                    advisory_level = "Level 4"
        except Exception as exc:
            logger.warning("ingest %s: advisory fetch failed — %s", country_iso, exc)
    else:
        logger.warning("ingest %s: no travel.state.gov slug mapping — skipping advisory/visa_entry", country_iso)

    # Fetch country metadata for destination guide
    guide_text = ""
    restcountries_url = _RESTCOUNTRIES_URL.format(iso=country_iso.upper())
    if settings.RESTCOUNTRIES_API_KEY:
        try:
            resp = httpx.get(
                restcountries_url,
                headers={"Authorization": f"Bearer {settings.RESTCOUNTRIES_API_KEY}"},
                timeout=_TIMEOUT_S,
            )
            if resp.status_code == 200:
                objects = resp.json().get("data", {}).get("objects", [])
                if objects:
                    c = objects[0]
                    capitals = ", ".join(cap.get("name", "") for cap in (c.get("capitals") or []))
                    languages = ", ".join(lang.get("name", "") for lang in (c.get("languages") or []))
                    currencies = ", ".join(cur.get("name", "") for cur in (c.get("currencies") or []))
                    guide_text = (
                        f"{c.get('names', {}).get('common', country_iso)} travel information. "
                        f"Region: {c.get('region', '')}. "
                        f"Capital: {capitals}. "
                        f"Languages: {languages}. "
                        f"Currency: {currencies}."
                    )
        except Exception as exc:
            logger.warning("ingest %s: restcountries fetch failed — %s", country_iso, exc)
    else:
        logger.warning("ingest %s: RESTCOUNTRIES_API_KEY not set — skipping destination_guides", country_iso)

    sources = [
        ("visa_entry", advisory_text, advisory_url),
        ("advisories", advisory_text, advisory_url),
        ("destination_guides", guide_text, restcountries_url),
    ]
    return sources, advisory_level


def build_point(
    chunk_text_val: str,
    vector: list[float],
    *,
    source_url: str,
    country_iso: str,
    passport: str,
    advisory_level: str | None,
    last_verified: str,
) -> PointStruct:
    """One chunk → one Qdrant point; the single place payloads are shaped."""
    content_hash = hashlib.sha256(chunk_text_val.encode()).hexdigest()
    # id must be unique per (country, passport, chunk) — not content_hash
    # alone, which is passport-independent (advisory/visa text doesn't vary
    # by passport). Two passports for the same country previously hashed to
    # the same point id and silently overwrote each other, so a two-passport
    # query (e.g. US + Indian to Japan) only ever had the last-ingested
    # passport's data. content_hash itself stays pure-content: staleness.py's
    # diff already scopes lookups by (country, passport, source_url) via a
    # Qdrant filter before comparing hashes, so it doesn't need passport
    # folded into the hash value itself.
    point_id = hashlib.sha256(f"{country_iso}:{passport}:{chunk_text_val}".encode()).hexdigest()
    return PointStruct(
        id=int(point_id[:8], 16),
        vector=vector,
        payload={
            "text": chunk_text_val,
            "source_url": source_url,
            "country_iso": country_iso,
            "passport_nationality": passport,
            "advisory_level": advisory_level,
            "last_verified": last_verified,
            "content_hash": content_hash,
        },
    )


def ingest_country(country_iso: str, passport: str = "US", client: QdrantClient | None = None) -> int:
    """Fetch, chunk, embed, and upsert travel data for one country.

    Returns the number of chunks upserted. Idempotent via content-addressed
    point IDs: an unchanged chunk overwrites itself in place.
    """
    client = client or _get_client()
    last_verified = datetime.now(timezone.utc).isoformat()
    total_upserted = 0

    sources, advisory_level = fetch_country_sources(country_iso)

    for collection_name, text, source_url in sources:
        if not text:
            continue
        config = COLLECTION_CONFIGS[collection_name]
        _ensure_collection(client, collection_name, config.vector_size)
        chunks = chunk_text(text, config)
        if not chunks:
            continue

        vectors = embed_texts(chunks)
        points = [
            build_point(
                chunk_text_val,
                vector,
                source_url=source_url,
                country_iso=country_iso,
                passport=passport,
                advisory_level=advisory_level,
                last_verified=last_verified,
            )
            for chunk_text_val, vector in zip(chunks, vectors)
        ]

        if points:
            client.upsert(collection_name=collection_name, points=points)
            total_upserted += len(points)
            logger.info("ingest %s/%s: upserted %d chunks", country_iso, collection_name, len(points))

    return total_upserted
