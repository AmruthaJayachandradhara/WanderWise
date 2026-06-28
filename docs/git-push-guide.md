# WanderWise — Manual GitHub Push Guide (Phase 2)

> Branch: `phase-2/implementation`. Run each block in order.
> Before starting Push 4, verify locally: `uv run ruff check backend/ scripts/` and `uv run pytest backend/tests/unit/ -v` (expect 23 passing).

**Status:** Pushes 1–3 are **already on GitHub**. Pushes 4–5 are the remaining ones to run.

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

## Notes

- Each push builds on the previous — do not reorder.
- `data/corpus/` contains only a `.gitkeep` placeholder; actual scraped docs are gitignored.
- `data/fixtures/` contains only a `README.md`; live fixture JSON files require API keys (see `data/fixtures/README.md`).
- `QDRANT_URL`, `QDRANT_API_KEY`, and `DUFFEL_API_KEY` must be set (HF Spaces secrets) before the corpus ingest and live-graph eval will run.
- Pending live-key work: `scripts/ingest_corpus.py --all`, demo fixture capture, and the full-graph `run_eval.py` gate.
