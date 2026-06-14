# WanderWise — Phase 1: Foundation & Skeleton
### Phase Design Document (implementation roadmap, code-light)

| | |
|---|---|
| **Phase** | 1 of 6 — Foundation & Skeleton |
| **Goal** | Prove the full path works end-to-end before any real complexity: one traced query, running on a live URL, with the LLM router, observability, eval harness, and CI all wired in skeleton form |
| **Duration** | ~Week 1 |
| **Prereq** | Phase 0 complete — all decisions locked, all keys provisioned and smoke-tested, repo + toolchain ready |
| **Defining principle** | **De-risk the scary stuff now.** Deployment, config/secrets, LLM provider friction, tracing, and CI are the things that sink projects in the final week. Phase 1 does all of them while the system is trivially simple. |
| **Exit milestone** | A recruiter-openable live URL where a weather query runs end-to-end, is fully traced in LangSmith, and the trace shows which model tier executed |

---

## Repository Structure (as of Phase 1 — evolves each phase)

The structure below reflects what exists at the **end of Phase 1**. It is the skeleton the rest of the project grows into — directories are created now even when empty, so later phases have an obvious home for every file. Expect this tree to expand significantly: Phase 2 fills `agents/`, `tools/`, and `rag/`; Phase 3 fills `guardrails/`, `reliability/`, and `memory/`; Phase 4 fills `reservation_service/` and `agents/activities_booking.py`; Phase 5 completes `tests/eval/`. The tree is annotated to show what exists now vs. what is a placeholder for later.

