# WanderWise — Manual GitHub Push Guide (Phase 2 + Phase 3)

> Phase 2 branch: `phase-2/implementation` (all 5 pushes complete).
> Phase 3 branch: **`main`** (no per-phase branch — push directly). Run each block in order.
> Before starting Phase 3 pushes, verify locally:
> `uv run ruff check backend/` → 0 errors
> `uv run pytest backend/tests/unit/ -v` → 86 passing

---

## Phase 2 status

| Push | Commit | State |
|---|---|---|
| 1 — Session profile + Duffel flights | `cc5b9ad` | ✅ pushed |
| 2 — Hotel search + plan node + parallel graph | `f4a6fa7` | ✅ pushed |
| 3 — Budget node + RAG ingest pipeline | `8c752e9` | ✅ pushed |
| 4 — RAG retrieval + cited synthesis | — | ⬜ to run |
| 5 — Itinerary assembly + eval + docs | — | ⬜ to run |

---

## Push 1 — Session profile loading and live flight search  ✅ ALREADY PUSHED (`cc5b9ad`)

User travel preferences (home airport, passport, budget) are loaded into graph state at the start of every session. Connects the Duffel API for live flight searches with typed degraded-failure handling so the graph never crashes on an API outage.

```bash
# Already committed and pushed — listed for reference only.
git add \
  backend/app/memory/.gitkeep \
  backend/app/memory/__init__.py \
  backend/app/memory/session.py \
  backend/app/state/profile.py \
  backend/app/tools/duffel.py \
  backend/app/agents/travel_search.py \
  backend/app/prompts/library/travel_search/ \
  backend/app/orchestrator/state.py \
  backend/tests/unit/test_travel_search.py \
  backend/tests/unit/test_session.py \
  pyproject.toml \
  uv.lock

git commit -m "feat: add session profile loading and Duffel flight search

Loads user profile into graph state at session start. Adds DuffelFlightTool and travel_search_node with typed degraded-failure mode."

git push origin phase-2/implementation
```

---

## Push 2 — Hotel search and parallel agent dispatch  ✅ ALREADY PUSHED (`f4a6fa7`)

Travel search gains hotel availability via Duffel Stays (httpx — SDK 0.6.2 has no stays support). The orchestrator now fans out to three independent agents concurrently; the router is trimmed to tier-resolution only and each agent extracts its own arguments.

```bash
# Already committed and pushed — listed for reference only.
git add \
  backend/app/orchestrator/nodes/plan.py \
  backend/app/orchestrator/nodes/budget.py \
  backend/app/orchestrator/graph.py \
  backend/app/orchestrator/router.py \
  backend/app/agents/weather.py \
  backend/app/agents/rag.py \
  backend/app/prompts/library/orchestrator/router_intent.yaml \
  backend/app/prompts/library/orchestrator/plan_dispatch.yaml \
  backend/app/prompts/library/weather/ \
  backend/tests/eval/cases/orchestrator/router_intent.jsonl \
  backend/tests/eval/cases/orchestrator/plan_dispatch.jsonl \
  backend/tests/eval/cases/weather/ \
  backend/tests/unit/test_graph.py \
  backend/app/main.py \
  backend/tests/eval/run_eval.py

git commit -m "feat: add hotel search, plan node, and parallel graph topology

Graph rewired to static fan-out (plan → travel_search ∥ weather ∥ rag). Router shrunk to tier-resolution only; each agent extracts its own arguments."

git push origin phase-2/implementation
```

---

## Push 3 — Budget allocation and travel advisory corpus  ✅ ALREADY PUSHED (`8c752e9`)

A budget node normalises prices via Frankfurter FX and selects the best flight + hotel combination within the user's stated budget. The RAG package is introduced with per-collection chunking strategies, ONNX fastembed embeddings, and an idempotent Qdrant ingest pipeline covering 50 countries.

