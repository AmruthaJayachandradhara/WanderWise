"""Semantic cache + API/tool-result cache (Phase 3, Step 9).

Two cache types:

  Semantic cache — embeds the incoming query; if cosine similarity to a
    prior query exceeds CACHE_SEMANTIC_SIMILARITY_THRESHOLD, returns the
    cached response and skips the whole LLM pipeline. Backed by Upstash
    Redis when creds are set, otherwise by an in-process dict (graceful
    fallback — same pattern as RAG's retrieve(), which never raises).
    Cache hit → still routed through output_guardrail so safety is never
    bypassed.

  API/tool-result cache — wraps slow-changing external calls with TTLs:
      visa docs  24h (CACHE_TTL_VISA_DOCS)
      weather     1h (CACHE_TTL_WEATHER)
      flights     0  (never — prices change too fast)
    Cache keys include a data-version slug (v1, v2 …) so a corpus re-ingest
    or weather format change invalidates stale entries without flushing the
    whole cache. This is the seam that Phase 4's staleness job hooks into.

Backend selection (lazy, only on first call):
  UPSTASH_REDIS_URL set → _RedisCache (redis-py)
  else                  → _InMemoryCache
"""

import hashlib
import json
import logging
import time

logger = logging.getLogger(__name__)

# Shared backend instance — initialised lazily on first call
_backend = None


# ---------------------------------------------------------------------------
# Cosine similarity (self-contained — no external dep)
# ---------------------------------------------------------------------------

def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


# ---------------------------------------------------------------------------
# Embedding helper (reuses fastembed, degrade-safe)
# ---------------------------------------------------------------------------

_embedding_model = None


def _embed(text: str) -> list[float] | None:
    global _embedding_model
    try:
        from fastembed import TextEmbedding

        if _embedding_model is None:
            _embedding_model = TextEmbedding("BAAI/bge-small-en-v1.5")
        vecs = list(_embedding_model.embed([text]))
        return vecs[0].tolist() if vecs else None
    except Exception as exc:
        logger.debug("cache._embed: fastembed unavailable (%s)", exc)
        return None


# ---------------------------------------------------------------------------
# In-memory backend (default / CI / local dev without Redis)
# ---------------------------------------------------------------------------

class _InMemoryCache:
    """Simple in-process dict cache with TTL and a bounded semantic index."""

    _SEM_INDEX_LIMIT = 200

    def __init__(self) -> None:
        self._store: dict[str, dict] = {}
        self._sem_index: list[dict] = []  # [{key, embedding}]

    def get(self, key: str) -> str | None:
        entry = self._store.get(key)
        if not entry:
            return None
        exp = entry.get("expires_at")
        if exp and time.monotonic() > exp:
            self._store.pop(key, None)
            return None
        return entry["value"]

    def set(self, key: str, value: str, ttl: int = 0) -> None:
        self._store[key] = {
            "value": value,
            "expires_at": time.monotonic() + ttl if ttl > 0 else None,
        }

    def semantic_search(self, embedding: list[float], threshold: float) -> str | None:
        best, best_key = -1.0, None
        for item in self._sem_index:
            score = _cosine(embedding, item["embedding"])
            if score > best:
                best, best_key = score, item["key"]
        if best >= threshold and best_key:
            return self.get(best_key)
        return None

    def semantic_add(self, key: str, embedding: list[float]) -> None:
        self._sem_index.append({"key": key, "embedding": embedding})
        if len(self._sem_index) > self._SEM_INDEX_LIMIT:
            self._sem_index = self._sem_index[-self._SEM_INDEX_LIMIT :]


# ---------------------------------------------------------------------------
# Redis backend (Upstash via redis-py)
# ---------------------------------------------------------------------------

