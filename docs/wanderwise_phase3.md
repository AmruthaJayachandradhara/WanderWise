# WanderWise — Phase 3: Guardrails, Reliability & Advanced Memory
### Phase Design Document (implementation roadmap, code-light)

| | |
|---|---|
| **Phase** | 3 of 6 — Guardrails, Reliability & Advanced Memory |
| **Goal** | Harden the now-useful system so it behaves correctly under adversarial and failure conditions, and remembers across sessions |
| **Duration** | ~Week 3 |
| **Prereq** | Phase 2 complete — Travel Search + RAG + active router + parallelism + budget reasoning running on the live URL; basic memory loads the profile |
| **Slip-risk note** | This is the densest phase. It's organized into three internal parts (A → B → C) with an explicit internal cut line (below) so that if the week slips, you cut depth in a pre-decided order rather than panicking |
| **Exit milestone** | A red-team input is blocked, an induced hallucination is caught and corrected by the self-reflection loop, a stored preference (vegetarian) is recalled across sessions, and a cache hit visibly cuts latency |

---

## What Phase 3 is (and isn't)

Phase 3 is where WanderWise stops being a happy-path demo and becomes *production-shaped*. It adds the three subsystems interviewers drill into hardest: **guardrails** ("how do you stop it doing the wrong thing?"), **reliability** ("what happens when it fails?"), and **advanced memory** ("how do you handle context, personalization, and cost?"). None of these change *what* the system does — they change how it behaves at the edges, which is exactly the production signal these roles want.

The phase is sequenced cheap-and-independent first, expensive-and-dependent second, memory last:

- **Part A — Input defense + infra reliability** (steps 1–4): input guardrails and transport-level retries. Cheap, mostly deterministic, independent of RAG output.
- **Part B — Output validation + quality reliability** (steps 5–6): output guardrails and the self-reflection loop. These depend on Phase 2's RAG/budget outputs being stable.
- **Part C — Advanced memory** (steps 7–9): rolling summary, long-term write policy, semantic + API caching.

One dependency is handled deliberately: the **no-hallucinated-booking** output guardrail guards an agent (Booking/Action) that doesn't exist until Phase 4. So it's **designed as a structural seam here and tested in Phase 4** — you can't validate a gate against a nonexistent agent.

What Phase 3 is *not*: no booking, no actions, no query decomposition, no staleness/re-ingestion, no dashboards, no frontend polish.

---

## Internal cut line (if Week 3 slips)

Cut depth in this order — never cut the items in the "keep" row:

| Cut first, in order | Keep no matter what |
|---|---|
| 1. Semantic cache (keep API/tool-result cache) | Input topicality + injection guardrails |
| 2. Long-term semantic recall (keep flat key-value preference store) | PII redaction (before model **and** logs) |
| 3. Rolling summary sophistication (keep simple truncation+pinned-constraints) | Infra retry: backoff + fallback model |
| 4. Circuit breaker (keep backoff + fallback) | Output grounding + schema + budget checks |
| | Self-reflection loop (the single best reliability demo) |

---

## Repo structure at the end of Phase 3

Complete root tree, incremental from Phase 2: **(new)** = created this phase, **(extended)** = changed this phase, **(unchanged)** = carried forward, **(placeholder)** = empty, populated later. Every root-level subdirectory is shown. State schema and tool contract remain stable (extended, not rebuilt).