```bash
# Already committed and pushed — listed for reference only.
git add \
  backend/app/orchestrator/nodes/budget.py \
  backend/app/prompts/library/orchestrator/budget_allocation.yaml \
  backend/tests/eval/cases/orchestrator/budget_allocation.jsonl \
  backend/tests/unit/test_budget.py \
  backend/app/rag/__init__.py \
  backend/app/rag/collections.py \
  backend/app/rag/embeddings.py \
  backend/app/rag/ingest.py \
  scripts/ingest_corpus.py \
  data/corpus/.gitkeep

git commit -m "feat: add budget node with FX normalisation and RAG ingest pipeline

budget_node picks best flight+hotel via Frankfurter-normalised prices. RAG package adds three Qdrant collections with fastembed ONNX embeddings and idempotent upsert."

git push origin phase-2/implementation
```

---

## Push 4 — Visa/advisory retrieval and cited synthesis  ⬜ TO RUN

The retrieval pipeline queries Qdrant with a metadata pre-filter (country ISO + passport), rewrites the query on the small tier, and deduplicates results to top-5 chunks. The RAG agent node synthesises a cited answer on the large tier and appends an official-source disclaimer.

```bash
git add \
  backend/app/rag/retriever.py \
  backend/app/agents/rag.py \
  backend/app/prompts/library/rag/ \
  backend/tests/unit/test_retriever.py \
  backend/tests/unit/test_rag.py \
  backend/tests/eval/cases/rag/

git commit -m "feat: add RAG retrieval pipeline and rag_node synthesis

retrieve() applies metadata pre-filter, rewrites query, deduplicates to top-5 chunks. rag_node synthesises cited answer on large tier with official-source disclaimer."

git push origin phase-2/implementation
```

---

## Push 5 — Itinerary assembly and eval coverage  ⬜ TO RUN

The assemble node is upgraded to compose a full itinerary from all parallel-agent outputs — flights, hotels, weather, budget breakdown, and visa answer. The SSE `done` payload is extended to carry all new fields, the eval harness gains checks for new result fields and budget validity, and the travel_search prompt's missing eval case is added.

```bash
git add \
  backend/app/orchestrator/nodes/assemble.py \
  backend/app/prompts/library/orchestrator/assemble_itinerary.yaml \
  backend/app/main.py \
  backend/tests/eval/dataset.jsonl \
  backend/tests/eval/run_eval.py \
  backend/tests/eval/cases/travel_search/ \
  data/fixtures/ \
  docs/implementation-state.md \
  docs/git-push-guide.md

git commit -m "feat: compose full itinerary and extend eval harness

assemble_node v2 builds itinerary from all agent outputs; SSE done payload carries all new fields. Eval gains expected_fields and budget_valid checks."

git push origin phase-2/implementation
```

---

## Verification

After Push 4 and Push 5 complete:

```bash
# Confirm remote is up to date (expect 5 commits on the branch)
git log --oneline -5

# Confirm tests still pass locally
uv run ruff check backend/ scripts/
uv run pytest backend/tests/unit/ -v
```

Expected: 23/23 unit tests pass; ruff clean; all 8 active prompts have paired eval cases.

---

## Notes (Phase 2)

- Each push builds on the previous — do not reorder.
- `data/corpus/` contains only a `.gitkeep` placeholder; actual scraped docs are gitignored.
- `data/fixtures/` contains only a `README.md`; live fixture JSON files require API keys (see `data/fixtures/README.md`).
- `QDRANT_URL`, `QDRANT_API_KEY`, and `DUFFEL_API_KEY` must be set (HF Spaces secrets) before the corpus ingest and live-graph eval will run.
- Pending live-key work: `scripts/ingest_corpus.py --all`, demo fixture capture, and the full-graph `run_eval.py` gate.

---

---

# Phase 3 — Guardrails, Reliability & Advanced Memory

> Branch: **`main`** (no per-phase branch).
> All 10 steps are uncommitted. Run the 5 pushes below in order.
> Pre-flight check before Push 6:
> ```bash
> uv run ruff check backend/
> uv run pytest backend/tests/unit/ -v   # expect 86 passing
> ```

