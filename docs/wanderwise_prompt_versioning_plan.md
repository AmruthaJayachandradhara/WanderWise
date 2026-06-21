# WanderWise — Prompt Versioning, Evaluation & Agent Symmetry
### Cross-cutting implementation plan (code-light, phase-sequenced)

| | |
|---|---|
| **Scope** | Two coupled changes: (1) externalize all prompts into versioned YAML with per-prompt evaluation; (2) make Weather a fully independent agent symmetric with the other four |
| **Type** | Cross-cutting concern — seeded once, grown every phase, like the eval harness and observability |
| **Source of truth alignment** | Mirrors `agents/` vs `orchestrator/nodes/` module split; extends (never rebuilds) the Phase 1 state schema and tool contract |
| **Defining principle** | A prompt is a versioned, independently-testable artifact — not a string literal buried in node logic. Every prompt has an ID, a version, a changelog, and its own eval cases. |

---

## Why this is cross-cutting, not a single-phase task

Three of the project's own "threads that run through every phase" already establish the pattern this plan follows: the eval harness is *seeded empty in Phase 1 and grown every phase*; observability is *always-on from day one*; the state schema and tool contract are *set once and only extended*. Prompt versioning belongs in exactly that category. Seeding the registry when there are two prompts (Phase 1) costs an hour; retrofitting it across a dozen scattered f-strings after Phase 4 costs days and risks silent behavior drift during the migration.

The payoff is the same trustworthiness story the CI eval-gate already tells, sharpened: *"every prompt is versioned, every prompt change is individually eval-gated in CI, and every trace records which prompt version produced it."* That is a concrete, verifiable production-AI-engineering signal.

---

## The two changes and why they are coupled

**Change A — Prompt versioning + per-prompt eval.** All system/agent/guardrail prompts move out of Python and into versioned `.yaml` files under `backend/app/prompts/library/`, loaded through a small registry, each carrying its own eval dataset and threshold, wired into a per-prompt eval runner that gates CI.

**Change B — Weather as an independent agent.** Today Weather is special-cased: its argument extraction lives inside `router_node` because Weather was the only agent in Phase 1. Once a second agent exists, that extraction must move into Weather's own node so every specialist agent is symmetric (own prompt, own extraction, own tool call). This is coupled to Change A because the act of giving Weather its own extraction prompt is the first real migration into the prompt library — the two changes share the same first move.

---

## Target structure

### Prompt library (mirrors the code's module split exactly)

```
backend/app/prompts/                       # (new — Phase 1)
├── __init__.py
├── schema.py                              # Pydantic model: shape + validation of a prompt file
├── registry.py                            # load / validate / cache / render
└── library/
    ├── orchestrator/                      # non-tool-bearing nodes (maps to orchestrator/nodes/)
    │   ├── router_intent.yaml             # tier resolution + (P1 only) weather extraction → moves out P2
    │   ├── plan_dispatch.yaml             # which agents + parallelism (P2)
    │   ├── decompose_query.yaml           # multi-passport/multi-city fan-out (P4)
    │   ├── self_reflection_critique.yaml  # critique-and-retry (P3)
    │   └── assemble_itinerary.yaml        # final synthesis across all agent outputs
    ├── weather/                           # (P2 — extraction moves here from router)
    │   └── argument_extraction.yaml
    ├── travel_search/                     # (P2)
    │   ├── argument_extraction.yaml
    │   └── offer_ranking.yaml
    ├── rag/                               # (P2)
    │   ├── query_rewrite.yaml
    │   └── synthesis.yaml
    ├── activities_booking/                # (P4)
    │   ├── search_extraction.yaml
    │   └── selection_reasoning.yaml
    ├── action/                            # (P4)
    │   └── email_drafting.yaml
    └── guardrails/                        # (P3)
        ├── input_topicality.yaml
        ├── input_injection.yaml
        ├── input_pii.yaml                 # only if LLM-assisted alongside Presidio
        ├── output_grounding.yaml
        └── output_no_hallucinated_booking.yaml
```

**Rule:** `orchestrator/` is the one folder that maps to `orchestrator/nodes/*.py` rather than `agents/*.py`, because plan, assemble, decompose, router, and self-reflection are non-tool-bearing orchestration logic, not specialist agents. Every other folder maps 1:1 to an `agents/*.py` file.

### Eval cases (mirror the prompt library 1:1)

```
backend/tests/eval/
├── dataset.jsonl                          # existing — full-graph end-to-end cases
├── run_eval.py                            # existing — full-graph eval (CI-gating)
├── run_prompt_eval.py                     # (new — P1) per-prompt isolated eval runner
└── cases/                                 # (new — P1) mirrors prompts/library/ exactly
    ├── orchestrator/
    │   ├── router_intent.jsonl
    │   ├── plan_dispatch.jsonl
    │   └── ...
    ├── weather/
    │   └── argument_extraction.jsonl
    └── ...
```

The three things — call site, prompt file, eval cases — always share the same path-style key:
```
render("rag/synthesis", ...)        →  prompts/library/rag/synthesis.yaml
                                    →  tests/eval/cases/rag/synthesis.jsonl
```

