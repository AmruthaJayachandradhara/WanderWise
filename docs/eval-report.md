# WanderWise Eval Report

Generated: 2026-07-27T02:23:31.145335+00:00 — commit `83f3209`

## Methodology

WanderWise's eval suite splits into two tiers, on purpose:

- **Deterministic checks** (`run_eval.py`, `run_prompt_eval.py` without `--judge`)
  run on every push. They're cheap, free of LLM-judge cost, and never flaky —
  exactly what should gate a merge. They cover routing tier accuracy,
  retrieval Hit@5, decomposition structure, budget/temporal validity,
  guardrail block/false-block rates, and fault-injection handling.
- **LLM-as-judge checks** (`judges.py`, `run_prompt_eval.py --judge`) cover the
  quality dimensions that need a judge — faithfulness, decomposition merge
  quality, itinerary helpfulness. These are *sampled* and run *nightly*, off
  the PR path (`.github/workflows/eval-nightly.yml`), so a flaky judge call
  never blocks an unrelated PR, and the free-tier LLM/LangSmith quota isn't
  burned re-judging every case on every push.

The eval set is intentionally **small and honest** (~40 labeled cases) rather
than large and noisy — each case carries an explicit expected label, so every
check is objective. The methodology is the signal here, not the case count.

**Judges are hand-rolled**, not RAGAS: three small functions
(`judge_faithfulness`, `judge_merge_quality`, `judge_helpfulness` in
`backend/tests/eval/judges.py`) built directly on the project's own
provider-agnostic `LLMClient`. That keeps quota control, retries, and Groq
fallback for three prompts' worth of judging without pulling RAGAS's
dependency tree or building a second LLM-calling path outside the system's
existing reliability layer. The trade-off: less interview name-recognition
than RAGAS, in exchange for consistency with how every other LLM call in the
system is made, retried, and traced.

## Deterministic metrics (gate every push)

| Metric | Target | Current | CI-blocking | Status |
|---|---|---|---|---|
| Guardrail block rate | 95% | 100% | yes | PASS |
| Guardrail false-block rate | 5% | 0% | yes | PASS |
| Routing tier accuracy | 90% | 100% | yes | PASS |
| Decomposition correctness | — | no cases | yes | not computed |
| Budget validity | — | no cases | yes | not computed |
| Temporal validity | — | no cases | yes | not computed |
| Retrieval Hit@5 | 85% | 0% | yes | FAIL |
| Fault-injection handling | 100% | 100% | yes | PASS |

Suite: `ci` — 23 cases, 9 failure(s). Generated: 2026-07-26T19:51:29.108707+00:00

## LLM-as-judge metrics (sampled, nightly, non-blocking)

| Prompt | Metric | Threshold | Cases judged | Result |
|---|---|---|---|---|
| guardrails/output_grounding | grounding_label_agreement | 1.00 | 5 | PASS (5/5) |
| rag/synthesis | faithfulness | 0.90 | 3 | PASS (3/3) |
| orchestrator/assemble_itinerary | helpfulness | 0.70 | 2 | PASS (2/2) |

## Per-prompt eval results

| Prompt | Cases | Passed | Pass rate |
|---|---|---|---|
| guardrails/output_grounding | 5 | 5 | 100% |
| orchestrator/assemble_itinerary | 2 | 2 | 100% |
| rag/synthesis | 3 | 3 | 100% |

## Observability aggregates (last 7 days)

_LangSmith unavailable (no API key configured, or the API call failed) — observability aggregates not computed this run._

## Sampling & free-tier policy

| Context | TRACE_SAMPLING | Rationale |
|---|---|---|
| Interactive/demo | 1.0 (full) | Every trace visible for a live walkthrough |
| Nightly eval (`eval-nightly.yml`) | 0.25 | Full 40-case suite + judge sampling generates real volume; sampled tracing respects LangSmith's free Developer-tier trace cap |
| PR-path CI (`ci.yml`) | 0 (off) | Fast, free, deterministic gate — tracing adds no signal to a pass/fail gate |

Judge sampling: `JUDGE_SAMPLE_RATE=0.5` of eligible
cases per nightly run (seeded on the date, so the sample rotates day to day
for eventual full coverage rather than always judging the same subset).

Gemini free-tier limit: 1,500 requests/day. A full nightly run (~40 graph
cases, ~17 of which call the LLM, plus sampled judge calls) stays well under
that even without fallback. Groq is wired as a fallback provider so transient
429s during a burst (e.g. all 13 per-prompt suites plus the graph suite
running close together) are absorbed rather than surfaced as stubs.

