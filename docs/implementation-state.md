# WanderWise — Implementation State

> Single source of truth for the current state of the project. Updated at the end of each phase. Describes what has been built, decisions locked, and where things live.

---

## Project Overview

| | |
|---|---|
| **Repo** | `AmruthaJayachandradhara/WanderWise` (GitHub) |
| **Live URL** | https://gwuwanderwise-wanderwise.hf.space |
| **HF Space** | `GwuWanderwise/wanderwise` (Docker SDK, port 7860) |
| **Language** | Python 3.12 (uv), Node 20 (Vite + React) |
| **Current phase** | Phase 2 complete |

---

## Locked Decisions

| # | Area | Decision |
|---|---|---|
| 1 | Booking stack | Duffel (flights + hotels) + self-built mock reservation service behind a `BookingProvider` contract |
| 2 | Hotels | Booking enabled (same Duffel token) |
| 3 | Vector DB | Qdrant — native hybrid (vector + BM25) search |
| 4 | Cache / session | Redis — Upstash free tier |
| 5 | Guardrails | Custom via LangChain middleware |
| 6 | LLM provider | Gemini primary (`gemini-2.5-flash-lite` = small, `gemini-2.5-flash` = large, Gemini Embedding); Groq as fallback |
| 7 | Re-ingestion | GitHub Actions scheduled workflow |
| 8 | Deploy target | Hugging Face Spaces (Docker SDK, single container) |
| 9 | Demo countries | 50-country curated list (see `docs/wanderwise_phase0.md` §1.4) |
| 10 | Embeddings | Gemini Embedding; `bge-small-en` as offline fallback |

---

## Phase 0 — Foundation Prerequisites

**Status: Complete**

All 10 decisions locked. All API keys provisioned and smoke-tested (Gemini, Duffel, Ticketmaster, Eventbrite, ORS, LangSmith, Upstash Redis, Qdrant Cloud, Groq, Hugging Face). Repo created, toolchain pinned, `.env.example` committed, `docs/decision-log.md` written.

**Produced:** decisions, credentials, repo skeleton. No application code.

---

## Phase 1 — Foundation & Skeleton

**Status: Complete. Live on HF Spaces.**  
**Branch:** `phase-1/skeleton`

A full vertical slice through every architectural layer: one weather query flows frontend → FastAPI SSE → LangGraph → router (`small` tier) → WeatherTool → assemble (`large` tier) → LangSmith trace.

---

### Config & Logging

**`backend/app/config.py`**  
All runtime config in one place via `pydantic-settings`. Loads from `.env`. Key fields: `MODEL_TIERS`, `GEMINI_BASE_URL`, `GROQ_BASE_URL`, `GROQ_MODEL_TIERS`, `USE_GROQ_FALLBACK`, `LLM_TEMPERATURE`, `LLM_TIMEOUT_S`, `TRACE_SAMPLING`, `APP_PORT=7860`, `FRONTEND_DIST_DIR`, `DEMO_USER_ID`. Global singleton: `settings`.

**`backend/app/logging_config.py`**  
`setup_logging(level)` — configures root logger once at startup. Format: `timestamp [LEVEL] name: message` to stdout.

---

### LLM Abstraction

| File | Description |
|---|---|
| `backend/app/llm/base.py` | `LLMResponse` Pydantic model (`text, tier, model, input_tokens, output_tokens, latency_ms`); `LLMProvider` Protocol |
| `backend/app/llm/providers/openai_compat.py` | Wraps `langchain_openai.ChatOpenAI` parametrized by `base_url`, `api_key`, `tier_model_map`. Only file that directly uses an LLM SDK |
| `backend/app/llm/providers/gemini.py` | Factory returning a Gemini-configured `OpenAICompatProvider` |
| `backend/app/llm/providers/groq.py` | Factory returning a Groq-configured `OpenAICompatProvider`; raises on missing key |
| `backend/app/llm/client.py` | `LLMClient.complete(tier, messages, config, **opts) → LLMResponse`. Resolves tier → model, merges trace metadata, reads `usage_metadata` for tokens, measures latency. Module-level singleton: `llm` |

Provider switch: `USE_GROQ_FALLBACK=true` in `.env`.

---

### Observability

**`backend/app/observability/tracing.py`**

- `init_tracing()` — sets LangSmith env vars from `settings`; called at app startup. `TRACE_SAMPLING <= 0` disables tracing.
- `trace_metadata(tier, model) → dict` — returns `RunnableConfig`-shaped dict with `metadata: {tier, model, phase}` and `tags`. Merged into every `llm.complete()` call so each LangSmith trace records which tier and model ran.

---

### Tool Contract

**`backend/app/tools/base.py`**

