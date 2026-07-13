"""Shared JSON parsing for LLM responses and JSON-shaped cache payloads.

Centralizes the parse-or-default pattern used throughout the graph: an LLM
(even in json_mode) can still return malformed JSON under quota pressure,
and a cache entry can predate a payload-shape change. Every call site
should degrade to `default` rather than let a raw
JSONDecodeError/KeyError/AttributeError/TypeError escape into the graph —
callers then read fields via .get() with their own field-level defaults.
"""

import json
import logging

logger = logging.getLogger(__name__)


def parse_json_dict(text: str, default: dict | None = None, *, context: str = "") -> dict:
    """Parse `text` as JSON, returning a dict. Never raises.

    Falls back to a copy of `default` (or {}) when `text` isn't valid JSON
    or doesn't decode to a dict.
    """
    fallback = dict(default) if default else {}
    label = f" [{context}]" if context else ""
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("parse_json_dict: invalid JSON%s (%s)", label, exc)
        return fallback
    if not isinstance(parsed, dict):
        logger.warning("parse_json_dict: expected dict, got %s%s", type(parsed).__name__, label)
        return fallback
    return parsed
