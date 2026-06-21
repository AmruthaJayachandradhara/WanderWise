# WanderWise — AI Travel Planning Agent
### Engineering Design Document & Project Plan (v5)

| | |
|---|---|
| **Author** | Amrutha |
| **Status** | Draft — for build |
| **Doc type** | Design doc / project plan (no implementation code) |
| **Project goal** | Learning vehicle for building a production-shaped agentic AI system; portfolio artifact for AI Engineer / Forward Deployed Engineer applications |
| **Target timeline** | 5-week MVP (compressible to 4 with cuts) |
| **LLM strategy** | Hosted-only (no local GPU); **Google Gemini API** (AI Studio free tier); **2-tier routing** — Gemini 2.5 Flash-Lite (small/fast) + Gemini 2.5 Flash (large/reasoning) |
| **Deployment** | Cloud-deployed live demo — **Hugging Face Spaces** (free tier) |
| **User model** | Solo demo user for v1; schema designed for multi-user |
| **Changes in v5** | **All open decisions resolved + phased build plan produced.** Observability/eval switched **Langfuse → LangSmith** (free Developer tier); **vector DB locked to Qdrant** for MVP (was Chroma; native hybrid search); **deployment locked to Hugging Face Spaces**; **demo corpus expanded to 50 countries** (travel-warning coverage, superpowers incl. China/Russia, Middle East); **hotel booking enabled** via Duffel Stays (was search-only); cache (Redis/Upstash), guardrails (custom middleware), re-ingestion (GitHub Actions), embeddings (Gemini) confirmed-locked; all Section 16 decisions RESOLVED. A detailed **phased build plan (Phase 0–6) + build index** now accompanies this doc as the authoritative sequencing (see Section 07). |
| **Changes in v4** | **LLM strategy updated** — Ollama/local hosting dropped (no GPU); Google Gemini API (AI Studio free tier) adopted for both tiers; 2-tier routing now Gemini 2.5 Flash-Lite → Gemini 2.5 Flash; Groq removed as primary (kept as optional fallback in LLM abstraction layer); data privacy note added |
| **Changes in v3** | **Final API stack locked** — Duffel (flights real-book + hotels search) replaces Amadeus (which is decommissioned July 17 2026); booking abstraction (`BookingProvider`) with Duffel + self-hosted mock reservation service; Sabre evaluated and kept as architecture-only extension point; all 12 data/booking components confirmed free REST APIs (Section 8.4) |
| **Changes in v2** | Observability + eval promoted to MVP; added LLM routing, guardrail middleware, retry/self-reflection, restaurant/events booking subagent, advanced RAG (decomposition + staleness + auto re-ingestion), and a memory-management layer |

---

## A note on scope realism (read this first)

v1 of this doc was a 3-week MVP that proved one vertical slice of each capability. You've since chosen to pull the most interview-probed capabilities into the MVP itself and extend to **5 weeks**. That's a defensible call — the additions (routing, guardrails, retries, memory, observability, advanced RAG, a booking subagent) are exactly what AI Engineer / FDE interviews drill into.

But honesty matters in a design review: **5 weeks solo for all of this is aggressive.** This doc therefore (a) sequences the work so something runs end-to-end early, (b) keeps observability and eval *always-on* rather than a final-week task, and (c) preserves a **cut-line discipline** (Section 07.3) so that if a week slips, you cut depth in a pre-decided order instead of panicking. Where a real-world constraint forces a design choice (e.g., no free restaurant-booking API), it's called out with **[reality check]** and pros/cons.

---

## 01 · Problem Statement & Scope

### 1.1 The problem

Planning a trip is a multi-source reasoning task. A traveler must search live flight/hotel inventory, reconcile options against a budget, check entry requirements (visa, passport validity), account for weather, find and reserve activities/restaurants, and commit actions (book, save to calendar, email an itinerary). The information needed lives in **three fundamentally different places**:

1. **Live, volatile data** — flight prices, hotel/restaurant availability, weather, FX. Fetched at query time; cannot be pre-indexed.
2. **Slow-changing reference knowledge** — visa rules, advisories, destination guides. The RAG layer.
3. **User state & memory** — budget, preferences, prior trips, in-session decisions. Persisted and recalled.

A naive chatbot treats everything as one LLM call and fails. A production agent **orchestrates** the right tool per sub-problem, **routes** to the right model per task, **guards** its inputs and outputs, **retries** intelligently on failure, **remembers** across turns, and **takes action** safely.

### 1.2 What this system is

WanderWise is an **agentic travel planning system**: an orchestrator (LangGraph) that classifies and routes a query, plans a sequence of tool calls, executes them (some in parallel), reasons over results under guardrails, retries on failure or low-confidence output, produces a budget-aware itinerary, and takes low-risk actions automatically while drafting high-risk ones for confirmation — all instrumented end-to-end and continuously evaluated.

**Defining principle:** RAG is *one tool among many*. The agent decides when to retrieve, when to call a live API, when to compute, when to remember, and when to act. This orchestration framing — not "a RAG chatbot" — is what these roles want to see.

### 1.3 Primary user journey (the demo narrative)

> *"Plan a 6-day trip to Japan in late March for two of us (one US passport, one Indian passport). Budget around $3,000. We love food and history, want to avoid crowds, and book a couple of restaurants."*

The agent should: decompose this (note the **two passports** → two visa lookups); fetch live flights (Duffel) + hotels (Duffel Stays) within budget; retrieve per-passport visa rules and the current advisory (RAG with **query decomposition**); check the weather window and flag cherry-blossom crowding; search restaurants (Overpass) and events (Ticketmaster/Eventbrite), and **make a real restaurant reservation** via the mock reservation service for chosen ones; assemble a day-by-day itinerary with a budget breakdown (Frankfurter FX); auto-create a calendar hold (low-risk `.ics`) and draft the booking summary + itinerary email (high-risk → draft + confirm). Throughout: the **router** picks a cheap model for classification/rewriting and a strong model for synthesis; **guardrails** validate inputs/outputs; **memory** recalls that this user is vegetarian from a past trip; everything is **traced**.

### 1.4 In scope (MVP — 5 weeks)