```
wanderwise/
│
├── README.md                          # project overview (minimal now, expanded Phase 6)
├── .env                               # local secrets — never committed
├── .env.example                       # committed template; one var per line, no values
├── .gitignore                         # excludes .env, __pycache__, .venv, node_modules, vector DB files
├── .pre-commit-config.yaml            # secret scanner (gitleaks) wired in Phase 0
├── docker-compose.yml                 # local: backend + qdrant + redis (no Ollama); extended later phases
├── pyproject.toml                     # Python package metadata + deps (managed via uv)
│
├── docs/
│   ├── design-doc.md                  # the master v4 design doc
│   ├── decision-log.md                # Phase 0 decisions + smoke-test results
│   ├── architecture.png               # placeholder; diagram added Phase 6
│   └── phases/                        # per-phase design documents (this file lives here)
│       ├── phase0.md
│       ├── phase1.md                  # this document
│       └── ...                        # phases 2–6 added as built
│
├── .github/
│   └── workflows/
│       ├── ci.yml                     # lint + test + eval-gate + deploy (seeded Phase 1, hardened Phase 5)
│       └── reingest.yml               # scheduled staleness re-ingestion (added Phase 4)
│
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                    # FastAPI app, routes, SSE endpoint, health check
│   │   ├── config.py                  # all runtime config from .env (Pydantic BaseSettings)
│   │   │
│   │   ├── llm/                       # ← BUILT Phase 1
│   │   │   ├── __init__.py
│   │   │   ├── client.py              # complete(tier, messages) interface; tier → model resolution
│   │   │   └── providers/
│   │   │       ├── gemini.py          # Gemini 2.5 Flash-Lite + Flash via OpenAI-compat endpoint
│   │   │       └── groq.py            # Groq fallback (Llama-3.3-70B); activated by config flag
│   │   │
│   │   ├── observability/             # ← BUILT Phase 1
│   │   │   ├── __init__.py
│   │   │   └── tracing.py             # LangSmith init; trace decorators; tier/token/latency capture
│   │   │
│   │   ├── orchestrator/              # ← SKELETON Phase 1; extended every later phase
│   │   │   ├── __init__.py
│   │   │   ├── graph.py               # LangGraph graph definition (grows each phase)
│   │   │   ├── state.py               # typed graph state schema (multi-user-ready with user_id)
│   │   │   ├── router.py              # 2-tier routing node (deterministic Phase 1; complexity-aware Phase 2+)
│   │   │   └── nodes/                 # plan, assemble, gates, reflection — added per phase
│   │   │       └── assemble.py        # natural-language summary (Phase 1: weather summary only)
│   │   │
│   │   ├── agents/                    # ← ONE agent Phase 1; grows each phase
│   │   │   ├── __init__.py
│   │   │   └── weather.py             # Weather agent node (calls Weather tool, puts result in state)
│   │   │   # travel_search.py         Phase 2
│   │   │   # rag.py                   Phase 2
│   │   │   # activities_booking.py    Phase 4
│   │   │   # action.py                Phase 4
│   │   │
│   │   ├── tools/                     # ← CONTRACT + Weather Phase 1; grows each phase
│   │   │   ├── __init__.py
│   │   │   ├── base.py                # uniform tool contract (typed in/out, latency budget, failure mode)
│   │   │   └── weather.py             # Open-Meteo + Nominatim geocoding; implements base contract
│   │   │   # duffel.py                Phase 2
│   │   │   # rag_retriever.py         Phase 2
│   │   │   # overpass.py              Phase 4
│   │   │   # ticketmaster.py          Phase 4
│   │   │   # calendar.py              Phase 4
│   │   │   # frankfurter.py           Phase 2
│   │   │   # ors.py                   Phase 4
│   │   │
│   │   ├── guardrails/                # ← PLACEHOLDER Phase 1; built Phase 3
│   │   │   └── .gitkeep
│   │   │
│   │   ├── reliability/               # ← PLACEHOLDER Phase 1; built Phase 3
│   │   │   └── .gitkeep
│   │   │
│   │   ├── memory/                    # ← PLACEHOLDER Phase 1 (profile hardcoded); built Phase 2–3
│   │   │   └── .gitkeep
│   │   │
│   │   ├── rag/                       # ← PLACEHOLDER Phase 1; built Phase 2
│   │   │   └── .gitkeep
│   │   │
│   │   ├── reservation_service/       # ← PLACEHOLDER Phase 1; built Phase 4
│   │   │   └── .gitkeep
│   │   │
│   │   └── state/                     # user profile + session store
│   │       ├── __init__.py
│   │       └── profile.py             # hardcoded demo user profile (Phase 1); DB-backed Phase 2+
│   │
│   └── tests/
│       ├── unit/                      # ← empty Phase 1; populated as code lands
│       │   └── .gitkeep
│       └── eval/                      # ← SEEDED Phase 1 (harness + CI gate); grows every phase
│           ├── dataset.jsonl          # labeled eval cases; starts tiny (routing + weather); grows each phase
│           └── run_eval.py            # runs eval cases; deterministic checks only Phase 1; LLM-judge Phase 5
│
├── frontend/
│   └── src/
│       ├── App.jsx                    # minimal chat layout (Phase 1)
│       ├── components/
│       │   ├── ChatInput.jsx          # message input (Phase 1)
│       │   ├── MessageList.jsx        # message rendering (Phase 1)
│       │   └── ...                    # itinerary cards, budget bar, etc. added per phase
│       ├── hooks/
│       │   └── useStream.js           # SSE consumer hook (Phase 1)
│       └── api/
│           └── chat.js                # API client (Phase 1)
│
├── data/
│   ├── corpus/                        # RAG source documents (added Phase 2)
│   │   └── .gitkeep
│   └── fixtures/                      # demo fixture snapshots for fallback demo (captured Phase 2+)
│       └── .gitkeep
│
└── scripts/
    └── .gitkeep                       # utility scripts (ingest, smoke-test, etc.) added per phase
```

> **Living document note:** this tree is the intended structure, not a contract. As implementation progresses, file names and nesting may shift — particularly inside `orchestrator/nodes/`, `tools/`, and `rag/`. When a phase design doc says "build X," create it where it fits the tree above, and update this diagram at the end of each phase so it stays accurate. The Phase 6 README will carry the final authoritative version.

---

## What Phase 1 is (and isn't)

Phase 1 builds the **thinnest possible vertical slice** through every architectural layer: frontend → API → orchestrator → router → one agent → one tool → LLM → trace. It is deliberately *not* impressive. There is one agent (Weather), no RAG, no guardrails, no memory beyond a hardcoded profile, no booking. The value is structural: by the end, every cross-cutting concern (routing, observability, eval, CI, deployment) has a working home, so every later phase *slots into* a proven frame instead of inventing one.

Two things that are normally treated as "later" work are seeded here on purpose, per the design review: the **eval harness** (empty, but real and CI-gating) and the **uniform tool contract** (so every future agent conforms). Adding these now costs an hour each; retrofitting them later costs days.

---

## Repo structure at the end of Phase 1