class _RedisCache:
    _SEM_INDEX_KEY = "ww:sem_index"
    _SEM_INDEX_LIMIT = 200

    def __init__(self, url: str, token: str | None = None) -> None:
        import redis as redis_client

        # Upstash provides an HTTPS REST URL (https://host.upstash.io).
        # redis-py needs a Redis protocol URL (rediss://default:TOKEN@host:6379).
        # Convert automatically when the scheme is http/https.
        connect_url = url
        if url.startswith(("https://", "http://")):
            import urllib.parse
            host = urllib.parse.urlparse(url).hostname
            password = token or ""
            connect_url = f"rediss://default:{password}@{host}:6379"
            token = None  # already embedded in URL

        kwargs: dict = {}
        if token:
            kwargs["password"] = token
        self._r = redis_client.from_url(connect_url, decode_responses=True, **kwargs)
        logger.info("cache: Redis backend connected (%s)", urllib.parse.urlparse(connect_url).hostname if "urllib" in dir() else "...")

    def get(self, key: str) -> str | None:
        try:
            return self._r.get(f"ww:{key}")
        except Exception as exc:
            logger.warning("cache.Redis.get failed (%s)", exc)
            return None

    def set(self, key: str, value: str, ttl: int = 0) -> None:
        try:
            rkey = f"ww:{key}"
            if ttl > 0:
                self._r.setex(rkey, ttl, value)
            else:
                self._r.set(rkey, value)
        except Exception as exc:
            logger.warning("cache.Redis.set failed (%s)", exc)

    def semantic_search(self, embedding: list[float], threshold: float) -> str | None:
        try:
            raw = self._r.get(self._SEM_INDEX_KEY)
            if not raw:
                return None
            index = json.loads(raw)
            best, best_key = -1.0, None
            for item in index:
                score = _cosine(embedding, item["embedding"])
                if score > best:
                    best, best_key = score, item["key"]
            if best >= threshold and best_key:
                return self.get(best_key)
        except Exception as exc:
            logger.warning("cache.Redis.semantic_search failed (%s)", exc)
        return None

    def semantic_add(self, key: str, embedding: list[float]) -> None:
        try:
            raw = self._r.get(self._SEM_INDEX_KEY)
            index = json.loads(raw) if raw else []
            index.append({"key": key, "embedding": embedding})
            if len(index) > self._SEM_INDEX_LIMIT:
                index = index[-self._SEM_INDEX_LIMIT :]
            self._r.set(self._SEM_INDEX_KEY, json.dumps(index))
        except Exception as exc:
            logger.warning("cache.Redis.semantic_add failed (%s)", exc)


# ---------------------------------------------------------------------------
# Backend factory (lazy, singleton)
# ---------------------------------------------------------------------------

def _get_backend() -> _InMemoryCache | _RedisCache:
    global _backend
    if _backend is not None:
        return _backend
    try:
        from backend.app.config import settings

        if settings.UPSTASH_REDIS_URL:
            _backend = _RedisCache(
                settings.UPSTASH_REDIS_URL,
                token=settings.UPSTASH_REDIS_TOKEN,
            )
            return _backend
    except Exception as exc:
        logger.warning("cache: Redis init failed (%s), using in-memory fallback", exc)
    _backend = _InMemoryCache()
    logger.info("cache: using in-memory backend")
    return _backend


# ---------------------------------------------------------------------------
# Public API — API/tool-result cache
# ---------------------------------------------------------------------------

def api_get(key: str) -> str | None:
    """Return a cached API result, or None on miss / TTL expiry."""
    try:
        return _get_backend().get(key)
    except Exception as exc:
        logger.warning("api_get failed (%s)", exc)
        return None


def api_set(key: str, value: str, ttl: int = 0) -> None:
    """Store an API result. ttl=0 means no expiry."""
    try:
        _get_backend().set(key, value, ttl=ttl)
    except Exception as exc:
        logger.warning("api_set failed (%s)", exc)


# ---------------------------------------------------------------------------
# Public API — Semantic cache
# ---------------------------------------------------------------------------

def semantic_get(query: str) -> str | None:
    """Return a cached response if a past query is similar enough, else None.

    Similarity threshold is read from settings at call time so a config
    change takes effect without restart.
    """
    embedding = _embed(query)
    if embedding is None:
        return None
    try:
        from backend.app.config import settings

        return _get_backend().semantic_search(
            embedding, settings.CACHE_SEMANTIC_SIMILARITY_THRESHOLD
        )
    except Exception as exc:
        logger.warning("semantic_get failed (%s)", exc)
        return None


def semantic_set(query: str, response: str) -> None:
    """Cache a query→response pair for future semantic lookups."""
    embedding = _embed(query)
    if embedding is None:
        return
    key = "sem:" + hashlib.sha256(query.encode()).hexdigest()[:16]
    try:
        _get_backend().set(key, response)
        _get_backend().semantic_add(key, embedding)
        logger.info("semantic_set: cached query (key=%s)", key)
    except Exception as exc:
        logger.warning("semantic_set failed (%s)", exc)


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------

def cache_lookup_node(state) -> dict:
    """Check the semantic cache before running the full pipeline.

    On a hit: sets cache_hit=True and summary=cached_response.
    route_cache then short-circuits to output_guardrail, skipping all agents.
    On a miss: sets cache_hit=False and continues to the router.
    """
    query = state.get("query", "")
    cached = semantic_get(query)
    if cached:
        logger.info("cache_lookup: HIT — returning cached response")
        return {
            "cache_hit": True,
            "cache_source": "semantic",
            "summary": cached,
        }
    logger.info("cache_lookup: MISS — proceeding to router")
    return {"cache_hit": False}


def route_cache(state) -> str:
    """LangGraph conditional edge after cache_lookup: 'hit' or 'miss'."""
    return "hit" if state.get("cache_hit") else "miss"
