"""RAG retrieval pipeline.

Pipeline order:
  1. Query rewrite (small tier) — expand with passport + destination keywords.
  2. Embed the rewritten query via fastembed.
  3. Metadata pre-filter + dense search across all three Qdrant collections.
     The country_iso + passport_nationality filter is the highest-leverage
     correctness guard — it structurally prevents returning the wrong
     country's rules.
  4. Merge results, dedup by content_hash, return top-5 by score.

The public retrieve() never raises: any failure (Qdrant down, embedding
error) degrades to an empty list so the RAG agent can carry on.
"""

import logging
import os
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

from backend.app.llm.client import llm
from backend.app.prompts.registry import render
from backend.app.rag.collections import COLLECTION_CONFIGS
from backend.app.rag.embeddings import embed_query

logger = logging.getLogger(__name__)

_REWRITE_TIER = "small"
_REWRITE_PROMPT = "rag/query_rewrite"
_TOP_K = 5
_PER_COLLECTION_LIMIT = 10


@dataclass
class RetrievedChunk:
    text: str
    score: float
    source_url: str
    country_iso: str
    last_verified: str
    advisory_level: str | None


def _get_client() -> QdrantClient:
    url = os.getenv("QDRANT_URL")
    if url:
        api_key = os.getenv("QDRANT_API_KEY")
        return QdrantClient(url=url, api_key=api_key)
    return QdrantClient(":memory:")


def _rewrite_query(query: str, country_iso: str, passport_nationality: str) -> str:
    """Expand the query for better recall. Falls back to the raw query."""
    try:
        messages = [
            SystemMessage(content=render(_REWRITE_PROMPT)),
            HumanMessage(content=(
                f"Query: {query}\nDestination ISO: {country_iso}\n"
                f"Passport: {passport_nationality}"
            )),
        ]
        response = llm.complete(_REWRITE_TIER, messages)
        rewritten = response.text.strip()
        return rewritten or query
    except Exception:
        return query


def _retrieve(query: str, country_iso: str, passport_nationality: str) -> list[RetrievedChunk]:
    rewritten = _rewrite_query(query, country_iso, passport_nationality)
    vector = embed_query(rewritten)

    metadata_filter = Filter(must=[
        FieldCondition(key="country_iso", match=MatchValue(value=country_iso)),
        FieldCondition(key="passport_nationality", match=MatchValue(value=passport_nationality)),
    ])

    client = _get_client()
    existing = {c.name for c in client.get_collections().collections}

    merged: dict[str, RetrievedChunk] = {}
    for collection_name in COLLECTION_CONFIGS:
        if collection_name not in existing:
            continue
        hits = client.search(
            collection_name=collection_name,
            query_vector=vector,
            query_filter=metadata_filter,
            limit=_PER_COLLECTION_LIMIT,
        )
        for hit in hits:
            payload = hit.payload or {}
            content_hash = payload.get("content_hash", payload.get("text", ""))
            chunk = RetrievedChunk(
                text=payload.get("text", ""),
                score=float(hit.score),
                source_url=payload.get("source_url", ""),
                country_iso=payload.get("country_iso", country_iso),
                last_verified=payload.get("last_verified", ""),
                advisory_level=payload.get("advisory_level"),
            )
            # Dedup by content_hash, keeping the highest score
            if content_hash not in merged or chunk.score > merged[content_hash].score:
                merged[content_hash] = chunk

    ranked = sorted(merged.values(), key=lambda c: c.score, reverse=True)
    return ranked[:_TOP_K]


def retrieve(query: str, country_iso: str, passport_nationality: str) -> list[RetrievedChunk]:
    """Public entry point — never raises; returns [] on any failure."""
    try:
        return _retrieve(query, country_iso, passport_nationality)
    except Exception as exc:
        logger.warning("retrieve: degraded — %s", exc)
        return []