This is the layout Phase 1 establishes — the skeleton subset of the full structure in the design doc (Section 13). **Treat it as a living starting point, not a contract.** Directories for later phases (`guardrails/`, `reliability/`, `memory/`, `rag/`, `reservation_service/`) are shown as empty placeholders so files have a home, but the exact shape *will* shift as implementation reveals what actually belongs where. Don't over-invest in getting it "right" now; the only structural commitments that are expensive to change later are the **state schema** (Step 5) and the **tool contract** (Step 4) — those two are worth getting deliberate. Everything else is cheap to move.

```
wanderwise/
├── README.md
├── .env                         # local only — git-ignored (real secrets)
├── .env.example                 # committed template (from Phase 0)
├── .gitignore
├── pyproject.toml               # uv-managed deps
├── docker-compose.yml           # local: backend (vector db + redis added in Phase 2/3)
├── Dockerfile                   # single deployable: backend + built React static
├── docs/
│   ├── design-doc.md
│   ├── decision-log.md          # from Phase 0 — config source of truth
│   ├── phase0.md
│   └── phase1.md
├── .github/workflows/
│   └── ci.yml                   # lint + test + eval-gate + deploy (Step 8/9)
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, SSE chat endpoint, health check (Step 6)
│   │   ├── config.py            # env-driven config; tier→model map, feature flags (Step 1)
│   │   ├── orchestrator/
│   │   │   ├── graph.py         # minimal input→router→weather→assemble→output (Step 5)
│   │   │   ├── state.py         # typed, multi-user-ready state schema (Step 5)
│   │   │   ├── router.py        # deterministic task-type → tier (Step 5)
│   │   │   └── nodes/           # assemble (+ plan/gates/reflection added later)
│   │   ├── agents/
│   │   │   └── weather.py       # first agent node (Step 5)
│   │   ├── tools/
│   │   │   ├── contract.py      # uniform tool contract: typed I/O, latency, failure mode (Step 4)
│   │   │   └── weather.py       # Open-Meteo + Nominatim wrapper (Step 4)
│   │   ├── llm/                 # 2-tier abstraction: Gemini primary | Groq fallback (Step 2)
│   │   ├── observability/       # LangSmith tracing setup (Step 3)
│   │   ├── guardrails/          # (placeholder — Phase 3)
│   │   ├── reliability/         # (placeholder — Phase 3)
│   │   ├── memory/              # (placeholder — basic in Phase 2, advanced in Phase 3)
│   │   ├── rag/                 # (placeholder — Phase 2)
│   │   ├── reservation_service/ # (placeholder — Phase 4)
│   │   └── state/               # user profile + session store (hardcoded profile in Phase 1)
│   └── tests/
│       ├── unit/
│       └── eval/
│           ├── dataset.jsonl    # handful of trivial cases (Step 8)
│           └── run_eval.py      # deterministic checks; CI-gating (Step 8)
├── frontend/                    # Vite + React: minimal chat UI (Step 7)
│   └── src/{components, hooks, api}/
├── data/{corpus, fixtures}/     # empty now; corpus in Phase 2, fixtures from Phase 2 on
└── scripts/
```

**Why placeholders for later phases?** Empty directories (with a `.gitkeep`) signal intent and keep imports stable, but they carry no code. They're a map of where the project is going, not a commitment to that exact shape — rename, split, or merge freely as each phase teaches you what the real boundaries are.

---

## Build order at a glance

The 10 steps are ordered by dependency — each builds on the last. Build inside-out (config → LLM → trace → tool → graph) then outside-in (API → UI), then wrap with eval/CI, then deploy.

| Step | Builds | Depends on |
|---|---|---|
| 1 | Project scaffold + `config.py` (encodes Decision Log) | Phase 0 |
| 2 | LLM abstraction layer (2-tier + Groq fallback) | 1 |
| 3 | Observability wiring (LangSmith from the first call) | 2 |
| 4 | Uniform tool contract + Weather tool | 1, 3 |
| 5 | LangGraph skeleton + state schema + router stub + Weather agent | 2, 3, 4 |
| 6 | FastAPI streaming endpoint (SSE) | 5 |
| 7 | Minimal React chat UI | 6 |
| 8 | Eval harness skeleton + CI gate stub | 5 |
| 9 | Deploy skeleton to chosen platform | 6, 7, 8 |
| 10 | Verify the exit milestone | all |

---

## Step 1 — Project scaffold & config

**Objective:** A running Python package with all configuration driven by the Decision Log and `.env` — no hardcoded model names, thresholds, or providers anywhere else.