- `ToolResult[OutputT]` (Pydantic Generic): `success, degraded, data, error, latency_ms`
- `BaseTool[InputT, OutputT]` (ABC): `latency_budget_s=10.0`, abstract `_run()`, concrete `run()` — catches all exceptions, returns degraded result, never raises

**`backend/app/tools/weather.py`** — `WeatherTool(BaseTool)`:

- `WeatherInput(location: str, days: int = 7)` → `WeatherForecast(location, latitude, longitude, daily: list[DayForecast])`
- Geocodes via Nominatim (1 req/sec; descriptive `User-Agent`)
- Forecast via Open-Meteo — both no-key, `httpx` with timeout
- WMO code map included for human-readable weather descriptions

---

### LangGraph Orchestrator

**`backend/app/orchestrator/state.py`** — `GraphState (TypedDict, total=False)`:

| Field | Set by | Description |
|---|---|---|
| `user_id` | request | Multi-user FK |
| `query` | request | Raw user input |
| `task_type` | router | `"weather"` in Phase 1 |
| `tier` | router | Tier chosen for lookup step |
| `location` | router | Destination extracted from query |
| `weather` | weather node | Serialised `WeatherForecast` dict or `None` |
| `degraded` | weather node | `True` if tool returned degraded result |
| `summary` | assemble node | Final NL answer |
| `run_id` | graph entry | LangSmith trace id |
| `router_tier` | router | Tier used by router (eval + traces) |
| `assemble_tier` | assemble | Tier used by assemble (eval + traces) |

**`backend/app/orchestrator/router.py`** — `router_node`  
`llm.complete("small", ...)` with JSON-extraction prompt. Extracts `task_type` + `location`. Sets `router_tier="small"`. Fallback on JSON parse failure: `task_type="weather", location="unknown"`.

**`backend/app/agents/weather.py`** — `weather_node`  
Calls `WeatherTool.run(WeatherInput(location=...))`. No LLM call. Writes result + `degraded` flag to state.

**`backend/app/orchestrator/nodes/assemble.py`** — `assemble_node`  
`llm.complete("large", ...)` synthesises NL summary from weather state. Sets `assemble_tier="large"`.

**`backend/app/orchestrator/graph.py`** — compiled graph, module-level singleton:
```
START → router → weather → assemble → END
```

**`backend/app/state/profile.py`** — hardcoded demo `UserProfile`. `get_profile(user_id)` always returns the demo profile (no DB yet).

---

### API

**`backend/app/main.py`**

- Lifespan: `setup_logging()` + `init_tracing()` at startup
- `GET /health` → `{"status": "ok"}`
- `POST /api/chat` body: `{query: str, user_id?: str}` → SSE stream via `sse-starlette`
  - `event: progress` per node (`router`, `weather`, `assemble`)
  - `event: done` payload: `{summary, router_tier, assemble_tier, degraded}`
  - Single `graph.astream(stream_mode="updates")` pass; state accumulated in a dict
  - `user_id` falls back to `settings.DEMO_USER_ID`
- `frontend/dist` mounted as static files at `/` when the dist dir exists

---

### Frontend

**`frontend/`** — Vite + React, no styling framework

| File | Description |
|---|---|
| `src/api/chat.js` | `streamChat(query, userId)` async generator; manual SSE line parsing |
| `src/hooks/useStream.js` | Manages `messages`, `status`, `sendQuery`; handles `progress`/`done` events |
| `src/components/ChatInput.jsx` | Query input form |
| `src/components/MessageList.jsx` | Message list; shows tier debug info from `msg.meta` |
| `src/App.jsx` | Chat layout |
| `vite.config.js` | Dev proxy: `/api` → `http://localhost:8000` |

---

### Eval & CI

**`backend/tests/eval/dataset.jsonl`** — 3 cases: Tokyo, Paris, London weather queries  
Expected per case: `router_tier="small"`, `assemble_tier="large"`, `summary` non-empty.

**`backend/tests/eval/run_eval.py`** — runs each case through the compiled graph; deterministic tier + non-empty summary checks; `sys.exit(1)` on failure; `LANGSMITH_TRACING=false` in CI.

**`.github/workflows/ci.yml`**  
- Triggers on every push/PR
- `test` job: `ruff check` → `pytest` → eval gate (`GEMINI_API_KEY` secret, `TRACE_SAMPLING=0`)
- `deploy` job (push to `main` only): git push to HF Spaces remote using `HF_TOKEN` secret

---

### Infra

| File | Description |
|---|---|
| `Dockerfile` | Stage 1 (Node 20): `npm ci + vite build`. Stage 2 (Python 3.12-slim): `uv sync --no-dev --frozen`, copy `backend/` + `frontend/dist`, `uvicorn` on port 7860 |
| `.dockerignore` | Excludes `.git`, `.venv`, `.env`, `node_modules`, `frontend/node_modules`, `frontend/dist`, `__pycache__`, `*.egg-info` |
| `docker-compose.yml` | Single `backend` service, port 7860, reads `.env` |
| `pyproject.toml` | hatchling build backend; `packages = ["backend"]` |
| `README.md` | HF Spaces front matter: `sdk: docker`, `app_port: 7860` |

