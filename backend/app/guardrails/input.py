"""Input guardrails — topicality, injection, and PII checks.

All checks run inside the input_guardrail_node, which sits between the
memory node and the router. A blocked query deterministically routes to the
refusal_node via a conditional edge — no expensive agents are ever reached.

Step 1: topicality
Step 2: injection / jailbreak
Step 3: PII redaction

Check order in the node:
  1. PII redaction — must be first so every subsequent LLM call and every
     state write (→ LangSmith trace) sees scrubbed text, not raw PII.
  2. Injection heuristics (deterministic regex — fastest, safest first)
  3. Injection LLM classifier (ambiguous cases only)
  4. Topicality LLM classifier
"""

import json
import logging
import re
from typing import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.guardrails.pii import redact
from backend.app.llm import llm
from backend.app.orchestrator.state import GraphState
from backend.app.prompts.registry import get_prompt, render

logger = logging.getLogger(__name__)

_REFUSAL_MSG = (
    "I'm a travel planning assistant. I can only help with travel-related "
    "questions — destinations, flights, hotels, visas, budgets, and weather. "
    "Please ask me something about your next trip!"
)

_INJECTION_REFUSAL_MSG = (
    "I noticed your message contains patterns that look like an attempt to "
    "override my instructions. I'm a travel planning assistant and I'm here "
    "to help you plan your next trip!"
)

# ---------------------------------------------------------------------------
# Injection heuristics — deterministic, no LLM cost
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"ignore\b[\w\s]{0,30}\binstructions?",   # handles 1-3 modifier words
        r"disregard\b[\w\s]{0,30}\binstructions?",
        r"forget\b[\w\s]{0,30}\binstructions?",
        r"(print|reveal|show|output|repeat|expose|leak|tell me) (your )?(system prompt|instructions?|configuration|config|prompt)",
        r"what (is|are) (your )?(system prompt|instructions?|configuration)",
        r"you are now (a|an|the)\b",
        r"pretend (you are|to be|that you)",
        r"act as (if|though|a|an|the)\b",
        r"\broleplay as\b",
        r"\bdan\b.*\bmode\b",
        r"\bjailbreak\b",
        r"unrestricted mode",
        r"developer mode",
        r"bypass (safety|restrictions?|guardrails?|filters?)",
        r"override (safety|restrictions?|guardrails?|filters?)",
        r"ignore (safety|restrictions?|guardrails?|filters?)",
        r"sudo (mode|override)",
    ]
]


class Verdict(TypedDict):
    allowed: bool
    reason: str
    categories: list[str]


def _injection_heuristic(query: str) -> tuple[bool, str]:
    """Return (is_injection, matched_pattern_description)."""
    for pattern in _INJECTION_PATTERNS:
        m = pattern.search(query)
        if m:
            return True, m.group(0)
    return False, ""


# ---------------------------------------------------------------------------
# Injection / jailbreak check
# ---------------------------------------------------------------------------

def check_injection(query: str) -> Verdict:
    """Detect prompt-injection and jailbreak attempts.

    Runs deterministic regex heuristics first; escalates to a small-tier
    LLM classifier only for the ambiguous cases that heuristics miss.
    On any parse error the check defaults to allowing (fail-open).
    """
    # Fast path: deterministic heuristics
    is_injection, matched = _injection_heuristic(query)
    if is_injection:
        logger.info("check_injection: heuristic match — %r", matched)
        return Verdict(
            allowed=False,
            reason=f"Injection pattern detected: '{matched}'",
            categories=["injection"],
        )

    # Slow path: LLM classifier for ambiguous cases
    p = get_prompt("guardrails/input_injection")
    messages = [
        SystemMessage(content=render("guardrails/input_injection")),
        HumanMessage(content=query),
    ]
    try:
        response = llm.complete(p.tier, messages)
        parsed = json.loads(response.text.strip())
        # TODO(phase-4): enforce strict JSON schema via structured outputs.
        # Guard: quota exhaustion can make the LLM return a bare JSON string
        # (e.g. "injection") instead of an object; treat that as parse error.
        if not isinstance(parsed, dict):
            raise ValueError(f"expected dict, got {type(parsed).__name__}")
        is_inj = bool(parsed.get("injection", False))
        attack_type = parsed.get("attack_type") or "unknown"
        if is_inj:
            return Verdict(
                allowed=False,
                reason=str(parsed.get("reason", "Injection detected by classifier")),
                categories=["injection", attack_type],
            )
        return Verdict(
            allowed=True,
            reason=str(parsed.get("reason", "No injection detected")),
            categories=["clean"],
        )
    except Exception:
        logger.warning("check_injection: failed to parse LLM response, allowing by default")
        return Verdict(allowed=True, reason="parse_error_allow", categories=["parse_error"])