```
wanderwise/
├── README.md                        # (unchanged)
├── .env                             # + guardrail thresholds, retry caps, cache TTLs, redis url (extended)
├── .env.example                     # + new var names (extended)
├── .gitignore                       # + sqlite db file ignored (extended)
├── pyproject.toml                   # + presidio-analyzer, presidio-anonymizer, redis client (extended)
├── Dockerfile                       # (unchanged)
├── docker-compose.yml               # + Redis (Upstash or local) for cache/session (extended)
├── docs/
│   ├── design-doc.md                # (unchanged)
│   ├── decision-log.md              # (unchanged)
│   ├── phase0–2.md                  # (unchanged)
│   └── phase3.md                    # (new)
├── .github/workflows/
│   └── ci.yml                       # (unchanged — gate now runs red-team/grounding cases)
├── backend/
│   ├── app/
│   │   ├── main.py                  # (unchanged)
│   │   ├── config.py                # + guardrail thresholds, retry caps, cache TTLs (extended)
│   │   ├── orchestrator/
│   │   │   ├── graph.py             # + input/output guardrail edges, reflection wiring (extended)
│   │   │   ├── state.py             # + guardrail verdicts, retry counters, summary, cache flags (extended)
│   │   │   ├── router.py            # (unchanged)
│   │   │   └── nodes/
│   │   │       ├── plan.py          # (unchanged)
│   │   │       ├── budget.py        # (unchanged)
│   │   │       ├── assemble.py      # (unchanged)
│   │   │       └── reflection.py    # self-reflection / critique-and-retry subgraph (new)
│   │   ├── guardrails/              # (new — populated this phase)
│   │   │   ├── input.py             # topicality, prompt-injection/jailbreak
│   │   │   ├── pii.py               # Presidio detect + redact (pre-model AND pre-log)
│   │   │   └── output.py            # grounding, schema, budget, no-hallucinated-booking (seam)
│   │   ├── reliability/             # (new — populated this phase)
│   │   │   ├── retry.py             # exponential backoff + jitter, bounded attempts
│   │   │   ├── fallback.py          # fallback model / provider (Flash→Flash-Lite; Gemini→Groq)
│   │   │   └── circuit.py           # simple circuit breaker
│   │   ├── prompts/                     # (extended)
│   │   │   └── library/
│   │   │       ├── orchestrator/
│   │   │       │   └── self_reflection_critique.yaml    # (new)
│   │   │       └── guardrails/
│   │   │           ├── input_topicality.yaml            # (new)
│   │   │           ├── input_injection.yaml             # (new)
│   │   │           ├── input_pii.yaml                   # (new — if LLM-assisted alongside Presidio)
│   │   │           ├── output_grounding.yaml            # (new)
│   │   │           └── output_no_hallucinated_booking.yaml  # (new — designed here, enforced Phase 4)
│   │   ├── memory/                  # (extended — advanced)
│   │   │   ├── session.py           # (unchanged — Phase 2)
│   │   │   ├── summary.py           # rolling session summary (new)
│   │   │   ├── longterm.py          # write policy + cross-session persistence + semantic recall (new)
│   │   │   └── cache.py             # semantic cache + API/tool-result cache w/ TTLs (new)
│   │   ├── agents/                  # (unchanged — weather, travel_search, rag)
│   │   ├── tools/                   # (unchanged)
│   │   ├── rag/                     # (unchanged)
│   │   ├── llm/                     # (unchanged)
│   │   ├── observability/           # (unchanged)
│   │   ├── state/                   # + long-term store (SQLite) (extended)
│   │   └── reservation_service/     # (placeholder — Phase 4)
│   └── tests/
│       ├── unit/                    # (unchanged)
│       └── eval/
│           ├── dataset.jsonl        # + red-team inputs, faithfulness, false-block cases (extended)
│           ├── run_eval.py          # + guardrail block/false-block, grounding checks (extended)
│           └── cases/                   # (extended)
│               └── guardrails/
│                   ├── input_topicality.jsonl           # (new — red-team cases)
│                   ├── input_injection.jsonl            # (new — red-team cases)
│                   ├── output_grounding.jsonl           # (new — faithfulness cases)
│                   └── self_reflection_critique.jsonl   # (new)
├── frontend/                        # (unchanged — no new UI this phase)
│   └── src/{components, hooks, api}/
├── data/
│   ├── corpus/                      # (unchanged)
│   └── fixtures/                    # + a known hallucination-inducing fixture for the demo (extended)
└── scripts/                         # (unchanged)
```

---

## Build order at a glance