---

### Phase 1 Exit State

- `/health` returns `{"status": "ok"}` on live HF Space ✅
- Weather query streams progress events + final summary ✅
- LangSmith trace shows `small` routing + `large` summary with tokens + latency ✅
- Eval: 3/3 cases pass ✅
- CI gate: green; exits non-zero on eval failure ✅

---

### Not built in Phase 1

- Complexity classifier in router (always routes to weather)
- Real auth (`user_id` threaded but always demo)
- Qdrant, Redis, Duffel, Ticketmaster, Eventbrite, ORS integration
- Guardrails, budget reasoning, memory
- UI polish, itinerary cards

---

## Phase 2 — Travel Search + RAG

**Status: Complete.**

A full travel planning slice: one Japan query flows through memory → plan → parallel (flights ∥ weather ∥ RAG) → budget → assemble, returning a budget-aware itinerary with live flights, hotel options, weather, and a cited visa/advisory answer. All routing visible in LangSmith traces.

---

### Memory

**`backend/app/memory/session.py`** — `load_profile_node`
Loads the hardcoded demo `UserProfile` into `GraphState` at session start, keyed by `user_id`. Profile is read-only here; all downstream nodes consume these fields directly from state without re-prompting.

**State fields added:** `home_airport`, `passport_country`, `budget_default`, `home_currency`, `interests`, `preferences`.

---

### Tools

**`backend/app/tools/duffel.py`** — extended with flights + stays:

- `DuffelFlightTool`: `DuffelFlightInput(origin, destination, departure_date, return_date, passengers)` → `DuffelFlightOffers(offers: list[FlightOffer])`. Uses `duffel-api` SDK; degrades on any exception.
- `DuffelStaysTool`: `DuffelStaysInput(destination, check_in, check_out, guests)` → `DuffelStaysOffers(offers: list[HotelOffer])`. SDK 0.6.2 has no stays support — uses raw `httpx POST https://api.duffel.com/stays/search` with Nominatim geocoding. `latency_budget_s = 15.0`.

---

### Agents

**`backend/app/agents/travel_search.py`** — `travel_search_node`
Extracts IATA codes + dates via `small` tier (`render("travel_search/argument_extraction")`). Calls `DuffelFlightTool` then `DuffelStaysTool`. Deterministic budget pre-filter on hotels (`total_price ≤ budget_default × 0.45`). Returns namespaced degraded flags (`flights_degraded`, `hotels_degraded`).

**`backend/app/agents/weather.py`** — extended
Extracts its own location via `small` tier (`render("weather/argument_extraction")`) before calling `WeatherTool`. Writes `weather_extraction_tier`.

**`backend/app/agents/rag.py`** — `rag_node`
Resolves `country_iso` from location via `_LOCATION_TO_ISO` (50-country dict) + substring + small-LLM fallback. Calls `retrieve()`, synthesises a cited answer on `large` tier (`render("rag/synthesis")`), appends the official-sources disclaimer. Returns `rag_results`, `visa_answer`, `rag_degraded`, `rag_tier`.

---

### Orchestrator

**`backend/app/orchestrator/nodes/plan.py`** — `plan_node` (`large`): reads query + profile, returns `agents_needed` (trace metadata only — topology is static); falls back to all three agents.

**`backend/app/orchestrator/nodes/budget.py`** — `budget_node` (`large`): normalises prices to `home_currency` via **Frankfurter** (`api.frankfurter.app`, no key), picks best flight + hotel via `render("orchestrator/budget_allocation")`, builds `BudgetBreakdown`. Returns `budget_breakdown`, `selected_flight`, `selected_hotel`, `budget_tier`.

**`backend/app/orchestrator/nodes/assemble.py`** — extended to v2 (`large`): composes the full itinerary from selected flight, hotel, budget breakdown, weather, and visa/advisory answer; degrades gracefully per section.

**`backend/app/orchestrator/router.py`** — shrunk to tier-resolution only; returns `{"task_type": "travel_planning", "router_tier": "small"}`.

**`backend/app/orchestrator/graph.py`** — Phase 2 topology:
```
START → memory → router → plan → [travel_search ∥ weather ∥ rag] → budget → assemble → END
```
Fan-out from `plan`; fan-in into `budget` (waits for all three). Parallel writes are safe via per-agent namespaced state keys.

**State fields added:** `flights`/`flights_degraded`, `hotels`/`hotels_degraded`, `weather_extraction_tier`, `agents_needed`/`plan_tier`, `budget_breakdown`/`selected_flight`/`selected_hotel`/`budget_tier`, `rag_results`/`visa_answer`/`rag_tier`/`rag_degraded`.