---

## The prompt file schema

Each `.yaml` is one prompt, one purpose, versioned independently.

```yaml
prompt_id: weather/argument_extraction   # path-style; matches file location & eval-case folder
version: 1
tier: small                              # which model tier this prompt is written for
status: active                           # active | experimental | deprecated
description: >
  Extracts location and date window from a raw travel query for the Weather agent's tool call.

template: |
  Extract the destination and travel date window from the user's query.
  Query: {query}
  Respond with JSON only: {{"location": "...", "days": <int>}}

input_variables:
  - query

output_schema:                           # optional; for structured-output prompts
  type: object
  properties:
    location: {type: string}
    days: {type: integer}

eval:
  dataset: tests/eval/cases/weather/argument_extraction.jsonl
  metric: exact_match                    # exact_match | schema_valid | llm_judge
  threshold: 0.90

changelog:
  - version: 1
    date: 2026-XX-XX
    change: "Extracted from router_node into the Weather agent (agent-symmetry refactor)."
```

What this buys over an inline f-string: a pinnable version number, a reviewable changelog isolated from code diffs, a declared eval dataset + threshold per prompt, and a `status` flag enabling experimental/A-B versions without touching the active path.

---

## The registry (the only new runtime component)

```python
# backend/app/prompts/registry.py
from functools import lru_cache
from pathlib import Path
import yaml
from .schema import PromptDefinition

LIBRARY_DIR = Path(__file__).parent / "library"

@lru_cache(maxsize=None)
def get_prompt(prompt_id: str) -> PromptDefinition:
    """prompt_id is path-style, e.g. 'rag/synthesis'. Cached so hot loops don't re-read disk."""
    path = LIBRARY_DIR / f"{prompt_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No prompt registered at {prompt_id}")
    return PromptDefinition(**yaml.safe_load(path.read_text()))

def render(prompt_id: str, **kwargs) -> str:
    """Load + format in one call. Call-site ergonomics stay near-identical to an f-string."""
    p = get_prompt(prompt_id)
    missing = set(p.input_variables) - set(kwargs)
    if missing:
        raise ValueError(f"{prompt_id} missing variables: {missing}")
    return p.template.format(**kwargs)
```

**Call-site change is one line.** Before:
```python
prompt = f"""Extract the destination...\nQuery: {query}\n..."""
```
After:
```python
from backend.app.prompts.registry import render
prompt = render("weather/argument_extraction", query=query)
```

Nothing about the graph, state schema, or tool contract changes — this is purely relocating where the string lives.

---

## Why YAML-in-git, not a hosted prompt registry

YAML stays in git, diffs cleanly, needs no new infra or paid tool, and loads with one dependency. LangSmith does offer a hosted prompt registry, but pulling prompts over the network on every LLM call adds a runtime dependency and weakens the "everything is in git, reviewable, CI-gated" story the rest of the project commits to. The correct LangSmith integration is narrower and additive: **log `prompt_id` and `version` as trace metadata** next to the `tier`/`model` fields `trace_metadata()` already sets, so every trace shows which prompt version produced that run — the dashboard view for free, no dependency on hosted storage.

---

## Per-prompt evaluation — the actual payoff

`run_eval.py` (existing) runs whole-graph cases. `run_prompt_eval.py` (new) runs one prompt in isolation against its own `eval.dataset`, checks the declared `metric` against the declared `threshold`, and exits non-zero on failure. For prompts whose inputs don't depend on upstream graph state (extraction, classification, guardrails), this needs no graph traversal — it's seconds, not a full run.

Workflow for changing any prompt:
1. Edit `template`, increment `version`, append a `changelog` entry.
2. `python run_prompt_eval.py <prompt_id>` → pass/fail in seconds.
3. Commit. Rollback is `git revert` on a single file — node logic is never at risk.

Side-by-side comparison (interview-worthy): a small script loads two versions and runs both against the same cases, surfacing the delta — concrete evidence of prompt-level regression testing.

**CI wiring:** add `run_prompt_eval.py` (all prompts) as a step *before* the existing full-graph eval gate in `ci.yml`. It's cheaper and it isolates which layer broke when something regresses — a prompt-level red is unambiguous, a graph-level red needs investigation.

---

## Phase-by-phase rollout

The system is seeded in Phase 1 and grown every phase, exactly mirroring how the eval harness itself is handled. Tags follow the project convention: **(new) / (extended) / (unchanged)**.

### Phase 1 — Seed the registry + harness (do alongside Step 8, the eval-harness step)
- **(new)** `prompts/schema.py`, `prompts/registry.py`.
- **(new)** `prompts/library/orchestrator/router_intent.yaml` and `assemble_itinerary.yaml` — migrate the two existing Phase 1 prompts (router JSON-extraction, assemble summary) verbatim into YAML as the first real entries. Behavior identical; only location changes.
- **(new)** `run_prompt_eval.py` + `cases/orchestrator/router_intent.jsonl`, `cases/orchestrator/assemble_itinerary.jsonl` — tiny, deterministic (e.g. router extracts correct `location`; assemble returns non-empty). Mirrors "tiny but real" eval-harness seeding.
- **(extended)** `ci.yml` — add the per-prompt eval step before the full-graph gate.
- **(extended)** `observability/tracing.py` — `trace_metadata()` also records `prompt_id` + `version`.
- **Done when:** router and assemble prompts load from YAML, a push runs per-prompt eval in CI, and changing a prompt's expected extraction makes that prompt's eval (and only it) go red.

