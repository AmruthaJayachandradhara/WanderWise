"""LLM-as-judge evals (Phase 5) — faithfulness, decomposition merge quality,
itinerary helpfulness.

Hand-rolled rather than RAGAS: three small judge functions built on the
project's own provider-agnostic LLMClient keep quota control, retries, and
Groq fallback for free, and avoid pulling RAGAS's dependency tree for three
prompts. See docs/eval-report.md for the full trade-off writeup.

Judge calls use settings.JUDGE_MODEL_TIER (a tier, not a pinned model id —
stays provider-agnostic like the rest of the system) and are meant to be
*sampled*, not run on every case every run — see sample_cases() and the
nightly-only wiring in run_prompt_eval.py / eval-nightly.yml.
"""

import logging
import random
from dataclasses import dataclass
from datetime import date

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.config import settings
from backend.app.llm.client import llm
from backend.app.llm.parsing import parse_json_dict

logger = logging.getLogger(__name__)


@dataclass
class JudgeResult:
    score: float
    passed: bool
    reasoning: str
    judge_key: str


def _judge_call(system_prompt: str, human_content: str) -> dict:
    """Call the judge model and parse its JSON verdict. Never raises —
    a parse/call failure returns an empty dict, which callers treat as a
    score of 0.0 (fail closed, not fail open — a broken judge should not
    silently pass quality checks)."""
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_content),
    ]
    try:
        response = llm.complete(settings.JUDGE_MODEL_TIER, messages, json_mode=True)
        return parse_json_dict(response.text.strip(), context="judge")
    except Exception as exc:
        logger.warning("judge call failed: %s", exc)
        return {}


_FAITHFULNESS_PROMPT = """You are a strict faithfulness judge for a travel-assistant RAG answer.

Given an ANSWER and the retrieved CONTEXT it was supposed to be grounded in,
identify which claims in the answer are supported by the context and which
are not (hallucinated or unsupported).

Respond with JSON only:
{"supported_claims": [...], "unsupported_claims": [...], "score": <float 0.0-1.0>}

score = supported_claims / (supported_claims + unsupported_claims), or 1.0 if
the answer makes no checkable claims at all."""


def judge_faithfulness(answer: str, context: str) -> JudgeResult:
    """Is `answer` supported by the retrieved `context`? (RAG grounding judge.)"""
    parsed = _judge_call(
        _FAITHFULNESS_PROMPT,
        f"CONTEXT:\n{context}\n\nANSWER:\n{answer}",
    )
    score = float(parsed.get("score", 0.0))
    reasoning = (
        f"supported={parsed.get('supported_claims', [])} "
        f"unsupported={parsed.get('unsupported_claims', [])}"
    )
    return JudgeResult(
        score=score,
        passed=score >= settings.EVAL_FAITHFULNESS_MIN,
        reasoning=reasoning,
        judge_key="faithfulness",
    )


_MERGE_QUALITY_PROMPT = """You are judging a multi-traveler / multi-city trip-planning answer that was
assembled by merging several independent sub-query results (e.g. one visa
lookup per passport, or one lookup per destination city).

Given the ORIGINAL QUERY, the SUB-QUERIES it was split into, and the final
MERGED ANSWER, judge whether every subject (each passport/destination pair)
is addressed distinctly and correctly, and whether the merge reads as one
coherent answer rather than disconnected fragments.

Respond with JSON only:
{"per_subject": [{"subject": "...", "addressed": true|false}, ...], "score": <float 0.0-1.0>}"""


def judge_merge_quality(query: str, sub_queries: list[dict], answer: str) -> JudgeResult:
    """Does the merged answer correctly and coherently address every sub-query subject?"""
    subjects = ", ".join(
        f"{s.get('passport', '?')}→{s.get('destination', '?')}" for s in sub_queries
    )
    parsed = _judge_call(
        _MERGE_QUALITY_PROMPT,
        f"ORIGINAL QUERY: {query}\nSUB-QUERIES: {subjects}\nMERGED ANSWER:\n{answer}",
    )
    score = float(parsed.get("score", 0.0))
    return JudgeResult(
        score=score,
        passed=score >= settings.EVAL_MERGE_QUALITY_MIN,
        reasoning=f"per_subject={parsed.get('per_subject', [])}",
        judge_key="merge_quality",
    )