- Orchestrator + **5 specialist agents**: Travel Search (flights+hotels), Weather, RAG, Activities/Booking (restaurants/events), Action.
- **2-tier LLM routing** (small/fast + large/reasoning) driven by query/task classification.
- **Guardrails** via LangChain/LangGraph middleware: input validation (topical, prompt-injection, PII), output validation (grounding, no-hallucinated-booking, schema, budget).
- **Retry logic**: infra-level (backoff + fallback model) and quality-level (self-reflection / critique-and-retry).
- **Advanced RAG**: hybrid retrieval + rerank, **query decomposition**, **staleness detection + automated re-ingestion**.
- **Memory management**: short-term (session), long-term (profile/preferences/trip history), and caching (semantic + API/tool result).
- **Real sandbox reservations** for activities/restaurants (see 1.6 reality check), one real low-risk action (calendar), one drafted high-risk action (booking summary/email) with a confirmation gate.
- **Observability + eval as first-class, always-on** from Week 1.
- React frontend + FastAPI backend, deployed to free tier.

### 1.5 Out of scope (MVP) — deferred to backlog

- Multi-user auth & persistence (schema designed now, not built).
- Financial integrations (Plaid, points optimization, insurance arbitration) — the "FinTravel" extension.
- Real payments / real money bookings.
- Voice / multimodal input.
- 3-tier routing, multi-region deployment, A/B model experiments.

### 1.6 Reality check — what books for real vs. what's mocked

**[reality check]** Booking availability differs sharply by category. The API research (June 2026) settled this:

- **Flights — real sandbox booking.** **Duffel** provides a full booking flow in its free test mode (search → price → create order → cancel) with a reliable test airline ("Duffel Airways"). No IATA accreditation, no company, no commercial agreement — 1-minute signup. This is the post-Amadeus standard. *(Amadeus Self-Service was the obvious choice historically but is decommissioned July 17, 2026 — not viable.)*
- **Hotels — search + book via Duffel Stays.** Same SDK/token as flights. Per the resolved decision, **hotel booking is enabled** in the MVP — a second real booking type at near-zero extra effort, routed through the same `BookingProvider` contract as flights (search in the core loop, booking wired alongside flight booking — see Section 8.4 and Section 16 #2).
- **Restaurants — no free booking API exists.** OpenTable/Resy/Yelp Reservations are all partner-gated. Booking is satisfied by a **self-hosted mock reservation microservice** you build, implementing real booking semantics: idempotency keys, confirmation IDs, availability conflicts, cancellation/rollback.
- **Events — search-only.** Ticketmaster Discovery and Eventbrite are free for search but ticketing requires partnership/real money. Surface a deep link; no in-app booking.

*The interview line:* *"Flights book for real against Duffel's sandbox. Restaurant reservation APIs are all partner-gated, so I built a reservation microservice implementing the same booking semantics — idempotency, confirmation, cancellation — behind the same tool contract as Duffel. Swapping in OpenTable later is a config change, not a rewrite."* This shows you can integrate a real modern API *and* make a principled call where one doesn't exist. The booking abstraction (one `BookingProvider` interface, multiple backends) is the architecture that makes it coherent — see Section 8.4.

### 1.7 Success criteria

| Dimension | MVP target |
|---|---|
| End-to-end demo | The multi-passport Japan query → full itinerary + a real Duffel flight booking + a mock restaurant reservation in < 90s |
| Retrieval quality | Hit@5 ≥ 85%; faithfulness ≥ 0.90 (LLM-judge) |
| Query decomposition | Multi-part queries correctly split & merged ≥ 90% on test set |
| Routing | Correct tier chosen ≥ 90%; measurable cost/latency savings vs. always-large |
| Guardrails | Block rate ≥ 95% on a red-team input set; < 5% false-block on valid inputs |
| Reliability | 100% of injected tool/LLM failures handled (retry or graceful degrade) |
| Action taking | 1 real action (calendar .ics) + 1 real flight booking (Duffel) + 1 mock restaurant reservation + 1 drafted action, all working |
| Memory | Long-term preference recalled across sessions; cache hit measurably cuts latency |
| Observability | Every run traced; dashboards for latency, cost-by-tier, cache-hit, retry rate, eval scores |
| Deployment | Live public URL |

---

## 02 · Architecture

### 2.1 High-level shape

```
                          ┌──────────────────────────────┐
                          │   React Frontend (chat + UI)  │
                          └───────────────┬──────────────┘
                                          │  REST / SSE (streaming)
                          ┌───────────────▼──────────────┐
                          │      FastAPI Application       │
                          │   (routes, SSE, auth-ready)    │
                          └───────────────┬──────────────┘
                                          │
        ┌─────────────────────────────────▼──────────────────────────────────┐
        │                     Orchestrator (LangGraph)                         │
        │                                                                      │
        │   [Input Guardrails] → [LLM Router] → plan → act → observe →         │
        │                                         ↑                 │          │
        │                                   [Self-reflection /       │          │
        │                                    quality retry loop]     ▼          │
        │                                              [Output Guardrails] →    │
        │                                                    assemble itinerary │
        └──┬──────────┬──────────┬───────────┬────────────┬────────────────────┘
           │          │          │           │            │
    ┌──────▼───┐ ┌────▼───┐ ┌────▼───┐ ┌─────▼──────┐ ┌───▼────────┐
    │ Travel   │ │Weather │ │  RAG   │ │ Activities/│ │  Action     │
    │ Search   │ │ Agent  │ │ Agent  │ │  Booking   │ │  Agent      │
    └────┬─────┘ └───┬────┘ └───┬────┘ └─────┬──────┘ └────┬────────┘
         │           │          │            │             │
    ┌────▼────┐ ┌────▼───┐ ┌────▼────┐  ┌────▼─────┐  ┌────▼────────┐
    │Flight/  │ │Weather │ │Vector DB│  │Places +  │  │Calendar /   │
    │Hotel API│ │  API   │ │+ BM25   │  │Reservation│  │Email / Draft│
    └─────────┘ └────────┘ └────┬────┘  │ (sandbox/ │  └─────────────┘
                                │       │  mock)    │
                       ┌────────▼──────┐└───────────┘
                       │ Ingestion +   │
                       │ Staleness/    │
                       │ Re-ingestion  │
                       └───────────────┘

  ┌──────────────────────────────────────────────────────────────────────┐
  │ Cross-cutting layers:                                                  │
  │  • LLM abstraction (2-tier routing: Flash-Lite | Flash; Google Gemini API)    │
  │  • Memory: short-term (session) · long-term (profile) · cache (semantic+API) │
  │  • Observability/Eval (LangSmith) — always on                  │
  │  • Config & secrets                                                     │
  └──────────────────────────────────────────────────────────────────────┘
```

### 2.2 Orchestration model

A **plan-act-observe-reflect** state graph (LangGraph), chosen over a single ReAct prompt for inspectability (each node is traceable), controllable parallelism (independent tools run concurrently), and deterministic gates (guardrails, budget, action-confirmation are graph edges, not LLM whims).

**Pipeline order within the graph:** input guardrails → router (pick model tier) → plan → dispatch to agents (parallel where independent) → observe/merge → output guardrails + self-reflection (retry if failed) → assemble → action gates.

### 2.3 Agent responsibilities

| Agent | Responsibility | Tools | Model tier |
|---|---|---|---|
| **Orchestrator** | Decompose, route, sequence/parallelize, enforce gates, assemble | — | large |
| **Travel Search** | Flight + hotel search w/ budget/preference filters; flight booking | Duffel (flights + Stays) | small (calls) / large (rank) |
| **Weather** | Forecast across window; flag adverse conditions | Open-Meteo (+ Nominatim geocoding) | small |
| **RAG** | Visa/advisory/destination retrieval w/ decomposition + citations | Vector DB + BM25 + reranker | small (rewrite) / large (synthesis) |
| **Activities/Booking** | Search restaurants/events; **make real sandbox reservations** | Places/events search + reservation service | small (search) / large (selection reasoning) |
| **Action** | Real low-risk action (calendar); drafted high-risk (booking/email) w/ confirmation gate | Calendar, email/draft | small |

### 2.4 Uniform tool contract

Every tool agent exposes a typed input schema, typed output schema, declared latency budget, and a defined failure mode (what it returns when upstream is down). This uniformity lets the orchestrator treat tools interchangeably and lets you swap the mock reservation service for a real provider with a config change.

---

## 03 · LLM Routing Layer

*Interview value: demonstrates cost- and latency-awareness — a top signal for production AI engineering.*

### 3.1 Concept

Not every step needs a 70B model. A **router** classifies each unit of work and dispatches it to the cheapest model that can do it well. Two tiers:

| Tier | Model | Used for |
|---|---|---|
| **Small / fast** | Gemini 2.5 Flash-Lite (Google AI Studio free tier) | Intent classification, query routing, query rewriting, guardrail classification, simple lookups, tool-argument extraction |
| **Large / reasoning** | Gemini 2.5 Flash (Google AI Studio free tier) | Itinerary synthesis, multi-constraint budget optimization, self-reflection critique, final answer generation |

**Why Gemini Flash-Lite + Flash for both tiers:**
- Both models share the same API key, the same SDK (`google-generativeai`), and the same Google AI Studio project — no switching providers, no extra auth.
- Flash-Lite at ~$0.10/$0.40 per 1M tokens and Flash at ~$0.30/$2.50 per 1M tokens represent a genuine cost difference that makes the routing savings measurable and real — ideal for the cost-by-tier dashboard story.
- Free tier: 1,500 requests/day and 1,000,000 tokens/minute on Flash models — 167× more token throughput than Groq's free tier, sufficient for development and demo without hitting limits.
- Both models support function calling, JSON mode, and structured outputs natively — required for tool-argument extraction and itinerary schema enforcement.

### 3.2 Routing signal

The router decides the tier from **task type** (known from which node is executing) plus a lightweight **complexity classification** of the query (single-step lookup vs. multi-constraint synthesis). Task-type routing is deterministic and reliable; complexity classification uses the small model itself or a heuristic. Start deterministic (task-type → tier), add complexity classification if time allows.

### 3.3 Tradeoffs

| | Pros | Cons |
|---|---|---|
| Routing | Lower cost & latency; realistic prod pattern; great interview story | Added complexity; a routing error can send a hard task to a weak model |
| Mitigation | — | Conservative default (when unsure → large); log routing decisions to traces; eval routing accuracy as a metric |

### 3.4 Implementation note (no code)

A `Router` node early in the graph annotates state with the chosen tier; the LLM abstraction layer resolves tier → concrete model via config (`gemini-2.5-flash-lite-preview` or `gemini-2.5-flash`). Both share the same `GEMINI_API_KEY` and SDK — the only difference per tier is the model string and a temperature/thinking-budget config. Routing decisions are emitted to the trace for the cost dashboard.

---

## 04 · Guardrails & Reliability

*Interview value: among the most-asked production topics — "how do you stop it doing the wrong thing, and what happens when it fails?"*

### 4.1 Guardrails (via LangChain/LangGraph middleware)

LangChain's agent **middleware** (hooks around model calls) and LangGraph **conditional edges / interrupts** implement guardrails as first-class graph elements, not prompt hopes.

**Input guardrails (before the model):**
- **Topicality** — reject/redirect clearly off-topic or abusive input (keeps a travel agent a travel agent).
- **Prompt-injection / jailbreak detection** — flag inputs trying to override instructions or exfiltrate the system prompt.
- **PII detection/redaction** — detect and redact sensitive personal data before it reaches the model or logs (Presidio or a small classifier).

**Output guardrails (after the model, before the user/action):**
- **Grounding / faithfulness** — RAG-derived claims must be supported by retrieved context; ungrounded claims trigger a retry or a "not found in sources" fallback.
- **No-hallucinated-booking (structural)** — *only* the Action/Booking agent may assert a reservation, and *only* after the reservation service returns a confirmation ID. The generator model is structurally prevented from claiming a booking happened.
- **Schema validation** — structured outputs (itinerary, budget table) must conform to a schema; malformed output triggers a retry.
- **Budget constraint** — itinerary total ≤ stated budget; violations are caught deterministically and sent back for re-planning.

### 4.2 Retry logic

Two distinct mechanisms — separating them is itself an interview-worthy point:

**Infrastructure-level retries** (transport failures):
- API timeout / 429 / 5xx → **exponential backoff with jitter**, bounded attempts.
- Persistent failure → **fallback model** (e.g., Flash → Flash-Lite as degraded fallback, or Groq as a secondary provider in the LLM abstraction if Gemini API is unreachable), then graceful degradation (return partial results with a flag).
- A simple **circuit breaker** prevents hammering a down dependency.

**Quality-level retries** (the output is *returned* but *wrong*):
- Output fails a guardrail (ungrounded, schema-invalid, over budget) → **critique-and-retry / self-reflection loop**: a critic pass (large tier) explains what's wrong; the generator regenerates with that feedback. Bounded to ~2 retries to cap cost/latency. Still failing → degrade gracefully and surface the limitation honestly.

### 4.3 Self-reflection as a subgraph

The critique-and-retry loop is a small LangGraph subgraph: `generate → validate → (pass ? done : critique → regenerate)`. It's reused for itinerary synthesis and RAG answers. This is the single most impressive reliability pattern to demo — induce a hallucination in the demo and show the system catch and correct it.

### 4.4 Tradeoffs

Guardrails and retries add latency and cost. Mitigations: run cheap deterministic checks (schema, budget) before expensive LLM-judge checks; cap retry counts; route critique to the large tier only when a check actually fails; track guardrail false-positive rate as an eval metric so you don't over-block valid requests.

---

## 05 · Memory Management

*Interview value: clean, well-bounded topic interviewers love; demonstrates you understand context windows, personalization, and cost.*

### 5.1 Three memory types

| Type | What it holds | Lifetime | Storage |
|---|---|---|---|
| **Short-term (working/session)** | Current trip context, recent turns, in-progress plan, tool results this session | Session | Graph state + session store; windowed/summarized to fit context |
| **Long-term** | User profile, durable preferences (vegetarian, aisle seat, "loves history"), past trips, learned constraints | Across sessions | DB (SQLite/Postgres); optionally embedded for semantic recall |
| **Cache** | Repeated query answers; slow-changing API/RAG results | TTL / eviction | Redis or in-memory |

### 5.2 Short-term memory

The graph state carries the working context. To stay within the context window on long multi-turn sessions, older turns are **summarized** (rolling summary) rather than dropped wholesale, preserving constraints the user stated early ("budget $3000") even after many turns.

### 5.3 Long-term memory

At session start, the user's profile and durable preferences are loaded. A **write policy** governs promotion from short-term to long-term: explicit preferences ("I'm vegetarian") and repeated behaviors are persisted; ephemeral chatter is not. For richer recall, preferences/past trips can be embedded so the agent can semantically retrieve "have I been somewhere like this before?" This doubles as a second, smaller RAG surface — a nice symmetry to mention.

### 5.4 Caching (two kinds)

- **Semantic cache** — embed the incoming query; if it's highly similar (cosine > threshold) to a previously answered one, return the cached answer and skip the LLM. Cuts cost/latency on repeated or near-duplicate queries. (GPTCache or a Redis-backed embedding cache.)
- **API / tool-result cache** — cache slow-changing results with appropriate TTLs (visa docs long, weather short, flight prices very short or not at all). Coordinated with RAG staleness (Section 06) so cache never serves known-stale reference data.

### 5.5 Tradeoffs & options

| Concern | Options | Note |
|---|---|---|
| Session/cache store | **Redis** (Upstash free tier / local) · in-memory | Redis if you want persistence + semantic cache; in-memory is simplest |
| Semantic cache | **GPTCache** · custom Redis+embeddings | GPTCache is purpose-built; custom is more transparent for learning |
| Long-term store | **SQLite** (MVP) · Postgres (Supabase/Neon) post-MVP | Same store as user state |
| Risk | Stale cache serving wrong info | TTLs + staleness coordination; cache keys include data-version |

---

## 06 · RAG Subsystem (Advanced)

*All three advanced pieces are in MVP per your decision: hybrid retrieval + rerank, query decomposition, staleness detection + automated re-ingestion.*

### 6.1 Collections & chunking

- **Visa/entry requirements** — one doc per country, **whole-document** chunking (fragmenting loses critical exceptions like "except passport holders of X").
- **Travel advisories** — daily-refreshed, sliding-window chunks.
- **Destination guides** — sliding-window with ~15% overlap (narrative context bleeds across paragraphs).

Every chunk carries metadata: source URL, country ISO, passport nationality, advisory level, `last_verified` timestamp, and a **content hash** (for staleness diffing).

### 6.2 Retrieval pipeline

`metadata pre-filter (country, passport) → query rewrite (small tier) → hybrid search (vector + BM25) → cross-encoder rerank → top-k assembly with citations`. Hybrid + rerank because visa text has exact terms ("visa-free", "90 days", "onward ticket") that pure vector search misses.

### 6.3 Query decomposition

Multi-part queries are split into sub-queries before retrieval, each retrieved independently, then merged. Examples:
- *"two US passports and one Indian passport to Japan"* → two visa lookups (US→JP, IN→JP), merged into a per-traveler answer.
- *"Tokyo then Kyoto then Osaka"* → per-city retrieval for guides/advisories.

Implemented as a **decomposition node** (small tier) that emits a list of sub-queries; the RAG agent fans out, retrieves per sub-query, and the synthesis step (large tier) composes a single grounded answer. This directly powers the demo's multi-passport narrative.

### 6.4 Staleness detection + automated re-ingestion

- Each chunk stores `last_verified` + `content_hash`.
- A **scheduled job** re-fetches each source on a per-collection cadence (advisories daily, visa weekly, guides monthly), recomputes the hash, and **re-ingests only changed documents** (re-chunk, re-embed, idempotent upsert), updating timestamps.
- At query time, if a retrieved chunk is older than its staleness threshold, the response carries a **"verify before travel"** warning.
- Scheduler options (pros/cons): **APScheduler** (in-process, simplest, dies with the app) · **GitHub Actions scheduled workflow** (free, external, no always-on server needed — good fit for free-tier hosting) · system **cron** (if a persistent host exists). *Recommendation: GitHub Actions scheduled workflow* so re-ingestion doesn't depend on a sleeping free-tier web service.

### 6.5 Curation scope for MVP

Curate **50 countries** (the resolved demo list), not all 195. The 50 are chosen to exercise every RAG use case — not just visa-free tourist destinations, but a deliberate spread of **travel-advisory levels** (the warning path), major economies/superpowers (incl. China, Russia), and Middle East coverage — alongside high-volume tourist destinations across every region. The full enumerated list lives in the Phase 0 decision log. Depth where it's demoed; the remaining ~145 countries are a backlog item. Ingestion is automated, so 50 vs. 25 is low marginal effort (more pages to scrape/embed, well within Gemini Embedding's free limits).

