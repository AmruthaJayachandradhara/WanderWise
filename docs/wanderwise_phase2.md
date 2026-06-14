# WanderWise — Phase 2: Core Data Agents + Router
### Phase Design Document (implementation roadmap, code-light)

| | |
|---|---|
| **Phase** | 2 of 6 — Core Data Agents + Router |
| **Goal** | Build the first genuinely useful capability on the Phase 1 skeleton: live travel search, grounded reference retrieval, a router active across multiple agents, parallel tool execution, and budget reasoning |
| **Duration** | ~Week 2 |
| **Prereq** | Phase 1 complete — skeleton runs end-to-end on a live URL; router/observability/eval/CI/deploy all wired in skeleton form |
| **Internal sequence** | **Travel Search first, RAG second.** Travel Search reuses the Phase 1 tool/agent pattern and gets a useful result on screen fast; RAG is the heavier subsystem and lands on a proven multi-agent loop |
| **Exit milestone** | The Japan query returns a budget-aware itinerary with live flights, hotel options, weather, and a cited visa/advisory answer — routing visible in traces |

---

## What Phase 2 is (and isn't)

Phase 2 turns the skeleton into something that actually plans a trip. It adds two of the five specialist agents — **Travel Search** (Duffel) and **RAG** (visa/advisory/destination) — brings the **router live across multiple agents**, makes the orchestrator **plan and parallelize**, and adds **budget reasoning**. Three design-review items fold in here because they're cheapest to do alongside the work they support: **basic memory** (load the profile, carry session state), **seeding retrieval eval cases** as RAG is built, and **capturing demo fixtures** so the growing demo is protected from rate limits and flaky sandboxes from here on.

What Phase 2 is *not*: no guardrails, no retries/self-reflection, no advanced memory (rolling summary, semantic cache), no booking or actions, and critically **no query decomposition** — the multi-passport fan-out is Phase 4. Phase 2 RAG does straightforward single-subject retrieval with citations. The Japan demo at this stage answers the visa question for *one* passport cleanly; the two-passport split comes later. Keep that line firm or RAG balloons.

---

## Repo structure at the end of Phase 2

Complete root tree, incremental from Phase 1: **(new)** = created this phase, **(extended)** = changed this phase, **(unchanged)** = carried from Phase 1, **(placeholder)** = empty, populated in a later phase. Every root-level subdirectory is shown. The only commitments expensive to change remain the state schema and tool contract (from Phase 1, extended here, not rebuilt).

```
wanderwise/
├── README.md                        # (unchanged)
├── .env                             # + Duffel/RAG/embeddings vars (extended, git-ignored)
├── .env.example                     # + new var names (extended)
├── .gitignore                       # + qdrant local data dir ignored (extended)
├── pyproject.toml                   # + duffel, qdrant-client, sentence-transformers, rank-bm25 (extended)
├── Dockerfile                       # (unchanged)
├── docker-compose.yml               # + Qdrant vector DB service (local dev) (extended)
├── docs/
│   ├── design-doc.md                # (unchanged)
│   ├── decision-log.md              # (unchanged)
│   ├── phase0.md / phase1.md        # (unchanged)
│   └── phase2.md                    # (new)
├── .github/workflows/
│   └── ci.yml                       # (unchanged — gate now runs new eval cases)
├── backend/
│   ├── app/
│   │   ├── main.py                  # (unchanged)
│   │   ├── config.py                # + Duffel/RAG/embeddings/budget settings (extended)
│   │   ├── orchestrator/
│   │   │   ├── graph.py             # + travel_search, rag nodes; parallel dispatch (extended)
│   │   │   ├── state.py             # + flights/hotels/rag_results/budget fields (extended)
│   │   │   ├── router.py            # active across multiple agents (extended)
│   │   │   └── nodes/
│   │   │       ├── assemble.py      # composes itinerary from merged results (extended)
│   │   │       ├── plan.py          # plan which agents to dispatch + parallelism (new)
│   │   │       └── budget.py        # budget allocation + affordability (new)
│   │   ├── agents/
│   │   │   ├── weather.py           # (unchanged)
│   │   │   ├── travel_search.py     # Duffel flights + Stays; budget filter (new)
│   │   │   └── rag.py               # retrieval + cited synthesis (new)
│   │   ├── tools/
│   │   │   ├── contract.py          # (unchanged)
│   │   │   ├── weather.py           # (unchanged)
│   │   │   └── duffel.py            # flights search + Stays search wrapper (new)
│   │   ├── rag/                     # (new — populated this phase)
│   │   │   ├── ingest.py            # fetch→clean→chunk→embed→upsert
│   │   │   ├── retriever.py         # metadata pre-filter → hybrid → rerank → cite
│   │   │   ├── collections.py       # per-collection chunking strategies
│   │   │   └── embeddings.py        # Gemini Embedding (bge-small fallback)
│   │   ├── memory/                  # (new — basic only)
│   │   │   └── session.py           # profile load at session start; session state carry
│   │   ├── llm/                     # (unchanged)
│   │   ├── observability/           # (unchanged)
│   │   ├── state/                   # profile store (unchanged — hardcoded demo profile)
│   │   ├── guardrails/              # (placeholder — Phase 3)
│   │   ├── reliability/             # (placeholder — Phase 3)
│   │   └── reservation_service/     # (placeholder — Phase 4)
│   └── tests/
│       ├── unit/                    # (unchanged)
│       └── eval/
│           ├── dataset.jsonl        # + retrieval/routing/budget cases (extended)
│           └── run_eval.py          # + Hit@k + tier-match + budget checks (extended)
├── frontend/                        # + minimal itinerary/budget/citation rendering (extended)
│   └── src/{components, hooks, api}/
├── data/
│   ├── corpus/                      # scraped visa/advisory/guide docs (new)
│   └── fixtures/                    # captured demo responses — Duffel/RAG (new)
└── scripts/
    └── ingest_corpus.py             # one-shot corpus build for curated countries (new)
```

