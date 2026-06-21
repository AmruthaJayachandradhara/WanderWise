# WanderWise — Phase 5: Eval Depth, Dashboards & CI/CD
### Phase Design Document (implementation roadmap, code-light)

| | |
|---|---|
| **Phase** | 5 of 6 — Eval Depth, Dashboards & CI/CD |
| **Goal** | Make the quality and observability story airtight and gate it: expand the eval suite to its full surface, surface live dashboards, and finalize the CI/CD pipeline |
| **Duration** | ~Week 5 |
| **Prereq** | Phase 4 complete — full demo narrative works end-to-end; eval harness has been grown incrementally since Phase 1; LangSmith tracing always-on since Phase 1 |
| **Reframing** | Because the harness, the CI gate, and tracing were seeded in Phase 1 and grown every phase, Phase 5 is **depth and finalization, not a from-scratch build** — the design-review fix paying off |
| **Exit milestone** | A recruiter opens the URL, runs the full demo, and sees live dashboards plus a passing eval gate — and a deliberately-introduced regression demonstrably turns the gate red and blocks deploy |

---

## What Phase 5 is (and isn't)

Phase 5 turns the always-on plumbing into a *story you can screen-share*. Nothing here is net-new infrastructure — the eval harness has existed since Phase 1 Step 8, tracing has captured tier/token/latency since Phase 1 Step 3, and the CI gate has failed builds on regressions since the start. Phase 5 brings all of it to interview-grade: the eval set reaches its **full ~40-case surface**, evals split cleanly into **deterministic (always-run)** vs. **LLM-as-judge (sampled)**, the **CI gate is hardened** so a quality regression blocks deploy, **dashboards** surface the metrics that prove the cost/latency/reliability story, and the **CI/CD pipeline** is finalized end to end.

This phase is also where the **free-tier trace-cap discipline** finally matters in practice. Always-on tracing plus a full eval run generates real volume against LangSmith's free Developer tier. The `TRACE_SAMPLING` flag seeded in Phase 1 gets used here: full tracing for interactive/demo runs, sampled tracing for high-volume eval runs, so the monthly cap isn't burned by CI.

What Phase 5 is *not*: no new product capability, no booking/RAG/agent changes, no frontend polish (Phase 6 — though the dashboard is a deliverable here, it's LangSmith's UI, not your React app).

---

## Repo structure at the end of Phase 5

Complete root tree, incremental from Phase 4: **(new)** = created this phase, **(extended)** = changed this phase, **(unchanged)** = carried forward. Every root-level subdirectory is shown. State schema and tool contract remain stable.

```
wanderwise/
├── README.md                        # + dashboard screenshots, eval-gate explanation (extended)
├── .env / .env.example              # + eval sampling/judge-model config (extended)
├── .gitignore                       # (unchanged)
├── pyproject.toml                   # + ragas (optional), eval/judge deps (extended)
├── Dockerfile                       # (unchanged)
├── docker-compose.yml               # (unchanged)
├── docs/
│   ├── design-doc.md                # (unchanged)
│   ├── decision-log.md              # (unchanged)
│   ├── phase0–4.md                  # (unchanged)
│   ├── phase5.md                    # (new)
│   └── eval-report.md               # eval methodology + current scores (new)
├── .github/workflows/
│   ├── ci.yml                       # hardened: lint + test + eval-gate + deploy (extended)
│   ├── reingest.yml                 # (unchanged)
│   └── eval-nightly.yml             # fuller sampled LLM-judge eval run, off the PR path (new)
├── backend/
│   ├── app/
│   │   ├── config.py                # + judge model, sampling rates, eval thresholds (extended)
│   │   ├── observability/           # + dashboard/metric helpers; sampling enforcement (extended)
│   │   │   ├── tracing.py           # (Phase 1 — LangSmith setup)
│   │   │   └── metrics.py           # cost-by-tier, cache-hit, retry-rate aggregation (new)
│   │   └── ... (orchestrator, agents, booking, rag, guardrails, memory, reliability, tools,
│   │            reservation_service, llm, state — all unchanged)
│   └── tests/
│       ├── unit/                    # (unchanged)
│       └── eval/
│           ├── dataset.jsonl        # expanded to full ~40-case set (extended)
│           ├── run_eval.py          # deterministic CI-gating checks (extended)
│           ├── run_prompt_eval.py   # (extended — metric: llm_judge now wired for sampled nightly runs)
│           ├── judges.py            # LLM-as-judge: faithfulness, decomposition merge, helpfulness (new)
│           └── report.py            # aggregate scores → eval-report.md + LangSmith (new)
├── frontend/                        # (unchanged — polish is Phase 6)
│   └── src/{components, hooks, api}/
├── data/
│   ├── corpus/                      # (unchanged)
│   └── fixtures/                    # (unchanged — reused as eval inputs where useful)
└── scripts/
    ├── ingest_corpus.py             # (unchanged)
    ├── reingest.py                  # (unchanged)
    └── run_dashboards.py            # one-shot: push/refresh dashboard metrics (new)
```

