# WanderWise — Build Index
### Top-level guide to the phased build plan

| | |
|---|---|
| **Project** | WanderWise — AI Travel Planning Agent (production-shaped agentic system; AI Engineer / FDE portfolio artifact) |
| **Source of truth** | `design-doc.md` (the full v4 engineering design doc) — this index sequences it into buildable phases |
| **Phases** | 0 → 6 (Phase 0 is setup-only; Phases 1–6 each ship something demoable) |
| **Total timeline** | ~5 weeks (Phase 0 ≈ ½ day up front) |
| **How to use** | Read this page to orient; open the matching `phaseN.md` to build. Build phases in order — each slots into the proven frame of the one before |

---

## The phases at a glance

| Phase | Doc | Focus | Exit milestone |
|---|---|---|---|
| **0** | `phase0.md` | Decisions, accounts, dev env (no code) | All decisions locked, keys provisioned + smoke-tested, repo + toolchain ready |
| **1** | `phase1.md` | Foundation & skeleton | Traced weather query on a live URL; trace shows the model tier; CI eval-gate live |
| **2** | `phase2.md` | Core data agents + router (Travel Search → RAG) | Japan query → budget-aware itinerary with flights, hotels, weather, cited visa; routing in traces |
| **3** | `phase3.md` | Guardrails, reliability & advanced memory | Red-team blocked; induced hallucination caught + corrected; preference recalled across sessions; cache hit cuts latency |
| **4** | `phase4.md` | Booking, actions & advanced RAG | Full multi-passport demo: real flight booking + restaurant reservation (confirmation IDs) + calendar + drafted email; staleness re-ingest |
| **5** | `phase5.md` | Eval depth, dashboards & CI/CD | Live dashboards + passing eval gate; a deliberate regression turns the gate red and blocks deploy |
| **6** | `phase6.md` | Frontend polish, demo hardening & docs | Recruiter-ready: live URL + README + backup video; walkable diagram → code → trace → dashboard |

---

## Dependency flow

```
Phase 0  ─ decisions + keys + dev env (no code)
   │
Phase 1  ─ skeleton: config · LLM abstraction (2-tier + Groq fallback) · LangSmith tracing
   │        · 1 agent (Weather) · FastAPI/SSE · React chat · EVAL HARNESS + CI GATE (seeded) · DEPLOY
   │
Phase 2  ─ Travel Search (Duffel) → RAG (hybrid+rerank, cited) · router live · parallelism
   │        · budget reasoning · basic memory · retrieval eval cases · demo fixtures (start)
   │
Phase 3  ─ guardrails (in/out) · infra retry + self-reflection · advanced memory (summary/longterm/cache)
   │        · no-hallucinated-booking gate DESIGNED (tested in P4) · red-team eval cases
   │
Phase 4  ─ BookingProvider · mock reservation service · real Duffel booking · booking gate ENFORCED
   │        · Action agent (calendar + gated email) · Activities subagent · query decomposition · staleness
   │
Phase 5  ─ full ~40-case eval · deterministic (gating) vs LLM-judge (sampled) · dashboards · CI/CD finalized
   │
Phase 6  ─ UI polish · demo mode (fixtures) + video · README + architecture diagram · interview narratives
   │
  MVP complete ─→ post-MVP backlog (multi-user, FinTravel, Sabre, real payments, …)
```

---

## Cut-line discipline (when a week slips)

Two layers of pre-decided cuts so a slip means trimming depth in order, not panicking.

**Project-level cut order** (from the design doc): complexity-based routing (keep deterministic) → automated staleness (keep manual re-ingest script) → drafted email action (keep calendar + booking summary) → semantic cache (keep API cache) → frontend polish.

**Never cut:** the orchestration loop · 2-tier routing (≥ deterministic) · RAG with citations + decomposition · core guardrails (grounding + no-hallucinated-booking) · one real action + one real sandbox reservation · always-on tracing · live deployment.

**Phase 3 internal cut line** (the densest phase): semantic cache → semantic recall → summary sophistication → circuit breaker. Never cut: input topicality + injection, PII redaction, infra backoff + fallback, output grounding/schema/budget, the self-reflection loop.

---

## Threads that run through every phase

A few decisions hold the whole plan together — worth keeping in mind regardless of which phase you're in.