| Push | Steps | State |
|---|---|---|
| 6 — Input guardrails (topicality + injection) | Steps 1–2 | ⬜ to run |
| 7 — PII redaction + infra reliability | Steps 3–4 | ⬜ to run |
| 8 — Output guardrails + self-reflection | Steps 5–6 | ⬜ to run |
| 9 — Rolling summary + long-term memory | Steps 7–8 | ⬜ to run |
| 10 — Caching + eval harness + graph wiring + docs | Steps 9–10 | ⬜ to run |

---

## Push 6 — Input guardrail scaffold + topicality + injection detection  ⬜ TO RUN

Establishes guardrails as first-class graph elements. An `input_guardrail` node sits between `memory` and the router; a conditional edge short-circuits blocked queries to a `refusal` node before any expensive agent runs. Topicality (small-tier LLM) and injection/jailbreak (16 regex heuristics + small-tier LLM fallback) checks share the node. Phase 3 state fields added.

```bash
git add \
  backend/app/guardrails/__init__.py \
  backend/app/guardrails/input.py \
  backend/app/prompts/library/guardrails/input_topicality.yaml \
  backend/app/prompts/library/guardrails/input_injection.yaml \
  backend/tests/eval/cases/guardrails/input_topicality.jsonl \
  backend/tests/eval/cases/guardrails/input_injection.jsonl \
  backend/app/orchestrator/state.py

git commit -m "feat: add input guardrail scaffold with topicality and injection detection 
input_guardrail node sits between memory and router; conditional edge routes
blocked queries to refusal before any agent runs. Topicality + injection/
jailbreak checks share the node. Phase 3 GraphState fields added."

git push origin phase-3/implementation
```

---

## Push 7 — PII redaction + infra retry / fallback / circuit breaker  ⬜ TO RUN

PII is redacted by Presidio (lazy-loaded, degrade-safe) before any LLM call and before state is written — so LangSmith traces see scrubbed text. Infrastructure reliability added to `LLMClient.complete()`: exponential backoff with jitter, tier demotion + Groq provider fallback on exhaustion, and an in-process circuit breaker. New deps: `presidio-analyzer`, `presidio-anonymizer`, `redis`.

```bash
git add \
  backend/app/guardrails/pii.py \
  backend/app/reliability/__init__.py \
  backend/app/reliability/retry.py \
  backend/app/reliability/fallback.py \
  backend/app/reliability/circuit.py \
  backend/app/llm/base.py \
  backend/app/llm/client.py \
  backend/app/config.py \
  backend/tests/unit/test_reliability.py \
  pyproject.toml \
  uv.lock \
  Dockerfile \
  .env.example

git commit -m "feat: add PII redaction (Presidio) and infra retry/fallback/circuit breaker

PII redacted pre-model and pre-trace via Presidio. LLMClient gains exponential
backoff, tier demotion + Groq fallback, and in-process circuit breaker.
Adds presidio-analyzer, presidio-anonymizer, redis deps."

git push origin phase-3/implementation
```

---

## Push 8 — Output guardrails + self-reflection critique-and-retry  ⬜ TO RUN

Output checks run after `assemble`, cheap-first: schema → budget (deterministic) → grounding (large-tier LLM judge). Failed checks trigger a `reflection` node (critique-and-fix in one LLM call); the cycle `output_guardrail → reflection → output_guardrail` is capped at 2 attempts. A hallucination-inducing fixture makes the self-correction demo reproducible. No-hallucinated-booking seam designed (enforced Phase 4).

```bash
git add \
  backend/app/guardrails/output.py \
  backend/app/prompts/library/guardrails/output_grounding.yaml \
  backend/app/prompts/library/guardrails/output_no_hallucinated_booking.yaml \
  backend/tests/eval/cases/guardrails/output_grounding.jsonl \
  backend/app/orchestrator/nodes/reflection.py \
  backend/app/prompts/library/orchestrator/self_reflection_critique.yaml \
  backend/tests/eval/cases/guardrails/self_reflection_critique.jsonl \
  data/fixtures/hallucination_japan_visa.json

git commit -m "feat: add output guardrails and self-reflection critique-and-retry subgraph

Output checks: schema + budget (deterministic) + grounding (LLM judge).
reflection node critiques and fixes failed output; cycle capped at 2 attempts.
Hallucination fixture added for reproducible demo. Booking seam designed."

git push origin phase-3/implementation
```