**Build:**
- Initialize the backend package under `backend/app/` per the repo structure in the design doc (Section 13). Use `uv` for the environment and dependencies.
- Create `config.py` as the single source of runtime config, loaded from environment (Pydantic `BaseSettings` is the clean choice — it gives typed, validated config and fails loudly on a missing key).
- Encode every Phase 0 decision as config, not as code: model tier → concrete model string mapping, active vector DB, cache backend, guardrail mode, embeddings provider, deployment target, feature flags (e.g., `HOTELS_BOOKING_ENABLED`).
- Add a `TRACE_SAMPLING` flag now (default full in dev) so later high-volume eval runs can throttle LangSmith trace volume against the free-tier cap.

**Key detail:** the config maps *tiers* (`small`, `large`) to *model strings*, not the other way around. The rest of the codebase only ever references `small`/`large`. This is what makes routing and provider-swaps a config change.

**Done when:** the app imports, `config` loads from `.env`, and a missing required var raises a clear startup error.

---

## Step 2 — LLM abstraction layer (2-tier routing + fallback)

**Objective:** One interface the whole system calls; tier and provider live behind it. Demonstrates the cost/latency-awareness that's a top production signal.

**Build (`backend/app/llm/`):**
- A single `complete(tier, messages, **opts)` style interface. Callers pass a tier (`small`/`large`), never a model name.
- Tier → model resolution from config: `small` → Gemini 2.5 Flash-Lite, `large` → Gemini 2.5 Flash.
- Both tiers share one `GEMINI_API_KEY` and one SDK. Use Gemini's OpenAI-compatible endpoint so LangChain/LangGraph integration is uniform and the fallback swap is trivial.
- Wire **Groq as a secondary provider** behind the same interface, switchable by a single config flag. You're not using it yet — but the seam is the interview point ("multi-provider fallback") and it costs nothing to establish now.
- Centralize per-call options (temperature, thinking budget, JSON/structured-output mode) so later phases can request structured outputs without touching provider code.

**Key detail:** keep the interface provider-agnostic from the first line. The moment a caller does `gemini.generate(...)` directly, the abstraction is dead. Everything goes through the one interface.

**Done when:** a small script can call `complete("small", ...)` and `complete("large", ...)` and get responses, and flipping the provider flag routes both to Groq.

---

## Step 3 — Observability wiring (LangSmith from the very first call)

**Objective:** Tracing is instrumented before the first agent exists, so the pattern is set and never bolted on later.

**Build (`backend/app/observability/`):**
- Initialize LangSmith tracing at app startup: `LANGSMITH_TRACING=true`, API key, project name, endpoint — all from config.
- Because the LLM layer uses LangChain/LangGraph primitives, much tracing comes free, but explicitly wrap the LLM call so each trace records: **chosen tier, resolved model, token usage, latency**. These four fields are the seeds of your Phase 5 cost-by-tier dashboard — capture them from call one.
- Respect the `TRACE_SAMPLING` flag from Step 1 so you can throttle later.

**Key detail:** the trace must show *which tier ran*. That single fact is the visible payoff of the routing layer and the thing you point at in the exit milestone. Make sure it lands in the trace metadata, not just the logs.

**Done when:** calling the LLM layer produces a trace in your LangSmith project showing tier, model, tokens, and latency.

---

## Step 4 — Uniform tool contract + the Weather tool

**Objective:** Establish the *shape* every future tool conforms to, then implement the first one. This is the seam the design doc's Section 2.4 describes — set it now so RAG, booking, and the rest inherit it.

**Build (`backend/app/tools/`):**
- Define the **uniform tool contract** every tool wrapper implements: a typed input schema (Pydantic), a typed output schema, a declared latency budget, and an explicit **failure mode** (what it returns when the upstream API is down — never an unhandled exception). This contract is what lets the orchestrator treat tools interchangeably and lets you swap implementations behind a config flag in later phases.
- Implement the **Weather tool** against Open-Meteo, with **Nominatim** for city → coordinates geocoding. Both are no-key (set a descriptive User-Agent for Nominatim and respect its 1 req/sec limit).
- The failure mode for Weather: on upstream failure, return a typed "weather unavailable" result with a flag — *not* an exception. This sets the graceful-degradation pattern the FDE story leans on.

**Key detail:** resist the urge to make Weather special. It's the reference implementation of the contract — its structure is the template Travel Search, RAG, and Booking will copy.

**Done when:** calling the Weather tool with a city returns a typed forecast, and simulating an upstream failure returns the typed degraded result rather than throwing.