| Step | Part | Builds | Depends on |
|---|---|---|---|
| 1 | A | Guardrail middleware scaffold + input topicality | Phase 2 graph |
| 2 | A | Prompt-injection / jailbreak detection | 1 |
| 3 | A | PII detection & redaction (Presidio) — pre-model & pre-log | 1 |
| 4 | A | Infra retry: backoff + jitter, fallback model/provider, circuit breaker | LLM layer (P1) |
| 5 | B | Output guardrails: schema, budget, grounding + no-hallucinated-booking seam | Phase 2 outputs |
| 6 | B | Self-reflection / critique-and-retry subgraph | 5 |
| 7 | C | Short-term rolling session summary | Phase 2 memory |
| 8 | C | Long-term memory: write policy + persistence + semantic recall | 7, SQLite |
| 9 | C | Caching: semantic cache + API/tool-result cache w/ TTLs | 8, Redis |
| 10 | — | Red-team eval cases + verify milestone | all |

---

# Part A — Input defense + infrastructure reliability

## Step 1 — Guardrail middleware scaffold + input topicality

**Objective:** Establish guardrails as **first-class graph elements**, not prompt hopes, and add the first input check.

**Build (`backend/app/guardrails/input.py`, `orchestrator/graph.py`):**
- Implement guardrails via **LangChain middleware** (hooks around model calls) + **LangGraph conditional edges** — your Phase 0 choice (custom-via-middleware) for maximum transparency and learning.
- Add the input guardrail node as the **first node after input**, before the router (matches the design doc pipeline: input guardrails → router → plan → …).
- **Topicality check** (`small` tier or a lightweight classifier): reject/redirect clearly off-topic or abusive input so a travel agent stays a travel agent. On block, short-circuit to a polite refusal via a conditional edge — never reach the expensive agents.

> **Prompt:** `guardrails/input_topicality.yaml` (small tier). The topicality classifier system prompt lives here — `render("guardrails/input_topicality")` replaces any inline string. Its red-team eval cases (`cases/guardrails/input_topicality.jsonl`) are wired to the per-prompt CI gate (seeded in Phase 1) so a tuning change to this prompt is eval-gated in seconds, not a full-graph run.

**Key detail:** the guardrail is a *graph edge*, so a blocked input deterministically routes to a refusal node. Record the verdict in state and the trace. This wiring is the template steps 2–3 and 5 reuse.

**Done when:** an off-topic input ("write me a poem about cats") is deterministically redirected before any agent runs, with the verdict in the trace.

---

## Step 2 — Prompt-injection / jailbreak detection

**Objective:** Flag inputs trying to override instructions or exfiltrate the system prompt.

**Build (`backend/app/guardrails/input.py`):**
- Add an injection/jailbreak detector to the input guardrail node (heuristics + a `small`-tier classifier for the ambiguous cases). Catch attempts like "ignore previous instructions", "print your system prompt", role-override attacks.

> **Prompt:** `guardrails/input_injection.yaml` (small tier) — the injection/jailbreak classifier prompt, loaded via `render()`. Red-team eval cases cover canonical injection patterns (role-override, exfiltration, jailbreaks); the per-prompt gate verifies ≥95% block rate on this prompt in isolation.

- On detection: block + safe refusal, verdict logged.

**Key detail:** this is a Responsible-AI item (Section 12) and a common interview probe. Keep the detector's reasoning inspectable so you can explain in an interview *why* a given input was flagged — the transparency is the point of building custom rather than a black-box framework.

**Done when:** a prompt-injection attempt is flagged and blocked, with the reason captured.

---

## Step 3 — PII detection & redaction (Presidio)

**Objective:** Detect and redact sensitive personal data **before it reaches the model and before it reaches logs/traces**.

**Build (`backend/app/guardrails/pii.py`):**
- Integrate **Microsoft Presidio** (your Phase 0 choice) to detect + redact PII in input.
- Redact at **two boundaries**: before the model sees it, *and* before anything is written to LangSmith traces or logs. LangSmith captures inputs by default — without pre-log redaction, PII leaks into your traces.

If the PII check includes an LLM-assisted step (for ambiguous cases beyond Presidio’s recognizers): `guardrails/input_pii.yaml` (small tier) holds that classifier prompt. Presidio alone handles the deterministic cases — the YAML only exists if an LLM step is added.

**Key detail:** the pre-log redaction is the easy-to-miss half. Your tracing is always-on from Phase 1, so every run is logged — make sure redaction sits upstream of the trace write, not just the model call.

**Done when:** an input containing a fake email/phone is redacted both in what the model receives and in the resulting trace.