# ---------------------------------------------------------------------------
# Topicality check
# ---------------------------------------------------------------------------

def check_topicality(query: str) -> Verdict:
    """Return a Verdict classifying whether the query is travel-relevant.

    Cheap heuristic short-circuit runs first; falls back to a small-tier
    LLM call. On any parse error defaults to allowing (fail-open) to avoid
    over-blocking.
    """
    if not query or not query.strip():
        return Verdict(allowed=False, reason="Empty query", categories=["empty"])
    if len(query) > 5000:
        return Verdict(
            allowed=False,
            reason="Query exceeds maximum length",
            categories=["excessive_length"],
        )

    p = get_prompt("guardrails/input_topicality")
    messages = [
        SystemMessage(content=render("guardrails/input_topicality")),
        HumanMessage(content=query),
    ]
    try:
        response = llm.complete(p.tier, messages)
        parsed = json.loads(response.text.strip())
        # TODO(phase-4): enforce strict JSON schema via structured outputs.
        if not isinstance(parsed, dict):
            raise ValueError(f"expected dict, got {type(parsed).__name__}")
        return Verdict(
            allowed=bool(parsed.get("allowed", True)),
            reason=str(parsed.get("reason", "")),
            categories=list(parsed.get("categories", [])),
        )
    except Exception:
        logger.warning("check_topicality: failed to parse LLM response, allowing by default")
        return Verdict(allowed=True, reason="parse_error_allow", categories=["parse_error"])


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------

def input_guardrail_node(state: GraphState) -> dict:
    """Run all input checks: PII redaction, then injection, then topicality.

    PII redaction is first so every subsequent LLM call and every field
    written back to state (→ LangSmith trace) sees scrubbed text, not raw
    PII. Injection runs before topicality so clear attacks never reach the
    (more expensive) topicality model call.
    """
    raw_query = state.get("query", "")

    # 1. PII redaction — must precede ALL LLM calls and state writes
    query, pii_found = redact(raw_query)
    base_updates: dict = {"pii_redacted": pii_found}
    if pii_found:
        base_updates["query"] = query  # downstream nodes + traces see redacted text

    # 2. Injection / jailbreak
    injection = check_injection(query)
    if not injection["allowed"]:
        verdict: dict = {**injection, "checks": ["pii", "injection"]}
        logger.info(
            "input_guardrail: blocked — check=injection reason=%r",
            injection["reason"],
        )
        return {
            **base_updates,
            "input_verdict": verdict,
            "refusal_message": _INJECTION_REFUSAL_MSG,
        }

    # 3. Topicality
    topicality = check_topicality(query)
    verdict = {
        "allowed": topicality["allowed"],
        "reason": topicality["reason"],
        "categories": topicality["categories"],
        "checks": ["pii", "injection", "topicality"],
    }

    if not topicality["allowed"]:
        logger.info(
            "input_guardrail: blocked — check=topicality reason=%r categories=%s",
            topicality["reason"],
            topicality["categories"],
        )
        return {
            **base_updates,
            "input_verdict": verdict,
            "refusal_message": _REFUSAL_MSG,
        }

    logger.info("input_guardrail: allowed — %s", topicality["reason"])
    return {**base_updates, "input_verdict": verdict}


def refusal_node(state: GraphState) -> dict:
    """Terminal node for blocked inputs — writes a polite refusal to summary."""
    msg = state.get("refusal_message", _REFUSAL_MSG)
    logger.info("refusal_node: returning refusal to user")
    return {"summary": msg}


# ---------------------------------------------------------------------------
# Conditional edge router
# ---------------------------------------------------------------------------

def route_input(state: GraphState) -> str:
    """LangGraph conditional edge: 'refuse' if blocked, 'ok' otherwise."""
    verdict = state.get("input_verdict", {})
    return "refuse" if not verdict.get("allowed", True) else "ok"