---

## Build order at a glance

Travel Search first (steps 1–5), then RAG (steps 6–8), then eval/fixtures and integration (steps 9–10).

| Step | Builds | Depends on |
|---|---|---|
| 1 | Basic memory: profile load + session state | Phase 1 state schema |
| 2 | Travel Search — Duffel flights search | 1, tool contract |
| 3 | Travel Search — Duffel Stays hotels + budget pre-filter | 2 |
| 4 | Orchestrator planning + parallelism + router live | 2, 3 + Phase 1 weather |
| 5 | Budget reasoning (allocation + affordability) | 3, 4, memory |
| 6 | RAG — corpus sourcing + ingestion pipeline | 1 |
| 7 | RAG — retrieval pipeline (hybrid + rerank + citations) | 6 |
| 8 | RAG — agent node into the graph + synthesis routing | 7, 4 |
| 9 | Seed retrieval/routing/budget eval cases + capture demo fixtures | 5, 8 |
| 10 | Assemble itinerary + verify milestone | all |

---

## Step 1 — Basic memory: profile load + session state

**Objective:** The agent knows who it's planning for. Load the hardcoded demo profile into graph state at session start and carry working context across turns. This is *basic* memory only — no summarization or semantic recall (Phase 3).

**Build (`backend/app/memory/session.py`):**
- At session start, load the demo profile (home airport, passport nationality, budget defaults, interest tags, durable prefs like vegetarian) into state, keyed by the `user_id` already threaded through the Phase 1 state schema.
- Carry session working context across turns within the graph state (the in-progress plan, prior tool results, stated constraints like "$3000 budget").
- No write policy / promotion logic yet — that's long-term memory in Phase 3. Here the profile is read-only context.

**Key detail:** everything downstream depends on this — Travel Search needs the home airport, budget reasoning needs the budget default, RAG needs the passport nationality. Doing memory first means those steps just read from state instead of re-prompting the user.

**Done when:** invoking the graph loads the profile into state and a downstream node can read `home_airport`/`passport`/`budget` without asking.

---

## Step 2 — Travel Search agent: Duffel flights search

**Objective:** Real live flight search against Duffel's sandbox, conforming to the Phase 1 tool contract.