---

## 07 · Phases & Milestones (5 weeks)

> **Authoritative sequencing lives in the phased build plan.** This section gives the week-by-week shape; the detailed, step-by-step build instructions are in the accompanying phase docs (**Phase 0–6**) and the **build index**, which are the source of truth for *how* to build. A design-review pass refined the original week plan in a few ways worth noting here:
> - **Phase 0 added** — a setup-only phase (decisions, accounts, dev env; no code) that front-loads every stall risk before Week 1.
> - **Eval + CI gate are cross-cutting, seeded in Phase 1 and grown each phase** — not a Week 5 task. (The Week 5 work below becomes eval *depth* + dashboards, not eval from scratch.)
> - **Memory is split** — basic memory (profile load + session state) lands in Phase 2 with the core loop; advanced memory (rolling summary, write policy, semantic cache) stays in Phase 3.
> - **The no-hallucinated-booking guardrail is designed in Phase 3 but enforced + tested in Phase 4** (it can't be validated until the Booking agent exists).
> - **Demo fixtures are captured from Phase 2 onward** so the demo is replayable well before final polish.

Each week ends demoable. Observability and eval are wired **from Week 1**, not deferred.

### Week 1 — Foundation, skeleton, observability-from-day-1, deploy early
- Repo scaffold, config, secrets, **LLM abstraction layer with 2-tier routing stubs**.
- FastAPI streaming endpoint; minimal React chat UI.
- LangGraph skeleton with **one** tool (weather) and the state schema (multi-user-ready).
- **LangSmith tracing instrumented in the first node** (set the pattern early).
- Hardcoded demo user profile.
- **Deploy the skeleton to free tier** (de-risk deployment now).
- *Milestone:* traced weather query on the live URL; trace shows which model tier ran.

### Week 2 — Core agentic loop + routing + RAG
- Travel Search agent (Duffel flights + Stays, budget filtering).
- RAG agent: ingestion pipeline, hybrid retrieval + rerank, citations; curate countries.
- **Router node** active: small for classify/rewrite, large for synthesis.
- Orchestrator plans across agents; flight-search ∥ weather in parallel.
- Budget reasoning (allocation + affordability).
- *Milestone:* Japan query → budget-aware itinerary with visa + weather; routing visible in traces.

### Week 3 — Guardrails + reliability + memory
- Input guardrails (topicality, injection, PII) and output guardrails (grounding, schema, budget, no-hallucinated-booking) via middleware/conditional edges.
- Retry logic: infra backoff + fallback; **self-reflection / critique-and-retry** subgraph.
- Memory: short-term session (rolling summary), long-term profile persistence, **semantic + API caches**.
- *Milestone:* guardrails block a red-team input; an induced hallucination triggers a corrective retry; a cache hit visibly cuts latency; a stored preference (vegetarian) is recalled.

### Week 4 — Activities/Booking subagent + Action agent + advanced RAG
- Activities/Booking subagent: real search (Overpass restaurants/attractions + Ticketmaster/Eventbrite events) + **real restaurant reservation** via the self-hosted mock reservation service (idempotency/confirmation/cancellation). Real flight booking via Duffel sandbox wired through the same `BookingProvider` contract.
- Action agent: real calendar event (low-risk) + drafted booking summary/email (high-risk) + confirmation gate.
- Advanced RAG: **query decomposition** (multi-passport/multi-city) + **staleness detection + automated re-ingestion** (scheduled workflow).
- *Milestone:* multi-passport decomposition query works end-to-end; a real sandbox reservation returns a confirmation ID; the staleness job re-ingests a changed doc.

### Week 5 — Eval depth, dashboards, CI/CD, polish, demo
- Eval harness expanded: retrieval Hit@k, faithfulness (LLM-judge), itinerary validity, **routing accuracy**, **guardrail precision/recall**, decomposition correctness — wired as a **CI gate**.
- Observability dashboards: latency, **token cost by tier**, **cache-hit rate**, **retry rate**, eval scores over time.
- CI/CD: GitHub Actions (lint + test + eval-gate + deploy).
- Frontend polish (itinerary cards, budget bar, citations, reservation confirmations), README + architecture diagram, recorded demo video, live link.
- *Milestone:* recruiter opens URL, runs the full demo, sees dashboards + passing eval gate.

### 07.3 Cut-line discipline (if a week slips)

**Cut first, in order:** complexity-based routing (keep deterministic task-type routing) → automated staleness (keep a manual-trigger re-ingestion script) → drafted email action (keep calendar + booking summary) → semantic cache (keep API cache) → frontend polish.
**Never cut:** the orchestration loop, 2-tier routing (at least deterministic), RAG with citations + decomposition, core guardrails (grounding + no-hallucinated-booking), one real action + one real sandbox reservation, always-on tracing, live deployment.

---

## 08 · Tech Stack

Where multiple free options exist, both are listed with a recommendation.

### 8.1 Core (decided)

| Layer | Choice | Why |
|---|---|---|
| Backend | **Python + FastAPI** | Async, SSE streaming, Pydantic typing for tool/guardrail schemas |
| Frontend | **React (Vite)** | Chat + itinerary cards + reservation UI |
| Orchestration | **LangGraph** | Inspectable state graph; conditional edges/interrupts power guardrails & retries |
| Guardrail/middleware | **LangChain middleware + LangGraph edges** | Guardrails as first-class graph elements |
| LLM (small tier) | **Gemini 2.5 Flash-Lite** (Google AI Studio) | Free tier: 1,500 RPD, 1M TPM; no GPU needed; same SDK as large tier |
| LLM (large tier) | **Gemini 2.5 Flash** (Google AI Studio) | Free tier: 1,500 RPD, 1M TPM; strong reasoning; 1M token context window |

### 8.2 Decisions with options (pick one)

**Vector DB**

| Option | Pros | Cons |
|---|---|---|
| **Qdrant** ✅ **LOCKED (MVP)** | Production-grade **native hybrid search** (dense + sparse), generous free cloud | Slightly more setup than Chroma |
| **Chroma** | Trivial local setup, zero infra | Basic at scale; no native hybrid |
| **pgvector** | One DB for state + vectors | Hybrid search less ergonomic |

*Locked: **Qdrant** — chose the stronger prod story over Chroma's faster start; native hybrid (vector + sparse/BM25) search aligns directly with the Section 06 hybrid-retrieval requirement, and metadata pre-filtering is a native payload filter. **Qdrant Cloud free tier** (~1GB, no card) for the deployed demo; local Docker Qdrant for dev — same `qdrant-client`, switched by config.*

**State / long-term memory store**

| Option | Pros | Cons |
|---|---|---|
| **SQLite** (MVP) | Zero setup, file-based | Single-writer |
| **Supabase** (free Postgres) | Real Postgres + built-in auth (future multi-user) | Pauses on inactivity |
| **Neon** (serverless Postgres) | Scales to zero, branching | Cold starts |

*Rec: SQLite now; Supabase post-MVP (free auth solves multi-user).*

**Cache / session store**

| Option | Pros | Cons |
|---|---|---|
| **Upstash Redis** (free tier) | Serverless Redis, persistence, good for semantic+API cache | Free-tier request caps |
| **In-memory** | Simplest | Lost on restart; no cross-instance sharing |
| **GPTCache** | Purpose-built semantic cache | Another dependency |

*Locked: **Redis (Upstash free tier)** for cache + session; custom Redis-backed semantic cache (GPTCache optional, not a dependency).*

**Embeddings:** **Gemini Embedding model** via Google AI Studio (10M tokens/minute free — remarkably generous; handles text for RAG) · `BAAI/bge-small-en` via sentence-transformers (fully local, no API needed — good fallback if offline dev is needed) · `nomic-embed` (long context). *Locked: **Gemini Embedding** (same API key, same SDK); `bge-small-en` as offline fallback.*

**Reranker:** `cross-encoder/ms-marco-MiniLM-L-6-v2` (free, runs locally via sentence-transformers — no GPU required for inference on this small model).

**PII detection:** **Microsoft Presidio** ✅ **LOCKED** (free, open source) · regex + small-LLM classifier (fallback).

**Guardrails framework:** **Custom checks via LangChain middleware** ✅ **LOCKED** (most transparent; can explain every check in interviews) · Guardrails AI (declarative validators) · NeMo Guardrails (rails DSL; heavier). Pros/cons: custom = full control + best learning, more code; Guardrails AI = fast declarative validators, less flexible; NeMo = powerful rails, steeper setup.

### 8.3 LLM provider — locked: Google Gemini API (AI Studio free tier)

**Decision:** Google Gemini API, accessed via Google AI Studio. No GPU, no local hosting, no Ollama.

| Model | Tier | Free limits (June 2026) | Used for |
|---|---|---|---|
| **Gemini 2.5 Flash-Lite** | Small / fast | 1,500 RPD · 1M TPM · 15 RPM | Classification, routing, rewriting, guardrail checks |
| **Gemini 2.5 Flash** | Large / reasoning | 1,500 RPD · 1M TPM · 10 RPM | Itinerary synthesis, budget optimization, self-reflection |
| **Gemini Embedding** | Embeddings | 10M tokens/min free | RAG corpus + semantic cache embeddings |

**Setup:** Get one API key from `aistudio.google.com/apikey` (Google account only, no credit card). Both model tiers and embeddings share this single key. Python SDK: `google-generativeai`. Also exposes an OpenAI-compatible endpoint for easy LangChain/LangGraph integration.

**Free tier reality check (important):**
- 1,500 RPD shared across both tier models — this is the binding daily constraint, not TPM.
- At ~5–10 LLM calls per agent run, 1,500 RPD supports ~150–300 full query completions/day — sufficient for development and demos, tight for a high-traffic live deployment.
- Free tier data privacy: Google's terms permit using free-tier API inputs/outputs for model improvement. For this portfolio project with synthetic/demo data, this is not a concern. In a production deployment with real user data, move to Vertex AI (paid, data not used for training).
- Rate limit handling: implement exponential backoff (1s → 2s → 4s → 8s) on 429 responses — standard practice and directly relevant to the reliability pillar.

**Fallback:** Groq (free tier, OpenAI-compatible, runs Llama-3.3-70B and Llama-3.1-8B) is wired into the LLM abstraction layer as a secondary provider. A single config switch routes all calls to Groq if the Gemini API is unreachable. This demonstrates multi-provider fallback — an interview talking point — without depending on Groq as primary.

| Provider comparison | Google Gemini (primary) | Groq (fallback) |
|---|---|---|
| Free RPD | 1,500 | 1,000 |
| Free TPM | 1,000,000 | 6,000 |
| Model family | Gemini 2.5 Flash/Flash-Lite | Llama-3.3-70B / Llama-3.1-8B |
| Speed | Fast | Extremely fast (LPU, 300–1000 TPS) |
| SDK | `google-generativeai` + OpenAI-compat | OpenAI-compatible |
| No credit card | Yes | Yes |

### 8.4 Live data & booking APIs — final locked stack (all free REST APIs)

Verified available June 2026. 12 components, $0 total cost. Six need no key/signup; five need a free instant key; one is self-built.

| Need | Provider | Access | Free limit | Key? |
|---|---|---|---|---|
| Flights (search + **book**) | **Duffel** | REST + Python SDK | Unlimited sandbox; "Duffel Airways" test airline | Free key, 1-min signup |
| Hotels (search) | **Duffel Stays** | REST, same SDK | Unlimited sandbox | Same Duffel key |
| Weather + geocoding | **Open-Meteo** | REST | No limit (non-commercial); 7-day + historical | **No key** |
| City → coordinates | **Nominatim (OSM)** | REST | 1 req/sec public server | **No key** |
| Restaurants / attractions | **Overpass API (OSM)** | REST | No hard limit (fair use); ODbL data | **No key** |
| Events / concerts | **Ticketmaster Discovery** | REST | 5,000 calls/day | Free key, instant |
| Community events | **Eventbrite** | REST | 1,000 calls/hr (OAuth token) | Free token |
| Restaurant **booking** | **Mock reservation service** (self-built) | REST (self-hosted FastAPI) | n/a — your code | Internal |
| Directions / travel time | **OpenRouteService** | REST + Python client | 2,000 calls/day | Free key, instant |
| Currency / FX | **Frankfurter** | REST | No limit; ~30 currencies, ECB | **No key** |
| Country metadata / ISO | **REST Countries** | REST | No limit | **No key** |
| Calendar action | **.ics generation** (`icalendar`) | Python library | n/a | **No key** |

**Visa/advisory data (RAG sources, not live APIs):** `travel.state.gov` (225 country pages, advisory levels) and `CDC Travelers' Health` (vaccination/health) are **scraped on a schedule and ingested into the vector DB** — not queried at request time. Both are free public government pages. Optionally, `Travel Buddy Visa API` (free demo tier) can supplement with structured passport×destination lookups.

**The booking abstraction.** All booking goes through one `BookingProvider` interface (search → check → reserve → confirm → cancel). Flights route to **Duffel** (real sandbox); restaurants route to the **mock reservation service** (same interface, self-hosted). This single seam is what lets you swap in a real provider — or Sabre's MCP server — as a config change.

**On Sabre (evaluated, not used):** Sabre's Agentic API + travel-native MCP server is the enterprise-grade alternative and a strong architecture talking point, but its sandbox requires a **Pseudo City Code** obtainable only via a commercial agreement (7–21 days, paid). It is therefore **out of the MVP** and kept as a named extension point behind the `BookingProvider` contract. *(Amadeus Self-Service — the historical default — is decommissioned July 17, 2026 and excluded entirely.)*

### 8.5 Ops & observability (free tiers)

| Need | Option(s) |
|---|---|
| Tracing/eval | **LangSmith** (free Developer tier) ✅ **LOCKED** — tracing + datasets/eval in one product · (Langfuse was the prior pick) |
| Scheduler (re-ingestion) | **GitHub Actions scheduled workflow** ✅ **LOCKED** · APScheduler · cron |
| CI/CD | **GitHub Actions** (free for public repos) |
| Deployment | **Hugging Face Spaces** ✅ **LOCKED** (Docker SDK) · Railway · Render (free tiers — Section 14) |
| Secrets | Platform env vars + local `.env` (never committed) |

---

## 09 · Data Strategy

### 9.1 Three data classes

| Class | Examples | Handling | Freshness |
|---|---|---|---|
| **Live/volatile** | flight/hotel prices, availability, weather, FX | API tools per-query; minimal/no caching for prices | Real-time |
| **Reference/slow** | visa rules, advisories, guides | RAG corpus; staleness-checked + auto re-ingested | Days–months |
| **User state/memory** | profile, prefs, trip history, session | State + memory stores | Per session/user |

### 9.2 RAG corpus sourcing (free/public)

travel.state.gov country pages + advisory levels and CDC Travelers' Health pages (scraped → embedded); REST Countries for structured passport/ISO data; open-web destination overviews. 50 curated countries for MVP (list in the Phase 0 decision log). Live data (flights, hotels, weather, events, FX) is fetched per-query, never ingested.

### 9.3 Ingestion pipeline

Fetch → clean/normalize → chunk per collection strategy → embed → upsert with full metadata (incl. `content_hash`, `last_verified`). Idempotent. Powers staleness/re-ingestion (Section 06.4).

### 9.4 Demo user profile

Single hardcoded profile with a `user_id` FK throughout (so multi-user is additive later): home airport, passport nationality, budget defaults, interest tags, durable preferences (e.g., vegetarian), empty trip history that grows via long-term memory.

### 9.5 Eval data

~40 labeled cases covering: visa retrieval, **decomposition** (multi-passport/multi-city), budget validity, itinerary validity, **routing** (expected tier), and **guardrail** red-team inputs. Small, honest, sufficient to demonstrate discipline; expand post-MVP.

---

## 10 · Evaluation & Observability (first-class, always-on)

### 10.1 What gets measured

| Layer | Metric | MVP target | Method |
|---|---|---|---|
| Retrieval | Hit@5 | ≥ 85% | Labeled set |
| Retrieval | Faithfulness | ≥ 0.90 | LLM-judge (sampled) |
| Decomposition | Sub-query correctness / merge quality | ≥ 90% | Labeled multi-part set |
| Routing | Correct tier chosen | ≥ 90% | Labeled set + trace audit |
| Guardrails | Block rate / false-block rate | ≥ 95% / < 5% | Red-team + valid sets |
| Reliability | Injected-failure handling | 100% | Fault injection |
| Itinerary | Budget & temporal validity | 100% | Deterministic checks |
| System | End-to-end latency; cost/query | < 90s; tracked | Traces |

### 10.2 Two kinds of eval

- **Deterministic** (always-run, cheap, CI-gating): schema, budget, date validity, routing-tier match.
- **LLM-as-judge** (sampled): faithfulness, decomposition merge quality, itinerary helpfulness.

### 10.3 Eval-as-CI-gate

Every push runs the eval set; if Hit@5 or faithfulness regresses below threshold, the build fails and won't deploy. Directly answers the JD language on drift and trustworthiness.

### 10.4 Observability (LangSmith) — always on from Week 1

Every run traces: input guardrail verdicts, router decision + tier, plan, each tool call + latency, retrieved chunks, retry/reflection events, token usage by tier, cache hits, output guardrail verdicts, final output. Dashboards: latency, **cost-by-tier**, **cache-hit rate**, **retry rate**, eval scores over time. This is a live artifact to screen-share in interviews. Because LangSmith's free Developer tier has a monthly trace cap, a **trace-sampling flag** (full for interactive/demo runs, sampled for high-volume eval/CI runs) keeps always-on tracing within the free tier — itself a small cost-awareness signal.

---

## 11 · Challenges & Mitigations

| # | Challenge | Mitigation |
|---|---|---|
| 1 | Duffel sandbox: airline sandboxes can be flaky; "used up" inventory | Book against "Duffel Airways" test airline (Duffel-guaranteed reliable); cache known-good fixtures; never depend on one live call mid-demo |
| 2 | Agent non-determinism / wrong tool | Graph-constrained tool choice; loop caps; deterministic gates |
| 3 | Latency stacks up (tools + LLM + guardrails + retries) | Parallelize independent tools; run cheap deterministic checks before LLM-judge; route critique to Flash only on failure; stream partials to UI; implement exponential backoff rather than hard-failing |
| 4 | Gemini API rate limits (1,500 RPD shared across tiers) | Cache tool results + semantic cache for repeated queries; batch non-urgent LLM calls; Groq as fallback provider in the LLM abstraction; never exhaust daily quota in a live demo (run demos against cached fixtures) |
| 5 | Free-tier cold starts/pausing | Keep-warm ping or non-sleeping platform; recorded video backup; **run re-ingestion via GitHub Actions, not the web app** |
| 6 | Scope creep (lots in MVP) | 5-week sequencing + Section 07.3 cut-line |
| 7 | Secrets in public repo | `.env` + platform secrets; pre-commit secret scanner |
| 8 | RAG returns wrong country's rules | Metadata pre-filter (country ISO + passport) before semantic search |
| 9 | Hallucinated bookings | Structural gate: only Booking/Action agent asserts a reservation, only after confirmation ID; output guardrail enforces it |
| 10 | Over-blocking valid inputs (guardrails) | Track false-block rate as a metric; tune thresholds |
| 11 | Retry loops inflate cost/latency | Bounded retries (~2); circuit breaker; reflection only on actual failure |
| 12 | Stale cache serving wrong reference info | TTLs + data-version cache keys; coordinate with RAG staleness |
| 13 | Mock reservation looks "fake" in interview | Frame honestly as a partner-API stand-in implementing real semantics (idempotency, confirmation, cancellation); same tool contract as real provider |

---

## 12 · Security, Safety & Responsible AI

- **Action confirmation gates** for high-risk actions, as graph edges.
- **No real payments**; reservations are sandbox/mock — highest-harm failure mode designed out.
- **Grounded, cited answers** with `last_verified` dates; "not found in sources" instead of inventing.
- **Disclaimers** on visa/advisory answers ("verify with official sources before travel").
- **PII redaction** before model/log (Presidio).
- **Prompt-injection defense** as an input guardrail.
- **Secrets hygiene** (Challenge #7).
- Solo demo profile only; no real personal data in MVP.

---

## 13 · Repository Structure

```
wanderwise/
├── README.md
├── docs/
│   ├── design-doc.md            # this document
│   ├── architecture.png
│   └── demo-script.md
├── .github/workflows/
│   ├── ci.yml                   # lint + test + eval-gate + deploy
│   └── reingest.yml             # scheduled staleness re-ingestion
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI, routes, SSE
│   │   ├── config.py            # env-driven (model tiers, providers, thresholds)
│   │   ├── orchestrator/
│   │   │   ├── graph.py         # LangGraph definition (incl. guardrail/retry edges)
│   │   │   ├── state.py
│   │   │   ├── router.py        # 2-tier LLM routing node
│   │   │   └── nodes/           # plan, assemble, gates, reflection subgraph
│   │   ├── agents/
│   │   │   ├── travel_search.py
│   │   │   ├── weather.py
│   │   │   ├── rag.py
│   │   │   ├── activities_booking.py
│   │   │   └── action.py
│   │   ├── guardrails/          # input/output validators, PII, injection checks
│   │   ├── reliability/         # retry, backoff, circuit breaker, fallback
│   │   ├── memory/              # short-term, long-term, semantic+API cache
│   │   ├── tools/               # API client wrappers (Duffel, Open-Meteo, Overpass, Ticketmaster, Eventbrite, ORS, Frankfurter, calendar)
│   │   ├── booking/             # BookingProvider abstraction (Duffel real + mock backends)
│   │   ├── reservation_service/ # self-hosted mock booking (idempotency, confirm, cancel)
│   │   ├── rag/
│   │   │   ├── ingest.py
│   │   │   ├── retriever.py     # hybrid + rerank
│   │   │   ├── decompose.py     # query decomposition
│   │   │   ├── staleness.py     # hash diff + re-ingest
│   │   │   └── collections.py   # chunking strategies
│   │   ├── llm/                 # provider/tier abstraction (Gemini primary | Groq fallback)
│   │   ├── state/               # user profile + session store
│   │   └── observability/       # LangSmith tracing setup
│   └── tests/
│       ├── unit/
│       └── eval/
│           ├── dataset.jsonl    # ~40 labeled cases
│           └── run_eval.py      # retrieval/decomp/routing/guardrail/itinerary checks
├── frontend/
│   └── src/{components, hooks, api}/
├── data/{corpus, fixtures}/
├── scripts/
├── .env.example
├── docker-compose.yml           # local: backend + qdrant + redis (no Ollama — hosted LLM only)
└── pyproject.toml
```

**Principles:** agents reason / tools fetch; guardrails, reliability, memory are their own modules (not scattered); LLM tier/provider behind one abstraction; reservation service is swappable behind the tool contract; eval lives in the repo and gates CI; re-ingestion runs as a scheduled workflow independent of the web app.

---

## 14 · Deployment Strategy

| Platform | Pros | Cons | Fit |
|---|---|---|---|
| **Hugging Face Spaces** ✅ **LOCKED** | Free, ML-friendly, Docker support | Single-container friendliest | Slim combined demo |
| **Railway** | Easy multi-service (backend + redis + db) | Monthly usage cap | Backend + stores |
| **Render** | Free web services + managed Postgres | Cold starts/sleep | All-rounder |

**Locked MVP path:** containerize the backend (Gemini API key passed as env var, same config dev and prod), serve built React as static files from FastAPI (single deployable), push to **Hugging Face Spaces** (Docker SDK), use **Upstash Redis** (serverless) for cache/session and **Qdrant Cloud free tier** for the vector DB so the single container hosts neither store, and run **re-ingestion via GitHub Actions** (not the web app). De-risk deployment in **Week 1 (Phase 1)**. Keep recorded video + fixtures as demo fallback so rate-limit exhaustion never kills a live recruiter walkthrough.

---

## 15 · Resume & Interview Framing

**Resume line (option):**
> Built a production-shaped agentic AI travel planner: a LangGraph orchestrator with **2-tier LLM routing** (Gemini 2.5 Flash-Lite + Flash via Google AI Studio free tier), **input/output guardrails**, **infra + self-reflection retry logic**, an **advanced RAG** subsystem (hybrid retrieval, query decomposition, staleness-triggered auto re-ingestion), **short/long-term memory + semantic caching**, **real flight booking via Duffel**, and a **provider-agnostic booking abstraction** (real API + self-built reservation microservice) — with always-on tracing, a CI-gated eval suite, and a cloud-deployed live demo. Python/FastAPI + React; open-source stack (Gemini API, Qdrant, LangSmith, OpenStreetMap APIs).

**Stories to tell (each maps to a JD ask):**
- *Orchestration* — "RAG is one tool among many; the agent decides when to retrieve, call an API, compute, remember, or act."
- *Cost/latency* — the routing layer + cache-hit and cost-by-tier dashboards.
- *Reliability* — induce a hallucination live; show the self-reflection loop catch and fix it.
- *Trustworthiness* — CI eval-gate that blocks deploys on quality regression; staleness warnings on RAG answers.
- *FDE-specific* — broad tool integration, graceful degradation on every failure, and a live, fault-tolerant deployment that works in a messy real environment.

---

## 16 · Decisions (all RESOLVED before Week 1)

*All ten are now locked. The full enumerated demo-country list and the runtime config values live in the Phase 0 decision log, which is the source of truth `config.py` encodes.*

1. **Booking stack — RESOLVED:** Duffel for flights (real sandbox booking) + mock reservation service for restaurants, both behind one `BookingProvider` contract. Sabre and Amadeus excluded (see Section 8.4).
2. **Hotels — RESOLVED: booking enabled.** Duffel Stays booking via the same SDK/token, routed through the same `BookingProvider` as flights — a second real booking type for near-zero extra effort. (Reverses the earlier search-only default.)
3. **Vector DB — RESOLVED: Qdrant.** Chose the stronger prod story + native hybrid search over Chroma's faster start. Qdrant Cloud free tier for deploy, local Docker for dev.
4. **Cache/session store — RESOLVED: Redis (Upstash free tier)** for cache + session; custom Redis-backed semantic cache.
5. **Guardrails framework — RESOLVED: custom via LangChain middleware** (most transparent; explainable in interviews).
6. **LLM provider — RESOLVED:** Google Gemini API (AI Studio free tier). Gemini 2.5 Flash-Lite (small tier) + Gemini 2.5 Flash (large tier) + Gemini Embedding. Single API key, single SDK. Groq wired as fallback in the LLM abstraction layer.
7. **Re-ingestion scheduler — RESOLVED: GitHub Actions scheduled workflow** (external; survives free-tier sleep).
8. **Deployment target — RESOLVED: Hugging Face Spaces** (Docker SDK; single deployable serving React static from FastAPI). Deploy skeleton in Phase 1.
9. **Demo countries — RESOLVED: 50** — major economies/superpowers (incl. China, Russia), Middle East, and a spread of advisory levels for the travel-warning use case, alongside high-volume tourist destinations. Full list in the Phase 0 decision log.
10. **Embeddings — RESOLVED: Gemini Embedding** (same key/SDK, generous free limits); `bge-small-en` as offline fallback.