---

## Step 4 — Infrastructure-level retry (backoff, fallback, circuit breaker)

**Objective:** Handle *transport* failures — timeouts, 429s, 5xx — gracefully. This is the first half of the "what happens when it fails?" story (the second half is quality retries in Step 6).

**Build (`backend/app/reliability/`):**
- **Exponential backoff with jitter** (1s → 2s → 4s → 8s), bounded attempts, wrapping LLM and tool calls. Directly handles Gemini's 429s on the 1,500 RPD shared limit (Challenge #4).
- **Fallback model/provider** (`fallback.py`): on persistent failure, degrade Flash → Flash-Lite, or flip the whole LLM layer to **Groq** via the Phase 1 config seam. Then graceful degradation — return partial results with a flag rather than failing the whole run.
- **Circuit breaker** (`circuit.py`): stop hammering a down dependency after N consecutive failures; fail fast to the degraded path.

**Key detail:** keep infra retries (this step) and quality retries (Step 6) as *separate mechanisms* — that distinction is itself an interview-worthy point. Infra retry answers "the API was down"; quality retry answers "the API responded but the answer was wrong."

**Done when:** an injected timeout triggers backoff then fallback; an injected sustained outage trips the circuit breaker and returns a flagged degraded result.

---

# Part B — Output validation + quality reliability

## Step 5 — Output guardrails (schema, budget, grounding, + no-hallucinated-booking seam)

**Objective:** Validate model output before it reaches the user or an action. Order the checks cheap-first.

**Build (`backend/app/guardrails/output.py`):**
- **Deterministic checks first (cheap):**
  - **Schema validation** — itinerary/budget outputs must conform to their Pydantic schema; malformed → retry.
  - **Budget constraint** — itinerary total ≤ stated budget; this is the deterministic check that drops directly onto Phase 2 Step 5's structured budget output. Violation → re-plan.
- **LLM-judge check (expensive, only after deterministic pass):**
  - **Grounding / faithfulness** — RAG-derived claims must be supported by retrieved context; ungrounded claims → retry or a "not found in sources" fallback.
- **No-hallucinated-booking — DESIGN ONLY this phase.** Define the **structural rule**: only the Booking/Action agent may assert a reservation, and only after a confirmation ID exists; the generator model is structurally prevented from claiming a booking. The Booking/Action agent doesn't exist until Phase 4, so wire the seam and the rule now, **test it in Phase 4**.

> **Prompts:** `guardrails/output_grounding.yaml` (large tier — the grounding judge prompt) and `guardrails/output_no_hallucinated_booking.yaml` (the structural rule prompt, designed here). Both load via `render()`. The grounding prompt's eval cases use faithfulness metrics (`metric: schema_valid` for structural checks; `metric: llm_judge` once Phase 5 wires the judge runner). The no-hallucinated-booking YAML is written now but its red-team eval cases are added in Phase 4 when the Booking agent exists.

