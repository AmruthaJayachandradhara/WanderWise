"""SQLite-backed long-term preference store (Phase 3, Step 8).

Tables:
  preferences(user_id, key, value, source, updated_at)
    — flat key-value store for durable prefs (diet, seat, passport, etc.)
  memories(id, user_id, text, embedding, created_at)
    — text + optional fastembed vector for semantic recall

All operations are degrade-safe: failures log a warning and return a
sensible default so the graph never crashes on a DB error. This mirrors
the ToolResult / retrieve() pattern used elsewhere in the codebase.
"""

import json
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path("wanderwise_memory.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS preferences (
            user_id    TEXT NOT NULL,
            key        TEXT NOT NULL,
            value      TEXT NOT NULL,
            source     TEXT NOT NULL DEFAULT 'explicit',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, key)
        );

        CREATE TABLE IF NOT EXISTS memories (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    TEXT NOT NULL,
            text       TEXT NOT NULL,
            embedding  TEXT,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id);
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Preferences — flat key-value (guaranteed path)
# ---------------------------------------------------------------------------

def get_all_prefs(user_id: str) -> dict:
    """Return all durable preferences for user_id as a plain dict."""
    try:
        with _connect() as conn:
            _init(conn)
            rows = conn.execute(
                "SELECT key, value FROM preferences WHERE user_id = ?",
                (user_id,),
            ).fetchall()
            return {r["key"]: r["value"] for r in rows}
    except Exception as exc:
        logger.warning("longterm_store.get_all_prefs: failed (%s)", exc)
        return {}


def set_pref(user_id: str, key: str, value: str, source: str = "explicit") -> None:
    """Upsert a single preference. Idempotent — safe to call repeatedly."""
    from datetime import datetime, timezone

    try:
        with _connect() as conn:
            _init(conn)
            conn.execute(
                """INSERT INTO preferences (user_id, key, value, source, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, key) DO UPDATE SET
                       value      = excluded.value,
                       source     = excluded.source,
                       updated_at = excluded.updated_at""",
                (user_id, key, value, source, datetime.now(timezone.utc).isoformat()),
            )
    except Exception as exc:
        logger.warning("longterm_store.set_pref: failed (%s)", exc)


# ---------------------------------------------------------------------------
# Memories — text + optional embedding (semantic recall)
# ---------------------------------------------------------------------------

def add_memory(user_id: str, text: str, embedding: list[float] | None = None) -> None:
    """Store a memory entry for semantic recall."""
    from datetime import datetime, timezone

    try:
        with _connect() as conn:
            _init(conn)
            conn.execute(
                """INSERT INTO memories (user_id, text, embedding, created_at)
                   VALUES (?, ?, ?, ?)""",
                (
                    user_id,
                    text,
                    json.dumps(embedding) if embedding is not None else None,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
    except Exception as exc:
        logger.warning("longterm_store.add_memory: failed (%s)", exc)


def get_memories(user_id: str) -> list[dict]:
    """Return all memory rows for user_id."""
    try:
        with _connect() as conn:
            _init(conn)
            rows = conn.execute(
                "SELECT text, embedding FROM memories WHERE user_id = ? ORDER BY id",
                (user_id,),
            ).fetchall()
            return [
                {
                    "text": r["text"],
                    "embedding": json.loads(r["embedding"]) if r["embedding"] else None,
                }
                for r in rows
            ]
    except Exception as exc:
        logger.warning("longterm_store.get_memories: failed (%s)", exc)
        return []