**Build (`backend/app/tools/duffel.py` + `agents/travel_search.py`):**
- Duffel client wrapper implementing the **uniform tool contract**: typed input (origin/destination/dates/pax), typed output (offers with price, carrier, times, duration), declared latency budget, and a **typed degraded-failure mode** (return "flights unavailable" flag, never throw).
- Search flow: offer request → retrieve offers. Use the **"Duffel Airways" test airline** for reliability (Challenge #1) — never depend on a single flaky live offer mid-demo.
- The Travel Search agent node calls the tool, normalizes offers into state. Tool *calls* run on the `small` tier (argument extraction); ranking/selection reasoning is `large` (deferred to budget reasoning in Step 5).

**Key detail:** Duffel is the post-Amadeus standard and the real-API integration in your interview story. Keep the wrapper behind the contract so the eventual `BookingProvider` (Phase 4) plugs into the same seam — flight *booking* is Phase 4, search is now.

**Done when:** a flight search for a real route returns normalized offers into state, and a simulated Duffel outage returns the typed degraded result.

---

## Step 3 — Travel Search agent: Duffel Stays hotels + budget pre-filter

**Objective:** Hotel options via Duffel Stays (same SDK/token), plus a first-pass budget filter so the agent doesn't surface unaffordable options.

**Build:**
- Extend the Duffel wrapper with a Stays search (same contract shape). Per your Phase 0 decision, **hotel booking is enabled** — but here in Phase 2 you build **search only**; the booking path for hotels lands in Phase 4 behind `BookingProvider` alongside flight booking (near-zero extra effort on the same Duffel token).
- Add a lightweight **budget pre-filter**: given the budget default from memory and a rough allocation, drop options that are obviously out of range before they reach the expensive synthesis step. This is a cheap deterministic filter, not the full budget reasoning (Step 5).

**Key detail:** pre-filtering cheaply at the tool boundary keeps token cost down and is a small instance of "run cheap deterministic checks before expensive LLM work" — the same principle that governs guardrails later.

**Done when:** a Stays search returns hotel options into state with out-of-range options pre-filtered.

---

## Step 4 — Orchestrator planning + parallelism + router live across agents

**Objective:** The orchestrator stops being a single branch and starts *planning*: deciding which agents to dispatch and running independent ones concurrently. The router goes live across multiple agents.

**Build (`orchestrator/nodes/plan.py`, `graph.py`, `router.py`):**
- A **plan node** (`large` tier) that, from the query + profile, decides which agents are needed (Travel Search, Weather, RAG) and which can run in parallel.
- **Parallel dispatch:** flight search ∥ weather ∥ visa retrieval are independent — run them concurrently via LangGraph's parallel branches, then merge results at an observe/merge node. This is the latency mitigation (Challenge #3) and a real production pattern.
- **Router live:** still deterministic (task-type → tier), now applied across all agents — `small` for classification/rewrite/tool-arg extraction, `large` for synthesis. No complexity classifier yet (first item on the cut line). Router decisions emit to the trace.

**Key detail:** the value of LangGraph over a single ReAct prompt shows up here — parallelism and per-node tracing are graph properties, not prompt hopes. Make sure the trace clearly shows the parallel branches and the tier each node used.

**Done when:** a trip query dispatches flights ∥ weather ∥ (later) RAG in parallel, merges them, and the trace shows the parallel structure plus per-node tier.

---

## Step 5 — Budget reasoning (allocation + affordability)

**Objective:** Turn raw options into a budget-aware plan — allocate the stated budget across flights/lodging/activities and check the assembled itinerary is affordable.

**Build (`orchestrator/nodes/budget.py`):**
- A budget node (`large` tier — multi-constraint reasoning) that allocates the total budget across categories, selects within-budget flight + hotel combinations, and computes a running total.
- Use **Frankfurter** (no-key FX) to normalize currencies so the budget math is correct across destinations.
- Produce a structured budget breakdown that the final itinerary will render.

**Key detail:** this is where the `large` tier earns its cost. It's also a preview of the Phase 3 **budget output guardrail** — the deterministic "total ≤ stated budget" check that will later catch violations and trigger re-planning. Structure the budget output now so that check drops in cleanly.

**Done when:** the Japan query yields a flight + hotel selection with a budget breakdown that respects ~$3000, currency-normalized.

---

## Step 6 — RAG: corpus sourcing + ingestion pipeline

**Objective:** Build the reference-knowledge corpus for the curated countries and the idempotent ingestion pipeline that powers it. (RAG starts here — Travel Search is done.)

**Build (`backend/app/rag/ingest.py`, `collections.py`, `embeddings.py`, `scripts/ingest_corpus.py`):**
- **Sources** (free/public, scraped → embedded, *not* queried live): `travel.state.gov` country pages + advisory levels, `CDC Travelers' Health`; `REST Countries` for structured passport/ISO metadata. Curate the **50 countries** locked in Phase 0 — spanning major economies/superpowers (incl. China, Russia), Middle East destinations, and a deliberate spread of **advisory levels** so the travel-warning path is demoable, not just visa-free tourist countries.
- **Collections & chunking** per the design doc: visa/entry → **whole-document** (fragmenting loses exceptions like "except holders of X"); advisories → sliding-window, daily-refresh-ready; guides → sliding-window with ~15% overlap.
- **Metadata on every chunk:** source URL, country ISO, passport nationality, advisory level, `last_verified` timestamp, and a **`content_hash`**. The hash and timestamp are unused now but are the hooks Phase 4's staleness detection needs — populate them from the first ingest.
- **Embeddings:** Gemini Embedding (same key/SDK); `bge-small-en` noted as offline fallback.
- Pipeline: fetch → clean/normalize → chunk → embed → **idempotent upsert** into Qdrant.

**Key detail:** populate `content_hash` and `last_verified` now even though nothing reads them yet. Retrofitting metadata across an existing corpus is painful; adding two fields at ingest time is free. This is the same "seed the hooks early" discipline as the eval harness.

**Done when:** `scripts/ingest_corpus.py` builds the corpus for all 50 curated countries into Qdrant, with full metadata on every chunk.

---

## Step 7 — RAG: retrieval pipeline (hybrid + rerank + citations)

**Objective:** High-quality retrieval — the pipeline that hits your Hit@5 ≥ 85% / faithfulness ≥ 0.90 targets.

**Build (`backend/app/rag/retriever.py`):**
- Pipeline order: **metadata pre-filter** (country ISO + passport — prevents returning the wrong country's rules, Challenge #8) → **query rewrite** (`small` tier) → **hybrid search** (vector + BM25) → **cross-encoder rerank** (`ms-marco-MiniLM-L-6-v2`, runs locally, no GPU) → top-k assembly **with citations** (source URL + `last_verified`).
- Hybrid + rerank specifically because visa text has exact terms ("visa-free", "90 days", "onward ticket") that pure vector search misses.
- **Qdrant note:** Qdrant supports **native hybrid search** (dense + sparse vectors with built-in fusion), so the vector+BM25 fusion can run inside Qdrant rather than as a hand-rolled merge — a cleaner implementation and part of why Qdrant was chosen over Chroma in Phase 0. The metadata pre-filter is also a native Qdrant payload filter.

**Key detail:** the metadata pre-filter is the cheapest, highest-leverage correctness guard in the whole RAG subsystem — it structurally prevents the most embarrassing failure (Japan rules for a US passport answered with India's rules). Filter *before* semantic search, not after.

**Done when:** a visa query for a curated country returns correctly pre-filtered, reranked chunks with citations.

---

## Step 8 — RAG agent node into the graph + synthesis routing

**Objective:** Wire RAG into the orchestrator as a parallel-dispatchable agent with cited, grounded synthesis.

**Build (`backend/app/agents/rag.py`):**
- The RAG agent node calls the retrieval pipeline, then synthesizes a grounded answer on the **`large` tier**, attaching citations and `last_verified` dates. Query rewrite inside retrieval is `small`; synthesis is `large` — the router demonstrably uses both within one RAG call.
- Add the visa/advisory **disclaimer** ("verify with official sources before travel") to grounded answers now — it's a Responsible-AI item from Section 12 and trivial to include.
- The agent runs in parallel with flights/weather (Step 4's merge node already accommodates it).
- **Single-subject only** — one passport, one destination. Multi-passport/multi-city decomposition is Phase 4. If a query has two passports, Phase 2 handles the primary one and is honest about scope.

**Key detail:** keep "RAG is one tool among many" visible in the architecture — the orchestrator decides to call RAG; it isn't the center of the system. That framing is the whole point of the project vs. "a RAG chatbot."

**Done when:** the Japan query returns a cited visa/advisory answer for one passport, synthesized on `large`, running in parallel with travel search in the trace.

---

## Step 9 — Seed eval cases + capture demo fixtures

**Objective:** Grow the eval harness alongside the capabilities just built, and start protecting the demo. Both are design-review items: eval is cross-cutting, and the demo needs a safety net the moment it's worth showing.

**Build (`backend/tests/eval/`, `data/fixtures/`):**
- **Eval cases** added to `dataset.jsonl`: retrieval **Hit@5** on labeled visa queries, **routing tier-match** for the new agents, and **budget validity** (deterministic: total ≤ budget). Keep them small and honest — enough to make the CI gate meaningful for Phase 2's surface.
- Wire the deterministic checks into `run_eval.py` so the **CI gate** now guards retrieval and budget correctness, not just "non-empty response."
- **Demo fixtures:** capture known-good Duffel responses and RAG results for the Japan narrative into `data/fixtures/`. The demo can run against these when sandboxes are flaky or the Gemini daily quota is tight (Challenge #1, #4). Never let a live rate-limit kill a recruiter walkthrough.

**Key detail:** capturing fixtures now (not in Phase 6) means every subsequent phase's demo is replayable. The fixture set grows with the demo instead of being reconstructed at the end under pressure.

**Done when:** CI runs the new eval cases and fails on a regression; the Japan demo can be replayed entirely from fixtures with no live calls.

---

## Step 10 — Assemble itinerary + verify milestone

**Objective:** Merge everything into a coherent budget-aware itinerary and verify Phase 2 success.

**Build:** an assemble step (`large` tier) that composes flights + hotels + weather + cited visa answer + budget breakdown into a structured day-aware itinerary, streamed to the UI. Add *just enough* UI to render it (a simple itinerary block with a budget line and citations) — not Phase 6 polish.

**Verify the exit milestone:**
1. Run the Japan query (single passport for now).
2. Confirm the itinerary includes live flights, hotel options, the weather window, a cited visa/advisory answer, and a budget breakdown within ~$3000.
3. Open LangSmith: confirm flights ∥ weather ∥ RAG ran in parallel, and that `small`/`large` tiers were chosen correctly per node.
4. Confirm CI's eval gate guards retrieval + budget + routing.
5. Confirm the whole thing replays from fixtures.

---

## Phase 2 exit checklist

- [ ] Basic memory loads the profile into state; downstream nodes read it without re-prompting.
- [ ] Travel Search: Duffel flights search returns normalized offers; typed degraded-failure mode works.
- [ ] Travel Search: Duffel Stays hotels search with budget pre-filter.
- [ ] Orchestrator plans agents and runs flights ∥ weather ∥ RAG in parallel; merge node combines them.
- [ ] Router live across all agents (deterministic), tier choices visible in traces.
- [ ] Budget reasoning allocates and checks affordability, currency-normalized via Frankfurter.
- [ ] RAG corpus built for 50 countries with full metadata incl. `content_hash` + `last_verified`.
- [ ] Retrieval pipeline: metadata pre-filter → rewrite → hybrid → rerank → cited top-k.
- [ ] RAG agent synthesizes cited, disclaimered answers on `large`; single-subject scope held.
- [ ] Eval cases for Hit@5, routing, budget wired into the CI gate.
- [ ] Demo fixtures captured; Japan demo replays with no live calls.
- [ ] Exit milestone verified end-to-end on the live URL.

---

## What is NOT in Phase 2 (deferred)

No guardrails (input or output), no retry/self-reflection, no advanced memory (rolling summary, write policy, semantic cache), no booking or actions, **no query decomposition** (multi-passport/multi-city is Phase 4), no staleness/re-ingestion (the hooks are seeded, the job is Phase 4), no complexity-based routing, no LLM-judge evals, no dashboards, no frontend polish.

---

## Hand-off to Phase 3

Phase 3 ("Guardrails, Reliability & Advanced Memory") hardens the now-useful system so it behaves correctly under adversarial and failure conditions: **input guardrails** (topicality, prompt-injection, PII redaction via Presidio), **output guardrails** (grounding/faithfulness, schema, budget — the budget check drops onto Step 5's structured output; the no-hallucinated-booking gate is *designed* here but tested in Phase 4 where booking lands), **infra retry** (backoff + fallback model + circuit breaker), the **self-reflection / critique-and-retry subgraph**, and **advanced memory** (rolling session summary, long-term write policy, semantic + API caching). Red-team eval cases get written as the guardrails are built. Exit milestone: a red-team input is blocked, an induced hallucination is caught and corrected, a stored preference is recalled across sessions, and a cache hit visibly cuts latency.