---

## Build order at a glance

Expand the eval set first (1–2), split deterministic vs. judge (3), harden the gate (4), build dashboards (5–6), finalize CI/CD (7), then document and verify (8–10).

| Step | Builds | Depends on |
|---|---|---|
| 1 | Expand `dataset.jsonl` to the full ~40-case labeled set | Phase 1–4 eval cases |
| 2 | Complete the deterministic metrics (Hit@k, routing, budget, decomposition, fault-injection) | 1 |
| 3 | LLM-as-judge evals (faithfulness, merge quality, helpfulness), sampled | 1 |
| 4 | Harden the CI eval gate (thresholds block deploy) | 2, 3 |
| 5 | Metrics aggregation (cost-by-tier, cache-hit, retry-rate) | observability (P1) |
| 6 | LangSmith dashboards (latency, cost, cache, retry, eval-over-time) | 5 |
| 7 | Finalize CI/CD pipeline (+ nightly judge run, sampling discipline) | 4, 6 |
| 8 | Eval report doc | 2, 3 |
| 9 | Trace-cap / cost sanity pass | 6, 7 |
| 10 | Verify the milestone | all |

---

## Step 1 — Expand the eval dataset to the full ~40-case set

**Objective:** A small, honest, comprehensive labeled set covering every capability the system now has.

**Build (`backend/tests/eval/dataset.jsonl`):**
- Consolidate the cases grown across phases and fill gaps to ~40 labeled cases spanning: **visa retrieval** (Hit@k), **decomposition** (multi-passport/multi-city splits + merges), **budget validity**, **itinerary temporal validity**, **routing** (expected tier per case), **guardrail red-team** (off-topic, injection, PII, jailbreak) + valid-input controls (for false-block measurement), and **fault-injection** (tool/LLM failures → handled).
- Reuse Phase 2/4 **fixtures** as eval inputs where they fit — labeled fixtures are free eval cases.