---

## Push 9 — Rolling session summary + long-term memory  ⬜ TO RUN

Older conversation turns are compressed into a rolling `session_summary` while hard constraints (budget, diet, passports) are pinned and never summarised away. Long-term preferences are persisted to SQLite (`wanderwise_memory.db`, gitignored) via a write policy that only promotes explicit preference statements — not chatter. At session start, durable prefs are loaded and merged into `pinned_constraints`. Assembler injects prior context into the LLM prompt.

```bash
git add \
  backend/app/memory/summary.py \
  backend/app/state/longterm_store.py \
  backend/app/memory/longterm.py \
  backend/app/memory/session.py \
  backend/app/orchestrator/nodes/assemble.py \
  .gitignore

git commit -m "feat: add rolling session summary and SQLite long-term memory

summary.py: rolls older turns into session_summary; pins hard constraints.
longterm_store.py: SQLite preferences + memories tables (degrade-safe).
longterm.py: write policy promotes explicit prefs only; semantic recall via
fastembed. session.py: merges SQLite prefs into pinned_constraints at start."

git push origin phase-3/implementation
```

---

## Push 10 — Caching + eval harness + full graph wiring + docs  ⬜ TO RUN

Semantic cache (cosine similarity via fastembed, Upstash Redis or in-memory fallback) sits between `input_guardrail` and `router`; hits skip all agents but still pass output guardrails. API/tool cache wraps weather (1h TTL) and RAG retrieval (24h TTL) with data-versioned keys. Eval dataset extended with 3 red-team + 3 false-block prevention cases; `run_eval.py` gains block rate (≥95%) and false-block rate (<5%) thresholds. Full Phase 3 graph (14 nodes) wired: `input_guardrail → cache_lookup → router → … → output_guardrail ⟷ reflection → session_update`.

```bash
git add \
  backend/app/memory/cache.py \
  backend/app/agents/weather.py \
  backend/app/agents/rag.py \
  backend/app/orchestrator/graph.py \
  backend/tests/eval/dataset.jsonl \
  backend/tests/eval/run_eval.py \
  backend/tests/unit/test_guardrails.py \
  docs/implementation-state.md \
  docs/git-push-guide.md

git commit -m "feat: add semantic + API cache, red-team eval, and full Phase 3 graph wiring

cache.py: semantic cache (cosine/Redis) + API cache (data-versioned TTL keys).
Weather and RAG agents use API cache. graph.py: 14-node Phase 3 topology with
input_guardrail, cache_lookup, output_guardrail, reflection, session_update.
Eval: 11 cases with block/false-block rate CI thresholds (≥95% / <5%)."

git push origin phase-3/implementation
```

---

## Verification after all Phase 3 pushes

```bash
# Confirm 5 new commits on main
git log --oneline -5

# Confirm clean lint + all 86 tests pass
uv run ruff check backend/
uv run pytest backend/tests/unit/ -v

# Confirm the graph compiles with all 14 nodes
python -c "
from backend.app.orchestrator.graph import graph
nodes = [n for n in graph.nodes if not n.startswith('__')]
print(f'{len(nodes)} nodes: {nodes}')
"
```

Expected: 86/86 unit tests pass; ruff clean; 14 nodes; 13 active prompts auto-discovered.

---

## Notes (Phase 3)

- Push 10 must come last — `graph.py` wires all nodes from pushes 6–9 together.
- `*.db` (SQLite long-term store) is gitignored — never committed.
- `presidio-analyzer` + `redis` are in `pyproject.toml`; run `uv sync` then `uv run python -m spacy download en_core_web_lg` on first setup.
- Upstash Redis URL format: if `.env` contains `UPSTASH_REDIS_URL=https://...upstash.io`, `cache.py` converts it to `rediss://` automatically.
- Red-team eval (`run_eval.py`) requires `GEMINI_API_KEY`; the per-prompt gate (`run_prompt_eval.py`) runs the 5 guardrail prompts in isolation and is cheap.
- Qdrant must be running (resume from Qdrant Cloud dashboard if paused) for RAG/grounding cases to fire.