**Two commitments are expensive to change; everything else is cheap.** The **state schema** and the **tool contract** are set deliberately in Phase 1 and only ever extended, never rebuilt — five agents and every later subsystem depend on them. The repo layout, by contrast, is a living map: each phase's tree uses (new)/(extended)/(unchanged)/(placeholder) tags so you can trace any directory's lifecycle, but you should rename/split/merge freely as implementation teaches you the real boundaries.

**Eval and demo-safety are cross-cutting, not terminal.** The eval harness + CI gate are seeded *empty* in Phase 1 and grown every phase (retrieval cases in P2, red-team in P3, decomposition in P4, full set in P5) — so Phase 5 is depth, not a from-scratch build. Demo fixtures are captured from Phase 2 onward — so Phase 6 hardening is finalization, not a scramble.

**Observability is always-on from day one.** LangSmith tracing records tier/token/latency from the first LLM call (P1); the cost-by-tier, cache-hit, and retry-rate dashboards in P5 just aggregate fields already being captured. A `TRACE_SAMPLING` flag (seeded P1, exercised P5) keeps always-on tracing inside LangSmith's free Developer-tier cap.

**One dependency is handled deliberately across phases.** The no-hallucinated-booking guardrail is *designed* as a structural seam in Phase 3 but *enforced and tested* in Phase 4 — because you can't validate a gate against an agent (Booking/Action) that doesn't exist yet.

**Safety is structural, not prompted.** The booking gate keys on a confirmation ID existing in state (only a real provider call produces one); high-risk actions (email/booking) sit behind graph-edge confirmation gates, not model discretion. No real payments anywhere — the highest-harm failure mode is designed out.

**UI grows incrementally.** Each phase ships just-enough UI for its capability, so Phase 6 is genuine polish rather than a frontend cliff.

---

## Locked decisions (carried into every phase)

| Area | Choice |
|---|---|
| LLM provider | Google Gemini API (AI Studio free tier): Flash-Lite (small) + Flash (large) + Gemini Embedding; Groq fallback |
| Orchestration | LangGraph (plan-act-observe-reflect state graph) |
| Observability + eval | **LangSmith** (free Developer tier — tracing + datasets/eval in one product) |
| Booking | Duffel (real flight sandbox) + self-built mock reservation service, both behind one `BookingProvider` |
| Hotels | **Booking enabled** (Duffel Stays, same token) — search in Phase 2, booking in Phase 4 |
| Backend / Frontend | Python + FastAPI (SSE) / React (Vite) |
| Vector DB | **Qdrant** (native hybrid search; Qdrant Cloud free tier for deploy, local Docker for dev) |
| Embeddings | **Gemini Embedding** (`bge-small-en` offline fallback) |
| Cache / session | **Redis (Upstash free tier)** |
| Long-term store | SQLite (MVP) → Supabase (post-MVP) |
| Guardrails | Custom via LangChain middleware + LangGraph edges |
| Re-ingestion | GitHub Actions scheduled workflow |
| PII | Microsoft Presidio |
| Deployment | **Hugging Face Spaces** (Docker; single deployable serving React static from FastAPI) |
| Demo countries | **50** — major economies/superpowers (incl. China, Russia), Middle East, + advisory-level spread for the travel-warning use case |

*(All eight Phase 0 decisions are locked — see the Phase 0 decision log, the runtime config source of truth.)*

---

## File map

```
docs/
├── design-doc.md        ← full engineering design doc (the "what" and "why")
├── decision-log.md      ← your locked choices (Phase 0) — config source of truth
├── build-index.md       ← this file (the "in what order")
├── phase0.md            ← decisions, accounts, dev env
├── phase1.md            ← foundation & skeleton
├── phase2.md            ← core data agents + router
├── phase3.md            ← guardrails, reliability & advanced memory
├── phase4.md            ← booking, actions & advanced RAG
├── phase5.md            ← eval depth, dashboards & CI/CD
└── phase6.md            ← frontend polish, demo hardening & docs
```

**Start here:** Phase 0 → lock the decision log → build Phases 1–6 in order. Each phase doc opens with its own complete repo tree, a build-order table, step-by-step instructions, an exit checklist, and a hand-off to the next.