**Key detail:** keep it small and honest (the design doc's framing). ~40 well-chosen cases that demonstrate discipline beat 400 noisy ones. Each case carries its expected label so checks are objective. This is a portfolio artifact — the *methodology* signals seniority more than the count.

**Done when:** `dataset.jsonl` holds ~40 labeled cases covering every capability, each with an expected label.

---

## Step 2 — Complete the deterministic metrics

**Objective:** The cheap, always-run, CI-gating checks — everything measurable without an LLM judge.

**Build (`backend/tests/eval/run_eval.py`):**
- **Retrieval Hit@5** (≥85%) against labeled visa queries.
- **Routing accuracy** (≥90%) — chosen tier matches the expected label, audited from traces.
- **Decomposition correctness** (≥90%) — sub-query split + merge match labels (structural parts; merge *quality* is a judge metric in Step 3).
- **Budget + temporal validity** (100%) — deterministic itinerary checks.
- **Guardrail block / false-block** (≥95% / <5%) on the red-team + valid sets.
- **Fault-injection handling** (100%) — injected failures are retried or gracefully degraded.

**Key detail:** these run on **every push** because they're cheap and deterministic — no judge cost, no flakiness. They're the gate. The expensive judge metrics (Step 3) are sampled and largely off the PR path so CI stays fast and free.

**Done when:** `run_eval.py` reports all deterministic metrics against the full set, with pass/fail vs. thresholds.

---

## Step 3 — LLM-as-judge evals (sampled)

**Objective:** The quality dimensions that need a judge — faithfulness, decomposition *merge quality*, itinerary helpfulness.

**Build (`backend/tests/eval/judges.py`):**
- **Faithfulness** (≥0.90) — RAG answers supported by retrieved context (the grounding judge from Phase 3, now measured systematically).
- **Decomposition merge quality** — the merged multi-traveler answer is correct and well-composed, not just structurally split.
- **Itinerary helpfulness** — sampled qualitative score.
- Use a capable model as judge (configurable via `config.py`); **sample** rather than judging every case every run, to respect cost and the LangSmith trace cap.
- Optionally use **RAGAS** (Phase 0/tooling) for faithfulness/retrieval metrics — it's purpose-built and a recognizable name in interviews.

> **Prompt versioning thread:** `run_prompt_eval.py` (seeded in Phase 1) already has the `metric: llm_judge` branch — it was stubbed with a warning in Phase 1. Phase 5 wires it: for any prompt YAML with `metric: llm_judge`, the per-prompt runner now calls the judge model instead of skipping. This means activating the judge for `output_grounding.yaml` (Phase 3), `rag/synthesis.yaml` (Phase 2), and `orchestrator/assemble_itinerary.yaml` (Phase 1) is purely a YAML field + a per-prompt eval case update — no new runner code.

**Key detail:** judge evals are **sampled and run nightly / off the PR path**, not on every push. They inform the dashboard and the eval report; they don't block every commit (a flaky judge shouldn't fail an unrelated PR). Be explicit about this split — it's a sign of eval maturity.

**Done when:** judge metrics produce faithfulness/merge/helpfulness scores on a sample, logged to LangSmith and the eval report.

---

## Step 4 — Harden the CI eval gate

**Objective:** A regression below threshold fails the build and blocks deploy — the trustworthiness story made real.

**Build (`.github/workflows/ci.yml`):**
- The gate runs the **deterministic** suite (Step 2) on every push/PR; if Hit@5, routing, decomposition, guardrail, budget, or fault-injection regresses below threshold, **the build fails and won't deploy**.
- Thresholds live in `config.py` (single source). Failures report *which* metric regressed.
- Keep judge evals **out** of the blocking gate (sampled nightly via `eval-nightly.yml`) so CI stays fast, deterministic, and free.

**Key detail:** this directly answers the JD language on drift and trustworthiness — "a CI gate has blocked deploys on quality regression since commit one." The demo of this is deliberately breaking something (e.g., degrading the retriever) and watching CI go red — prepare that as a showable moment.

**Done when:** a deliberate regression (e.g., a broken retriever or mis-routed tier) turns CI red and blocks deploy; reverting it goes green.

---

## Step 5 — Metrics aggregation

**Objective:** Turn the per-run trace fields (captured since Phase 1) into the aggregates the dashboards need.

**Build (`backend/app/observability/metrics.py`):**
- Aggregate from traces: **token cost by tier** (the routing-savings story — Flash-Lite vs. Flash spend), **cache-hit rate** (semantic + API), **retry rate** (infra + quality), end-to-end **latency** distribution, and **eval scores over time**.
- These derive from the four fields every trace has recorded since Phase 1 Step 3 (tier, model, tokens, latency) plus the cache/retry/guardrail flags added in Phase 3 — nothing new to instrument, just to aggregate.

**Key detail:** the cost-by-tier metric is the visible payoff of the entire routing layer — it quantifies "the router saved X% by sending classification to Flash-Lite." Make sure it cleanly separates spend per tier so the savings are legible.

**Done when:** metrics.py produces cost-by-tier, cache-hit, retry-rate, and latency aggregates from traces.