**Key detail:** run cheap deterministic checks before the expensive LLM-judge (Section 4.4) — schema/budget failures are caught for free and never reach the judge. Track **false-block rate** as a metric from the start (Challenge #10) so you tune thresholds against over-blocking, not just blocking.

**Done when:** a malformed or over-budget output is caught deterministically and re-planned; an ungrounded RAG claim is caught by the grounding judge; the no-hallucinated-booking rule exists as a structural seam (untested until Phase 4).

---

## Step 6 — Self-reflection / critique-and-retry subgraph

**Objective:** The quality-retry mechanism, and the single most impressive reliability pattern to demo.

**Build (`backend/app/orchestrator/nodes/reflection.py`):**
- A small **LangGraph subgraph**: `generate → validate → (pass ? done : critique → regenerate)`. On a failed output guardrail, a critic pass (`large` tier) explains *what's* wrong; the generator regenerates with that feedback.

> **Prompt:** `orchestrator/self_reflection_critique.yaml` (large tier) — the critic pass system prompt, loaded via `render("orchestrator/self_reflection_critique")`. Versioning matters especially here: a critique prompt change can silently affect correction quality. Its eval cases capture the induced-hallucination fixture so a prompt regression is immediately visible in the per-prompt gate.

- **Bound to ~2 retries** to cap cost/latency; still failing → degrade gracefully and surface the limitation honestly.
- **Route the critique to `large` only when a check actually fails** — never run the expensive critic on a passing output.
- Reuse the subgraph for both itinerary synthesis and RAG answers.

**Key detail:** this is your headline demo moment — induce a hallucination (a prepared fixture) and show the system catch and correct it live. Make the reflection events clearly visible in the trace (the failed verdict, the critique, the corrected output) so you can screen-share the self-correction.

**Done when:** an induced hallucination fails grounding, triggers a critique, regenerates correctly, and the whole loop is visible in the trace — capped at 2 attempts.

---

# Part C — Advanced memory

## Step 7 — Short-term rolling session summary

**Objective:** Stay within the context window on long multi-turn sessions without losing early constraints.

**Build (`backend/app/memory/summary.py`):**
- Roll older turns into a **running summary** rather than dropping them, preserving constraints the user stated early ("budget $3000", "vegetarian", "two passports") even after many turns.
- Pin hard constraints so summarization never silently drops them.

**Key detail:** the failure mode to avoid is summarizing away a binding constraint. Pin the constraints explicitly; summarize only the conversational connective tissue around them.

**Done when:** a long session keeps honoring an early-stated budget/constraint after the raw turns would have fallen out of the window.

---

## Step 8 — Long-term memory: write policy + persistence + semantic recall

**Objective:** Durable, cross-session personalization — the "recalls you're vegetarian" demo.

**Build (`backend/app/memory/longterm.py`, `state/` SQLite store):**
- **Write policy** governing promotion from short-term → long-term: explicit preferences ("I'm vegetarian") and repeated behaviors are persisted; ephemeral chatter is not.
- Persist to **SQLite** (your Phase 0 choice), keyed by `user_id` (already threaded since Phase 1).
- At session start, load durable preferences into context (extends Phase 2's profile load).
- **Optional semantic recall** (cut-line item #2): embed preferences/past trips so the agent can retrieve "have I been somewhere like this before?" — a second, smaller RAG surface. Keep a flat key-value store if time is tight.

**Key detail:** the write policy is the interesting part — *not everything* should be remembered. Being able to explain "I persist explicit preferences and repeated behaviors, not chatter" is a stronger answer than "I store the whole conversation."

**Done when:** stating "I'm vegetarian" in one session causes it to be recalled and applied in a *new* session.

---

## Step 9 — Caching: semantic cache + API/tool-result cache

**Objective:** Cut cost and latency on repeated work; protect against the Gemini daily quota.

**Build (`backend/app/memory/cache.py`, Upstash Redis):**
- **Semantic cache** (cut-line item #1): embed the incoming query; if cosine similarity to a prior query exceeds a threshold, return the cached answer and skip the LLM entirely. Backed by Upstash Redis (your Phase 0 choice).
- **API / tool-result cache:** cache slow-changing results with appropriate **TTLs** — visa docs long, weather short, flight prices very short or not at all. **Cache keys include a data-version** so a cache never serves known-stale reference data (Challenge #12); this coordinates with Phase 4's RAG staleness.
- Ensure a **cached answer still passes safety** — a semantic-cache hit shouldn't bypass output guardrails for a freshly-risky context.

**Key detail:** the API/tool cache is the resilience play against the 1,500 RPD Gemini limit and flaky sandboxes — combined with the Phase 2 fixtures, it means a live demo rarely touches a rate limit. The semantic cache is the cost-story play (it shows up on the Phase 5 cache-hit dashboard).

**Done when:** a repeated/near-duplicate query returns from the semantic cache and the trace shows the latency drop; the API cache serves visa docs within TTL but refetches expired weather.

---

## Step 10 — Red-team eval cases + verify milestone

**Objective:** Grow the eval harness with the adversarial surface Phase 3 introduced, and verify the milestone.

**Build (`backend/tests/eval/`):**
- Add a **red-team input set** (off-topic, injection, PII, jailbreak) and measure **block rate (≥95%)** and **false-block rate (<5%)** — wired into the CI gate.

> Wire each guardrail prompt's red-team cases into the **per-prompt CI gate** (from Phase 1) — `run_prompt_eval.py` runs `guardrails/input_topicality`, `input_injection`, and `output_grounding` in isolation before the full-graph gate. This means a guardrail prompt tuning change shows up as a fast, isolated red in CI rather than requiring a full graph run to diagnose.

- Add **faithfulness** cases (the grounding judge) and a **fault-injection** check (injected tool/LLM failures → 100% handled).
- Capture a **hallucination-inducing fixture** so the self-reflection demo is reproducible.

**Verify the exit milestone:**
1. A red-team input (injection or off-topic) is **blocked** before reaching agents.
2. An induced hallucination is **caught and corrected** by the self-reflection loop (visible in the trace).
3. "I'm vegetarian" stored in one session is **recalled in a new session**.
4. A repeated query **hits the cache** and the trace shows a measurable latency drop.
5. CI's eval gate now guards guardrail block/false-block rates and grounding.

---

## Phase 3 exit checklist

- [ ] Input guardrails (topicality, injection, PII) wired as graph edges; blocks short-circuit to refusal.
- [ ] PII redacted before the model **and** before traces/logs.
- [ ] Infra retry: backoff+jitter, fallback model/provider, circuit breaker; degraded results flagged.
- [ ] Output guardrails: schema + budget (deterministic, cheap-first) + grounding (LLM-judge).
- [ ] No-hallucinated-booking structural seam defined (test deferred to Phase 4).
- [ ] Self-reflection subgraph catches an induced hallucination and corrects it, ≤2 retries, trace-visible.
- [ ] Short-term rolling summary preserves pinned early constraints.
- [ ] Long-term write policy persists explicit prefs across sessions; vegetarian recalled in a new session.
- [ ] Semantic cache + API/tool cache with TTLs and data-versioned keys; cache hit cuts latency.
- [ ] Red-team + faithfulness + fault-injection eval cases in the CI gate; false-block rate tracked.
- [ ] Exit milestone verified end-to-end.
- [ ] All guardrail and self-reflection prompts load from versioned YAML via `render()` — no inline strings in Phase 3 nodes.
- [ ] Per-prompt red-team eval cases wired to the CI gate; tuning a guardrail prompt triggers only that prompt's gate.

---

## What is NOT in Phase 3 (deferred)

No booking or actions (Phase 4), no **testing** of the no-hallucinated-booking gate (designed here, tested in Phase 4), no query decomposition (Phase 4), no staleness detection / automated re-ingestion (the cache data-version hook coordinates with it, but the job is Phase 4), no LLM-judge eval *depth* or dashboards (Phase 5), no frontend polish (Phase 6). No per-prompt LLM-judge eval (Phase 5 — the `metric: llm_judge` field is designed in the guardrail YAMLs but the judge runner wires it in Phase 5). No prompt dashboard breakdown (Phase 5).

---

## Hand-off to Phase 4

Phase 4 ("Booking, Actions & Advanced RAG") makes the demo genuinely impressive: the **Activities/Booking subagent** (Overpass restaurants/attractions + Ticketmaster/Eventbrite events), the **self-hosted mock reservation microservice** (idempotency keys, confirmation IDs, availability conflicts, cancellation/rollback), **real Duffel flight booking** wired through the `BookingProvider` abstraction — at which point the **no-hallucinated-booking gate from Step 5 is finally enforced and tested**. It also adds the **Action agent** (calendar `.ics` low-risk + drafted booking/email high-risk with a confirmation gate), and the two advanced-RAG pieces deferred from Phase 2: **query decomposition** (the multi-passport/multi-city fan-out that powers the full demo narrative) and **staleness detection + automated re-ingestion** (using the `content_hash`/`last_verified` hooks seeded in Phase 2, run via a GitHub Actions scheduled workflow). Exit milestone: the full multi-passport Japan query end-to-end — real flight booking, real mock restaurant reservation with a confirmation ID, calendar hold created, itinerary email drafted for confirmation, and a staleness job re-ingesting a changed document. Phase 4 also activates the `output_no_hallucinated_booking.yaml` prompt's red-team eval cases — the gate that was structurally seamed in Phase 3 becomes fully enforced and eval-gated once the Booking agent exists.