---

## Step 5 — LangGraph skeleton + state schema + router stub + Weather agent

**Objective:** The orchestration spine — a minimal plan-act-observe graph with the real state schema, a deterministic router, and one agent node.

**Build (`backend/app/orchestrator/`):**
- **State schema (`state.py`):** define the typed graph state now, designed multi-user even though v1 is solo. Include `user_id` (FK threading from day one), the query, working context, tool results, the chosen tier, and a trace/run id. Getting `user_id` in now means multi-user is purely additive later.
- **Router node (`router.py`):** start **deterministic** — task type (known from which node runs) → tier. Weather classification/lookup → `small`; any synthesis → `large`. No complexity classifier yet (that's a Phase 2+ enhancement and the first thing on the cut line). The router annotates state with the tier; the LLM layer resolves it.
- **Graph (`graph.py`):** a minimal `input → router → weather agent → assemble → output` graph. Real plan-act-observe structure, just one branch. Each node is a traceable unit (this is why LangGraph over a single ReAct prompt — inspectability).
- **Weather agent node (`agents/weather.py`):** calls the Weather tool via the contract, puts the typed result into state. The `large` tier composes a short natural-language summary at the assemble step so the router demonstrably picks *both* tiers in one run.

**Key detail:** keep the graph genuinely minimal but architecturally honest — the node boundaries and state shape you choose here are the ones every later phase extends. Don't shortcut the state schema; it's expensive to change once five agents depend on it.

**Done when:** invoking the graph with "what's the weather in Tokyo next week" runs router → weather → assemble, and the trace shows `small` used for routing and `large` for the summary.

---

## Step 6 — FastAPI streaming endpoint (SSE)

**Objective:** Expose the graph over HTTP with streaming, so the UI can show partial progress (which also sets up the latency-hiding pattern for later heavy phases).

**Build (`backend/app/main.py`):**
- A FastAPI app with one chat endpoint that invokes the graph and streams results via **SSE** (Server-Sent Events). Stream node-level progress and the final assembled answer.
- Structure routes to be auth-ready (the design doc's "auth-ready" note) — a place where a user id will later come from a session, even though it's hardcoded now.
- Health-check endpoint (needed for the deploy platform's liveness check in Step 9).

**Key detail:** wire streaming now even though one weather call is fast. Later phases stack tools + LLM + guardrails + retries; streaming partials to the UI is the mitigation for that latency (Challenge #3). Establishing it on an easy case avoids a painful retrofit.

**Done when:** `curl`-ing the endpoint with a query streams progress events and a final answer, and the run appears in LangSmith.

---

## Step 7 — Minimal React chat UI

**Objective:** A bare chat interface that sends a query and renders the streamed response. Just enough to demo this phase — no polish.

**Build (`frontend/`):**
- Vite + React app: a message input, a message list, and an SSE client that consumes the streaming endpoint and renders tokens/progress as they arrive.
- A tiny, honest "which tier ran" affordance is a nice touch (even just showing it in a debug line) — it makes the routing visible in the demo, not just the trace.
- No itinerary cards, no styling system yet. Each later phase adds *just enough* UI for its capability; Phase 6 is the real polish. This avoids a frontend cliff at the end.

**Key detail:** the UI grows incrementally across phases. Building only what this phase needs is deliberate, not laziness — it keeps Phase 6 as genuine polish.

**Done when:** typing "weather in Tokyo" in the browser streams back a response.

---

## Step 8 — Eval harness skeleton + CI gate stub

**Objective:** The eval safety net exists from commit one — empty, but real and CI-gating. This is the design-review fix: eval is cross-cutting, grown each phase, *not* a Phase 5 lump.

**Build (`backend/tests/eval/`):**
- `dataset.jsonl` with a *handful* of trivial cases (e.g., a weather query with an expected-tier label of `small` for routing, `large` for summary). Tiny is fine — the point is the harness runs.
- `run_eval.py` that loads the dataset, runs each case through the graph, and checks **deterministic** assertions only for now (e.g., routing-tier match, response is non-empty, no exception). LLM-judge evals come later; deterministic checks are cheap and CI-safe.
- Optionally register the dataset in **LangSmith** (its eval/dataset features share the tracing product — using it here means Phase 5's eval depth is an extension, not a new tool).
- **CI gate stub:** a GitHub Actions workflow (`.github/workflows/ci.yml`) that runs lint + tests + `run_eval.py` on every push, and **fails the build** if any eval case fails. It's almost trivial now — that's the point. The gate is in place before there's anything to regress.

**Key detail:** the gate failing the build is the whole value. A trustworthiness story of "CI blocked deploys on quality regression from commit one" is far stronger than eval added at the end. Wire the gate even though it currently guards almost nothing.

**Done when:** a push runs CI, the eval cases pass, and deliberately breaking the router tier makes CI go red.

---

## Step 9 — Deploy the skeleton to the chosen platform

**Objective:** De-risk deployment now, while the app is trivial. This is the single most important Phase 1 outcome — deployment surprises are what kill final weeks.

**Build:**
- Containerize the backend; pass `GEMINI_API_KEY`, LangSmith vars, and all secrets as platform env vars (same config dev and prod — no special-casing).
- Serve the built React app as static files from FastAPI so it's a **single deployable** (simplest free-tier story).
- Push to **Hugging Face Spaces** (your Phase 0 deployment target, Docker SDK). Use the health-check endpoint for liveness.
- Confirm the **CI pipeline deploys on merge to `main`** (lint + test + eval-gate + deploy), closing the loop from Step 8.
- Note the free-tier cold-start/sleep behavior (Challenge #5) — fine for now; a keep-warm ping or recorded fallback is a later concern.

**Key detail:** do this in Phase 1, not Phase 5. Every later phase then deploys through a proven pipeline. Discovering a Docker/secrets/static-serving problem now (trivial app) is a 30-minute fix; discovering it in week 5 (complex app) is a crisis.

**Done when:** the live public URL serves the chat UI and a weather query works against it.

---

## Step 10 — Verify the exit milestone

Run the end-to-end check that defines Phase 1 success:

1. Open the **live public URL** in a browser.
2. Ask for the weather somewhere.
3. Confirm the response streams back.
4. Open **LangSmith** and confirm the run is traced, showing the `small` tier for routing and `large` for the summary, with token usage and latency.
5. Confirm a push to the repo runs **CI with the eval gate**, and that breaking the router turns CI red.

If all five hold, Phase 1 is done and every architectural layer has a proven home.

---

## Phase 1 exit checklist

- [ ] `config.py` drives all model/provider/threshold/feature settings from `.env`; missing keys fail loudly.
- [ ] LLM abstraction layer: `small`/`large` tiers resolve to Gemini models; Groq fallback switchable by flag.
- [ ] LangSmith tracing live from the first LLM call; traces show tier, model, tokens, latency.
- [ ] Uniform tool contract defined; Weather tool implements it with a typed degraded-failure mode.
- [ ] LangGraph skeleton runs `input → router → weather → assemble → output`; state schema is multi-user-ready with `user_id`.
- [ ] Deterministic router picks `small` for routing and `large` for synthesis, visibly in traces.
- [ ] FastAPI SSE endpoint streams; health check present; auth-ready route shape.
- [ ] Minimal React chat UI streams responses.
- [ ] Eval harness runs in CI and gates the build; breaking the router turns CI red.
- [ ] Skeleton deployed to a live public URL; CI deploys on merge to `main`.
- [ ] Exit milestone (Step 10) verified end-to-end.

---

## What is NOT in Phase 1 (deferred to later phases)

To hold the scope line: no RAG, no Travel Search/Duffel, no guardrails, no retry/self-reflection, no memory beyond a single hardcoded profile, no booking or actions, no complexity-based routing (deterministic only), no LLM-judge evals, no dashboards, no frontend polish. If you find yourself building any of these, you've crossed into Phase 2+.

---

## Hand-off to Phase 2

Phase 2 ("Core Data Agents + Router") builds the first genuinely useful capability on this skeleton: the **Travel Search agent** (Duffel flights + Stays search with budget filtering), the **RAG agent** (ingestion pipeline, hybrid vector+BM25 retrieval, cross-encoder rerank, citations, 50 curated countries), the **router going active** across multiple agents, **orchestrator planning with parallelism** (flight search ∥ weather), and **budget reasoning**. Per the design review, Phase 2 also folds in **basic memory** (load the hardcoded profile at session start + carry session state) and **seeds retrieval eval cases** as RAG is built — and starts **capturing demo fixtures** so the growing demo is protected from rate limits and flaky sandboxes from here on. The exit milestone: the Japan query returns a budget-aware itinerary with visa and weather, routing visible in traces.