---

## Step 6 — LangSmith dashboards

**Objective:** The live artifact you screen-share in interviews.

**Build (LangSmith + `scripts/run_dashboards.py`):**
- Dashboards for: **latency**, **token cost by tier**, **cache-hit rate**, **retry rate**, and **eval scores over time**.
- Add a **per-prompt eval score breakdown**: because every trace records `prompt_id` and `prompt_version` (seeded in Phase 1's `trace_metadata()`), a dashboard panel showing eval scores grouped by `prompt_id` and `version` is a query, not new instrumentation. This makes prompt regressions attributable — "faithfulness dropped on `rag/synthesis` v2, not on the retriever" — without any new tagging work.
- Use LangSmith's dashboard/monitoring features (same product as tracing, so this extends what's already there). `run_dashboards.py` pushes/refreshes any custom aggregates from Step 5.
- Capture **screenshots into the README** (Phase 6 will reference them) so the story survives even if the live dashboard is mid-refresh during an interview.

**Key detail:** this is the single best screen-share in the whole project — it makes the invisible production concerns (cost, cache, reliability) visible. Treat it as a deliverable, not a byproduct. Because it's LangSmith's UI, it's not gated behind your free-tier web app's cold starts.

**Done when:** dashboards render the five metric families live, and screenshots are saved for the README.

---

## Step 7 — Finalize the CI/CD pipeline

**Objective:** A clean, complete pipeline: lint + test + eval-gate + deploy, with the judge run off the PR path.

**Build (`.github/workflows/ci.yml`, `eval-nightly.yml`):**
- `ci.yml`: lint → unit tests → **deterministic eval gate** → deploy on merge to `main` (the deploy step proven since Phase 1).
- The CI pipeline now has **three layers**: (1) per-prompt gate (`run_prompt_eval.py` — fast, deterministic + schema_valid metrics on every push), (2) full-graph deterministic gate (`run_eval.py` — every push), (3) sampled LLM-judge run (`eval-nightly.yml` — nightly, off the PR path). Layer 1 isolates prompt regressions before they reach layer 2; a prompt-only change that passes layer 1 can skip the slower layer 2 diagnosis entirely.
- `eval-nightly.yml`: the fuller **sampled LLM-judge** run on a schedule, writing scores to the dashboard + eval report — not blocking PRs.
- Enforce **trace sampling** in CI runs (the Phase 1 flag) so eval runs don't burn the LangSmith free-tier cap.

**Key detail:** the two-workflow split (fast deterministic gate on every push; richer sampled judge nightly) is the mature pattern — it keeps the feedback loop fast and free while still measuring the expensive quality dimensions regularly. Name and explain this split; it reads as production experience.

**Done when:** every push runs lint + tests + deterministic gate + deploy-on-merge; the nightly judge run posts scores without blocking PRs.

---

## Step 8 — Eval report

**Objective:** A documented methodology + current scores — a portfolio artifact and interview reference.

**Build (`docs/eval-report.md`, `backend/tests/eval/report.py`):**
- `report.py` aggregates the latest deterministic + judge scores into `eval-report.md`: what's measured, how, current scores vs. targets, and the deterministic-vs-judge split.
- State the methodology honestly — small labeled set, sampled judging, CI-gated deterministic metrics.

**Key detail:** the report is where you articulate *why* you measure what you measure — that reasoning is the senior signal. "I gate deterministically and judge by sampling because..." is a stronger interview answer than a wall of numbers.

**Done when:** `eval-report.md` documents methodology and current scores, regenerable via `report.py`.

---

## Step 9 — Trace-cap / cost sanity pass

**Objective:** Confirm the always-on observability story doesn't quietly blow the free tiers.

**Build / verify:**
- Confirm **trace sampling** is enforced for eval/CI runs and full for interactive/demo runs (the Phase 1 flag, finally exercised at volume).
- Sanity-check that a full demo run + a CI run stays within LangSmith's free Developer-tier monthly trace cap and the Gemini 1,500 RPD limit (lean on Phase 2 fixtures + Phase 3 caches for demos).
- Document the sampling policy in the eval report.

