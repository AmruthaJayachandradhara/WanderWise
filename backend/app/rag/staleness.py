"""Staleness detection + selective re-ingestion (Phase 4).

Uses the hooks seeded in Phase 2: every chunk carries a content_hash and a
last_verified timestamp. The refresh re-fetches each source, re-chunks, and
hashes BEFORE embedding — hashing is free, embedding is not — then diffs
against the hashes stored in Qdrant:

  unchanged chunk → last_verified bumped in place (set_payload, no embed)
  new/changed chunk → embedded + upserted
  orphaned chunk (no longer in the source) → deleted

Only changed documents cost embedding work, which is what makes the
scheduled GitHub Actions job (.github/workflows/reingest.yml) cheap enough
to run daily on free minutes.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue, PointIdsList

from backend.app.rag.collections import COLLECTION_CONFIGS, chunk_text
from backend.app.rag.embeddings import embed_texts
from backend.app.rag.ingest import (
    _ensure_collection,
    _get_client,
    build_point,
    fetch_country_sources,
)

logger = logging.getLogger(__name__)


@dataclass
class ReingestReport:
    country_iso: str
    collections: list[str] = field(default_factory=list)
    unchanged_chunks: int = 0
    new_chunks: int = 0
    deleted_chunks: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.new_chunks or self.deleted_chunks)


def _stored_hashes(
    client: QdrantClient,
    collection_name: str,
    country_iso: str,
    passport: str,
    source_url: str,
) -> dict[str, int | str]:
    """content_hash → point id for this (country, passport, source)."""
    doc_filter = Filter(must=[
        FieldCondition(key="country_iso", match=MatchValue(value=country_iso)),
        FieldCondition(key="passport_nationality", match=MatchValue(value=passport)),
        FieldCondition(key="source_url", match=MatchValue(value=source_url)),
    ])
    hashes: dict[str, int | str] = {}
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=collection_name,
            scroll_filter=doc_filter,
            limit=256,
            offset=offset,
            with_payload=["content_hash"],
            with_vectors=False,
        )
        for p in points:
            content_hash = (p.payload or {}).get("content_hash")
            if content_hash:
                hashes[content_hash] = p.id
        if offset is None:
            return hashes


def refresh_country(
    country_iso: str,
    passport: str = "US",
    collections: list[str] | None = None,
    client: QdrantClient | None = None,
) -> ReingestReport:
    """Re-fetch one country's sources; re-ingest only what changed."""
    client = client or _get_client()
    report = ReingestReport(country_iso=country_iso)
    now = datetime.now(timezone.utc).isoformat()

    sources, advisory_level = fetch_country_sources(country_iso)

    for collection_name, text, source_url in sources:
        if collections and collection_name not in collections:
            continue
        if not text:
            report.errors.append(f"{collection_name}: empty source fetch")
            continue
        report.collections.append(collection_name)

        config = COLLECTION_CONFIGS[collection_name]
        _ensure_collection(client, collection_name, config.vector_size)

        chunks = chunk_text(text, config)
        fresh = {hashlib.sha256(c.encode()).hexdigest(): c for c in chunks}
        stored = _stored_hashes(client, collection_name, country_iso, passport, source_url)

        unchanged = fresh.keys() & stored.keys()
        to_add = [fresh[h] for h in fresh.keys() - stored.keys()]
        to_delete = [stored[h] for h in stored.keys() - fresh.keys()]

        # Unchanged: bump last_verified only — verified today, zero embeds.
        if unchanged:
            client.set_payload(
                collection_name=collection_name,
                payload={"last_verified": now},
                points=[stored[h] for h in unchanged],
            )
            report.unchanged_chunks += len(unchanged)

        # Changed/new: the only chunks that pay for embedding.
        if to_add:
            vectors = embed_texts(to_add)
            points = [
                build_point(
                    chunk,
                    vector,
                    source_url=source_url,
                    country_iso=country_iso,
                    passport=passport,
                    advisory_level=advisory_level,
                    last_verified=now,
                )
                for chunk, vector in zip(to_add, vectors)
            ]
            client.upsert(collection_name=collection_name, points=points)
            report.new_chunks += len(points)

        # Orphans: chunks the source no longer contains.
        if to_delete:
            client.delete(
                collection_name=collection_name,
                points_selector=PointIdsList(points=to_delete),
            )
            report.deleted_chunks += len(to_delete)

        logger.info(
            "refresh %s/%s: %d unchanged, %d new, %d deleted",
            country_iso, collection_name,
            len(unchanged), len(to_add), len(to_delete),
        )

    return report