---

### RAG Pipeline

**`backend/app/rag/collections.py`** — `CollectionConfig` + three collections: `visa_entry` (whole-document), `advisories` (sliding-window 200/10%), `destination_guides` (sliding-window 300/15%).

**`backend/app/rag/embeddings.py`** — fastembed `BAAI/bge-small-en-v1.5` (ONNX, 384-dim, no torch). `embed_texts` + `embed_query`.

**`backend/app/rag/ingest.py`** — `ingest_country(iso, passport)`: fetches `travel.state.gov` + `restcountries.com`, strips HTML (stdlib), chunks per config, embeds, idempotent upsert to Qdrant (dedup by `content_hash`). Metadata on every chunk: `source_url`, `country_iso`, `passport_nationality`, `advisory_level`, `last_verified`, `content_hash`. In-memory Qdrant fallback when `QDRANT_URL` unset.

**`backend/app/rag/retriever.py`** — `retrieve(query, country_iso, passport_nationality) → list[RetrievedChunk]`: query rewrite (`small`) → `embed_query` → metadata pre-filter (`country_iso` + `passport_nationality`) + dense search across all three collections → dedup by `content_hash` → top-5. Public `retrieve()` never raises (returns `[]` on error).

**`scripts/ingest_corpus.py`** — CLI for the 50-country corpus build: `--country JP` or `--all`, optional `--passport`.

---

### API

**`backend/app/main.py`** — SSE `event: done` payload extended with: `flights`, `flights_degraded`, `hotels`, `hotels_degraded`, `visa_answer`, `rag_degraded`, `budget_breakdown`, `selected_flight`, `selected_hotel`.

---

### Prompt Registry — Phase 2 Additions

| File | Tier | Description |
|---|---|---|
| `orchestrator/router_intent.yaml` | small | v2 — returns `task_type` only (tier-resolution) |
| `orchestrator/plan_dispatch.yaml` | large | Decides `agents_needed` |
| `orchestrator/budget_allocation.yaml` | large | Picks best flight + hotel combo |
| `orchestrator/assemble_itinerary.yaml` | large | v2 — multi-source itinerary |
| `weather/argument_extraction.yaml` | small | Location extraction (agent-symmetry) |
| `travel_search/argument_extraction.yaml` | small | IATA/date/pax extraction |
| `rag/query_rewrite.yaml` | small | Query expansion before retrieval |
| `rag/synthesis.yaml` | large | Cited answer from retrieved chunks |

All eight active prompts have paired per-prompt eval cases under `tests/eval/cases/`.

---

### Eval & Tests

23 offline unit tests (monkeypatched LLM + Qdrant): `test_{graph, budget, retriever, rag, session, travel_search}.py`. `dataset.jsonl` extended with `full-trip-tokyo` (expected_fields) and `budget-validity-japan` (budget validity); `run_eval.py` extended with `expected_fields` + `expected_budget_valid` checks.

---

### Phase 2 Exit State

- Topology `memory → router → plan → [travel_search ∥ weather ∥ rag] → budget → assemble` ✅
- Agent symmetry: every agent extracts its own args; router is tier-resolution only ✅
- Budget node normalises via Frankfurter, selects best offers ✅
- RAG: fastembed ONNX, Qdrant metadata pre-filter, dedup, top-5; cited synthesis + disclaimer ✅
- Assemble v2 composes full itinerary; SSE payload carries all new fields ✅
- 23/23 unit tests pass; ruff clean; all 8 prompts have eval cases ✅

**Pending (requires live API keys):** `scripts/ingest_corpus.py --all` to populate Qdrant; demo fixture capture (`data/fixtures/README.md`); full-graph eval run (`run_eval.py`).

---

## Environment Variables

| Variable | Required now | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | Yes | LLM calls + embeddings |
| `LANGSMITH_API_KEY` | No | Tracing |
| `LANGSMITH_PROJECT` | No | Trace project name (default: `wanderwise`) |
| `TRACE_SAMPLING` | No | `0` = tracing off (used in CI) |
| `USE_GROQ_FALLBACK` | No | `true` routes all LLM calls to Groq |
| `GROQ_API_KEY` | No | Required if `USE_GROQ_FALLBACK=true` |
| `QDRANT_URL` | Phase 2 | Vector DB |
| `QDRANT_API_KEY` | Phase 2 | Vector DB auth |
| `UPSTASH_REDIS_URL` | Phase 2 | Session + cache |
| `UPSTASH_REDIS_TOKEN` | Phase 2 | Redis auth |
| `DUFFEL_API_KEY` | Phase 2 | Flight + hotel search |
| `HF_TOKEN` | CI/Deploy | HF Spaces push |