_HELPFULNESS_PROMPT = """You are judging the helpfulness of a travel-itinerary summary.

Rate the SUMMARY for the ORIGINAL QUERY on: specificity (concrete dates,
prices, places vs. vague generalities), actionability (could the traveler
act on this directly), and honesty (does it flag degraded/unavailable data
rather than paper over it).

Respond with JSON only:
{"specificity": <float 0-1>, "actionability": <float 0-1>, "honesty": <float 0-1>,
 "score": <float 0-1>}

score is the average of the three sub-scores."""


def judge_helpfulness(query: str, summary: str) -> JudgeResult:
    """Qualitative helpfulness score for an assembled itinerary summary."""
    parsed = _judge_call(
        _HELPFULNESS_PROMPT,
        f"ORIGINAL QUERY: {query}\nSUMMARY:\n{summary}",
    )
    score = float(parsed.get("score", 0.0))
    reasoning = (
        f"specificity={parsed.get('specificity')} "
        f"actionability={parsed.get('actionability')} "
        f"honesty={parsed.get('honesty')}"
    )
    return JudgeResult(
        score=score,
        passed=score >= settings.EVAL_HELPFULNESS_MIN,
        reasoning=reasoning,
        judge_key="helpfulness",
    )


def sample_cases(cases: list[dict], rate: float) -> list[dict]:
    """Deterministically sample `rate` fraction of cases, seeded on today's
    date so a given nightly run is reproducible if re-triggered same-day,
    but the sample rotates day to day for eventual full coverage."""
    if rate >= 1.0:
        return cases
    rng = random.Random(date.today().isoformat())
    k = max(1, round(len(cases) * rate)) if cases else 0
    return rng.sample(cases, k) if k < len(cases) else cases


def log_feedback(run_id: str | None, result: JudgeResult) -> None:
    """Log a judge score as LangSmith feedback on the given run, so the
    per-prompt / eval-over-time dashboard panels (Step 6 of
    docs/wanderwise_phase5.md) can group scores by prompt_id/version.

    No-op (with a debug log) if LANGSMITH_API_KEY isn't set or run_id is
    None (e.g. tracing disabled) — judge evals must not fail the caller
    just because feedback logging isn't available.
    """
    if not settings.LANGSMITH_API_KEY or not run_id:
        logger.debug("log_feedback: skipped (no LANGSMITH_API_KEY or run_id) — %s", result.judge_key)
        return
    try:
        from langsmith import Client

        Client().create_feedback(
            run_id,
            key=result.judge_key,
            score=result.score,
            comment=result.reasoning,
        )
    except Exception as exc:
        logger.warning("log_feedback: failed to write feedback for %s — %s", result.judge_key, exc)


def _smoke_test() -> None:
    """Canned grounded vs. ungrounded pair — grounded must score higher."""
    context = "Japan requires a valid passport. US citizens may enter visa-free for stays up to 90 days for tourism."
    grounded_answer = "US citizens can visit Japan visa-free for up to 90 days for tourism."
    ungrounded_answer = "US citizens need a $500 visa fee and a letter of invitation to enter Japan."

    grounded = judge_faithfulness(grounded_answer, context)
    ungrounded = judge_faithfulness(ungrounded_answer, context)

    print(f"grounded:   score={grounded.score:.2f} passed={grounded.passed} — {grounded.reasoning}")
    print(f"ungrounded: score={ungrounded.score:.2f} passed={ungrounded.passed} — {ungrounded.reasoning}")
    assert grounded.score > ungrounded.score, "grounded answer should score higher than ungrounded"
    print("OK — grounded answer scored higher than ungrounded")


if __name__ == "__main__":
    _smoke_test()