### Phase 2 — Agent symmetry + the prompt-count jump (this is where the value becomes visible)
- **(new)** `prompts/library/weather/argument_extraction.yaml` — **pull Weather's location/date extraction OUT of `router_node` and into `weather_node`.** This is the Weather-independence change. After this, `router_intent.yaml` shrinks to tier-resolution only and stops doing any agent's extraction.
- **(new)** `weather_node` gains its own small-tier extraction call (it had no LLM call before); it now reads raw `state["query"]` and extracts what its tool needs, identical in shape to every other specialist agent.
- **(new)** `travel_search/argument_extraction.yaml`, `travel_search/offer_ranking.yaml`, `rag/query_rewrite.yaml`, `rag/synthesis.yaml`, `orchestrator/plan_dispatch.yaml`.
- **(new)** matching `cases/` files; wire each prompt's eval into CI as it lands (retrieval/routing/budget cases already arrive this phase).
- **(extended)** every new Phase 2 node calls `render(...)` instead of inline strings from the start — no inline-string debt is created.
- **Done when:** Weather extracts its own arguments via its own versioned prompt; the router no longer does any agent's extraction; all five Phase 2 prompts are versioned and individually eval-gated.

### Phase 3 — Guardrail prompts (tight versioning matters most here)
- **(new)** `guardrails/input_topicality.yaml`, `input_injection.yaml`, `input_pii.yaml` (if LLM-assisted), `output_grounding.yaml`, `output_no_hallucinated_booking.yaml` (designed here, enforced P4), `orchestrator/self_reflection_critique.yaml`.
- Guardrail eval uses red-team datasets; metric is block-rate / false-block-rate, threshold per the design doc (≥95% block, <5% false-block). Per-prompt eval is the right granularity — you can tune an injection prompt and re-run only its red-team set in seconds.
- **Done when:** every guardrail and the self-reflection critic load from YAML; red-team eval cases gate each guardrail prompt independently.

### Phase 4 — Booking/action/decomposition prompts
- **(new)** `activities_booking/search_extraction.yaml`, `selection_reasoning.yaml`, `action/email_drafting.yaml`, `orchestrator/decompose_query.yaml`.
- Decomposition gets its own eval cases (split correctness + per-traveler merge quality) wired to its prompt.
- **Done when:** the full five-agent roster plus decomposition all run from versioned prompts; no inline prompt strings remain anywhere in the codebase.

### Phase 5 — Eval depth lands naturally on the existing seam
- The full ~40-case set splits into deterministic (CI-gating) vs LLM-judge (sampled) — the per-prompt runner already distinguishes `metric: exact_match`/`schema_valid` from `metric: llm_judge`, so this is configuration, not new machinery.
- **(new)** dashboard panel: eval score over time **broken down by `prompt_id` and `version`** (the trace metadata seeded in P1 makes this a query, not new instrumentation).
- **Done when:** dashboards show per-prompt eval trends; a deliberate prompt regression turns the gate red and is attributable to a specific prompt+version.

### Phase 6 — Documentation only
- README/architecture note: "prompt library mirrors module structure; every prompt is versioned and independently eval-gated; traces record prompt version." One verifiable line in the interview narrative.
- **Done when:** the prompt-versioning story is documented and pointable-to in the repo.

---

## Cut-line discipline

If a week slips, this system degrades gracefully in this order — never cut the whole thing, trim depth:
1. **Cut first:** per-prompt *LLM-judge* eval (keep deterministic per-prompt eval — exact_match/schema_valid).
2. **Then:** the side-by-side version-comparison script (nice-to-have, not load-bearing).
3. **Then:** the Phase 5 per-prompt dashboard breakdown (keep aggregate eval trend).

**Never cut:** prompts living in versioned YAML, the registry, `prompt_id`+`version` in trace metadata, and Weather owning its own extraction prompt. These are the load-bearing pieces — the first three are the entire point of the change, and the fourth is what makes the agent roster honest.

---

## Threads this plan adds to the project

- **A prompt is a versioned artifact.** It has an ID, a version, a changelog, an owner (its folder = its agent), and its own eval cases. It is never a string literal in node logic.
- **The prompt library mirrors the code's module split.** `orchestrator/` = non-tool-bearing nodes; every other folder = one `agents/*.py`. Structure is self-documenting and verifiable.
- **Every agent is symmetric.** Each specialist agent owns its extraction prompt, its tool call, and its reasoning step. Weather is not special — Phase 1's router-owned extraction was a first-agent artifact, corrected in Phase 2.
- **Prompt changes are CI-gated and attributable.** A prompt edit runs its own eval in CI before the full-graph gate; every trace records which prompt version ran, so a regression points at a specific prompt and version.
