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
import os
from datetime import datetime, timezone

import httpx
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from backend.app.rag.collections import COLLECTION_CONFIGS, chunk_text
from backend.app.rag.embeddings import embed_texts

logger = logging.getLogger(__name__)

_TIMEOUT_S = 10.0
_ADVISORY_URL = "https://travel.state.gov/content/travel/en/traveladvisories/traveladvisories/{iso}.html"
_RESTCOUNTRIES_URL = "https://restcountries.com/v3.1/alpha/{iso}"


class _HTMLStripper(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts)


def _strip_html(raw: str) -> str:
    stripper = _HTMLStripper()
    stripper.feed(raw)
    return " ".join(stripper.get_text().split())


def _get_client() -> QdrantClient:
    url = os.getenv("QDRANT_URL")
    if url:
        api_key = os.getenv("QDRANT_API_KEY")
        return QdrantClient(url=url, api_key=api_key)
    return QdrantClient(":memory:")


def _ensure_collection(client: QdrantClient, name: str, vector_size: int) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if name not in existing:
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )


def ingest_country(country_iso: str, passport: str = "US") -> int:
    """Fetch, chunk, embed, and upsert travel data for one country.

    Returns the number of chunks upserted. Idempotent: skips chunks
    whose content_hash already exists in the collection.
    """
    client = _get_client()
    iso_lower = country_iso.lower()
    last_verified = datetime.now(timezone.utc).isoformat()
    total_upserted = 0

    # Fetch advisory page
    advisory_text = ""
    advisory_level = None
    try:
        resp = httpx.get(_ADVISORY_URL.format(iso=iso_lower), timeout=_TIMEOUT_S, follow_redirects=True)
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

    # Fetch country metadata for destination guide
    guide_text = ""
    try:
        resp = httpx.get(_RESTCOUNTRIES_URL.format(iso=country_iso), timeout=_TIMEOUT_S)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and data:
                c = data[0]
                guide_text = (
                    f"{c.get('name', {}).get('common', country_iso)} travel information. "
                    f"Region: {c.get('region', '')}. "
                    f"Capital: {', '.join(c.get('capital', []))}. "
                    f"Languages: {', '.join(c.get('languages', {}).values())}. "
                    f"Currency: {', '.join(c.get('currencies', {}).keys())}."
                )
    except Exception as exc:
        logger.warning("ingest %s: restcountries fetch failed — %s", country_iso, exc)

    sources = [
        ("visa_entry", advisory_text, _ADVISORY_URL.format(iso=iso_lower)),
        ("advisories", advisory_text, _ADVISORY_URL.format(iso=iso_lower)),
        ("destination_guides", guide_text, _RESTCOUNTRIES_URL.format(iso=country_iso)),
    ]

    for collection_name, text, source_url in sources:
        if not text:
            continue
        config = COLLECTION_CONFIGS[collection_name]
        _ensure_collection(client, collection_name, config.vector_size)
        chunks = chunk_text(text, config)
        if not chunks:
            continue

        vectors = embed_texts(chunks)
        points = []
        for chunk_text_val, vector in zip(chunks, vectors):
            content_hash = hashlib.sha256(chunk_text_val.encode()).hexdigest()
            points.append(PointStruct(
                id=int(content_hash[:8], 16),
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
            ))

        if points:
            client.upsert(collection_name=collection_name, points=points)
            total_upserted += len(points)
            logger.info("ingest %s/%s: upserted %d chunks", country_iso, collection_name, len(points))

    return total_upserted