**Key detail:** this is the practical consequence of "observability always-on from day one" meeting a free-tier reality. Showing you *manage* the cap (sampling, fixtures, caching) rather than ignore it is itself a cost-awareness signal — the same instinct as the routing layer.

**Done when:** sampling policy is enforced and documented; a full demo + CI cycle stays within free-tier caps.

---

## Step 10 — Verify the milestone

**Verify the exit milestone:**
1. Open the **live URL**; run the full multi-passport demo.
2. Open **LangSmith dashboards**; confirm latency, cost-by-tier, cache-hit, retry-rate, and eval-over-time all render.
3. Confirm the **CI eval gate** passes on `main`.
4. **Deliberately introduce a regression** (degrade the retriever or mis-route a tier) → confirm CI goes **red** and blocks deploy; revert → green.
5. Confirm the **nightly judge run** posts faithfulness/merge/helpfulness scores without blocking PRs.
6. Confirm a full demo + CI cycle **stays within free-tier caps** (sampling + fixtures + caches).

---

## Phase 5 exit checklist

- [ ] `dataset.jsonl` expanded to the full ~40 labeled cases across all capabilities.
- [ ] Deterministic metrics complete: Hit@5, routing, decomposition, budget/temporal, guardrail block/false-block, fault-injection.
- [ ] LLM-as-judge evals (faithfulness, merge quality, helpfulness) running sampled, off the PR path.
- [ ] CI eval gate hardened: deterministic regression below threshold fails the build and blocks deploy.
- [ ] Metrics aggregation: cost-by-tier, cache-hit, retry-rate, latency from traces.
- [ ] LangSmith dashboards render all five metric families; screenshots saved for README.
- [ ] CI/CD finalized: fast deterministic gate on every push; sampled judge nightly; deploy on merge.
- [ ] Eval report documents methodology + current scores, regenerable.
- [ ] Trace-sampling policy enforced and documented; full demo + CI stays within free-tier caps.
- [ ] Milestone verified — including a deliberate regression turning the gate red.
- [ ] `metric: llm_judge` wired in `run_prompt_eval.py`; prompt YAMLs with judge metrics run sampled nightly via `eval-nightly.yml`.
- [ ] Per-prompt eval score dashboard panel shows scores by `prompt_id` and `version`; a deliberate prompt regression is attributable to a specific prompt+version.

---

## What is NOT in Phase 5 (deferred)

No new product capability (agents/booking/RAG are frozen), no frontend polish (Phase 6 — the dashboards here are LangSmith's UI, not your React app), no demo video / README finalization beyond capturing dashboard screenshots (Phase 6), no resume/interview-narrative finalization (Phase 6). No new prompt YAML files (all prompts were added in Phases 1–4). No changes to the prompt library structure — Phase 5 only activates the `metric: llm_judge` path in the existing runner.

---

## Hand-off to Phase 6

Phase 6 ("Frontend Polish, Demo Hardening & Documentation") makes everything recruiter-ready. The React app gets **polished** (itinerary cards with day-by-day structure, a budget bar, inline citations, reservation-confirmation and action-draft UI) — building on the just-enough UI each phase added, so this is genuine polish, not a frontend cliff. **Demo hardening** finalizes the fixture-backed fallback (built since Phase 2) and a **recorded demo video** so a rate-limit or cold start can never kill a live walkthrough. **Documentation** lands the README (with the architecture diagram and the Phase 5 dashboard screenshots), the demo script, and the **resume framing + interview narratives** tying each system component to a JD ask. Exit milestone: a recruiter opens the live URL, runs the demo, reads the README, and can watch a backup video — and you can walk any component from diagram → code → trace → dashboard. Phase 6 also finalises the prompt-versioning narrative in the README — one verifiable line ("every prompt is versioned, independently eval-gated in CI, and every trace records the prompt version") and a pointer to `backend/app/prompts/library/` so it's inspectable during an interview.
