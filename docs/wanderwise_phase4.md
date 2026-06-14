# WanderWise — Phase 4: Booking, Actions & Advanced RAG
### Phase Design Document (implementation roadmap, code-light)

| | |
|---|---|
| **Phase** | 4 of 6 — Booking, Actions & Advanced RAG |
| **Goal** | Make the demo genuinely impressive: real action-taking (booking, calendar, drafted email) and the two advanced-RAG pieces that power the full multi-passport narrative |
| **Duration** | ~Week 4 |
| **Prereq** | Phase 3 complete — guardrails, reliability, and advanced memory hardening the system; the no-hallucinated-booking gate exists as a structural seam awaiting an agent to enforce against |
| **Defining moment** | This is the phase where the full demo narrative finally works end-to-end — and where the booking guardrail designed in Phase 3 is finally enforced and tested |
| **Exit milestone** | The full multi-passport Japan query: real Duffel flight booking + a real mock restaurant reservation with a confirmation ID + a calendar hold created + an itinerary email drafted for confirmation, with query decomposition handling the two passports and a staleness job re-ingesting a changed document |

---

## What Phase 4 is (and isn't)

Phase 4 is the payoff phase. Everything before it built a system that *plans*; this phase makes it *act* — safely, behind confirmation gates and the structural booking guardrail. It completes the agent roster with the **Activities/Booking subagent** and the **Action agent**, introduces the **`BookingProvider` abstraction** that unifies real and mock booking behind one contract, and adds the two advanced-RAG capabilities deferred from Phase 2: **query decomposition** (the multi-passport/multi-city fan-out) and **staleness detection + automated re-ingestion** (using the `content_hash`/`last_verified` hooks seeded back in Phase 2).

A deliberate ordering choice: build the **booking abstraction and the mock reservation service first**, then wire **real Duffel booking** into the same contract, then **enforce the no-hallucinated-booking gate** (which now has a real agent to guard), then the **Action agent**, then advanced RAG. Booking-before-RAG because the booking guardrail is the Phase 3 loose end and closing it early de-risks the most safety-sensitive code.

What Phase 4 is *not*: no real payments or real money (sandbox/mock only — the highest-harm failure mode is designed out), no eval *depth* or dashboards (Phase 5), no frontend polish (Phase 6).

---

## Repo structure at the end of Phase 4

Complete root tree, incremental from Phase 3: **(new)** = created this phase, **(extended)** = changed this phase, **(unchanged)** = carried forward. Every root-level subdirectory is shown. State schema and tool contract remain stable (extended, not rebuilt).

```
wanderwise/
├── README.md                        # (unchanged)
├── .env                             # + Ticketmaster/Eventbrite/ORS keys active (extended)
├── .env.example                     # + new var names (extended)
├── .gitignore                       # (unchanged)
├── pyproject.toml                   # + icalendar, ticketmaster/eventbrite/overpass/ORS clients (extended)
├── Dockerfile                       # (unchanged)
├── docker-compose.yml               # + reservation_service as a local service (extended)
├── docs/
│   ├── design-doc.md                # (unchanged)
│   ├── decision-log.md              # (unchanged)
│   ├── phase0–3.md                  # (unchanged)
│   └── phase4.md                    # (new)
├── .github/workflows/
│   ├── ci.yml                       # (unchanged — gate now runs decomposition cases)
│   └── reingest.yml                 # scheduled staleness re-ingestion workflow (new)
├── backend/
│   ├── app/
│   │   ├── main.py                  # (unchanged)
│   │   ├── config.py                # + booking provider map, action gates, events/places keys (extended)
│   │   ├── orchestrator/
│   │   │   ├── graph.py             # + activities_booking, action nodes; confirmation-gate edges (extended)
│   │   │   ├── state.py             # + reservations, confirmations, action drafts, decomposition fields (extended)
│   │   │   ├── router.py            # (unchanged)
│   │   │   └── nodes/
│   │   │       ├── plan.py          # + decomposition-aware planning (extended)
│   │   │       ├── budget.py        # (unchanged)
│   │   │       ├── assemble.py      # + reservations/actions in itinerary (extended)
│   │   │       └── reflection.py    # (unchanged)
│   │   ├── agents/
│   │   │   ├── weather.py           # (unchanged)
│   │   │   ├── travel_search.py     # + flight booking via BookingProvider (extended)
│   │   │   ├── rag.py               # + decomposition fan-out + staleness warnings (extended)
│   │   │   ├── activities_booking.py # restaurants/events search + real reservation (new)
│   │   │   └── action.py            # calendar (.ics) + drafted email + confirmation gate (new)
│   │   ├── booking/                 # (new — the BookingProvider abstraction)
│   │   │   ├── provider.py          # BookingProvider interface: search→check→reserve→confirm→cancel
│   │   │   ├── duffel_provider.py   # real Duffel flight + Stays (hotel) booking
│   │   │   └── mock_provider.py     # routes to the self-hosted reservation_service
│   │   ├── tools/
│   │   │   ├── contract.py          # (unchanged)
│   │   │   ├── weather.py           # (unchanged)
│   │   │   ├── duffel.py            # (unchanged — search; booking lives in booking/)
│   │   │   ├── places.py            # Overpass restaurants/attractions (new)
│   │   │   ├── events.py            # Ticketmaster Discovery + Eventbrite (new)
│   │   │   └── calendar.py          # .ics generation via icalendar (new)
│   │   ├── reservation_service/     # (new — self-hosted mock booking microservice)
│   │   │   ├── service.py           # FastAPI app: reserve/confirm/cancel endpoints
│   │   │   ├── store.py             # reservations + idempotency-key store
│   │   │   └── semantics.py         # idempotency, confirmation IDs, conflicts, rollback
│   │   ├── rag/
│   │   │   ├── ingest.py            # (unchanged)
│   │   │   ├── retriever.py         # (unchanged)
│   │   │   ├── collections.py       # (unchanged)
│   │   │   ├── embeddings.py        # (unchanged)
│   │   │   ├── decompose.py         # query decomposition: split → fan-out → merge (new)
│   │   │   └── staleness.py         # content-hash diff + idempotent re-ingest (new)
│   │   ├── guardrails/
│   │   │   ├── input.py             # (unchanged)
│   │   │   ├── pii.py               # (unchanged)
│   │   │   └── output.py            # no-hallucinated-booking now ENFORCED + tested (extended)
│   │   ├── memory/ reliability/ llm/ observability/ state/   # (unchanged)
│   └── tests/
│       ├── unit/                    # + reservation-service semantics tests (extended)
│       └── eval/
│           ├── dataset.jsonl        # + decomposition (multi-passport/city) cases (extended)
│           └── run_eval.py          # + decomposition correctness + booking-gate checks (extended)
├── frontend/                        # + reservation confirmation + action-draft UI (extended)
│   └── src/{components, hooks, api}/
├── data/
│   ├── corpus/                      # (unchanged — re-ingested in place by staleness job)
│   └── fixtures/                    # + booking/reservation/decomposition demo fixtures (extended)
└── scripts/
    ├── ingest_corpus.py             # (unchanged)
    └── reingest.py                  # invoked by reingest.yml workflow (new)
```

---

## Build order at a glance

Booking abstraction + mock service first (1–2), real booking + gate enforcement (3–4), Action agent (5), Activities search (6), then advanced RAG (7–8), then eval/integration (9–10).

| Step | Builds | Depends on |
|---|---|---|
| 1 | `BookingProvider` abstraction (the unifying contract) | Phase 1 tool contract |
| 2 | Mock reservation microservice (idempotency/confirm/cancel) | 1 |
| 3 | Real Duffel flight booking via `BookingProvider` | 1, Phase 2 Duffel search |
| 4 | **Enforce + test** the no-hallucinated-booking gate | 2, 3, Phase 3 seam |
| 5 | Action agent: calendar (.ics) + drafted email + confirmation gate | 3, 4 |
| 6 | Activities/Booking subagent: restaurants/events search + reservation | 2, places/events tools |
| 7 | Advanced RAG: query decomposition (multi-passport/city) | Phase 2 RAG |
| 8 | Advanced RAG: staleness detection + automated re-ingestion | Phase 2 hooks |
| 9 | Decomposition + booking-gate eval cases + demo fixtures | 4, 6, 7 |
| 10 | Assemble full itinerary + verify the full-narrative milestone | all |

---

## Step 1 — The `BookingProvider` abstraction

**Objective:** One interface that unifies real and mock booking, so flights and restaurants are interchangeable behind a single seam — the architecture that makes the whole booking story coherent.

**Build (`backend/app/booking/provider.py`):**
- Define the `BookingProvider` interface: `search → check → reserve → confirm → cancel`. Typed inputs/outputs, conforming to the Phase 1 uniform tool contract (typed I/O, latency budget, declared failure mode).
- Two backends register against it: `duffel_provider` (real flights, Step 3) and `mock_provider` (restaurants → the reservation service, Step 2). Selection is config-driven (the Phase 1 tier/provider pattern, applied to booking).

**Key detail:** this single seam is the interview line — "swapping in OpenTable later is a config change, not a rewrite." Build the interface before either backend so both are forced to conform to it, not the reverse.

**Done when:** the interface exists with both backends stubbed and config routing a booking request to the correct backend.

---

## Step 2 — Mock reservation microservice

**Objective:** A self-hosted service implementing *real* booking semantics — the principled stand-in where no free restaurant-booking API exists.

**Build (`backend/app/reservation_service/`):**
- A small **FastAPI service** (separate deployable, runs in docker-compose) exposing reserve/confirm/cancel endpoints behind the `BookingProvider` contract.
- Implement real semantics: **idempotency keys** (a retried reserve doesn't double-book), **confirmation IDs**, **availability conflicts** (a taken slot is rejected), and **cancellation/rollback**.
- Back it with a simple store (`store.py`) — in-memory or SQLite is fine; the point is correct semantics, not scale.

**Key detail:** frame this honestly (Challenge #13) — it's a partner-API stand-in implementing the same semantics as a real provider, behind the same contract. The idempotency/confirmation/cancellation behaviors are what make it credible rather than "fake." Write the unit tests for these semantics now (they're easy to assert and strengthen the eval story).

**Done when:** reserving returns a confirmation ID; a duplicate reserve with the same idempotency key returns the same reservation; a conflicting slot is rejected; cancellation rolls back.

---

## Step 3 — Real Duffel flight + hotel booking via `BookingProvider`

**Objective:** A real sandbox booking — the integration that proves you can wire a modern production API end-to-end.

**Build (`backend/app/booking/duffel_provider.py`):**
- Implement the full Duffel booking flow behind `BookingProvider`: search (reuse Phase 2) → price → **create order** → confirm → cancel. Book against the **"Duffel Airways" test airline** for reliability (Challenge #1).
- The Travel Search agent gains a booking path that goes *only* through the provider — never a direct call.
- **Hotel booking is enabled** (Phase 0 decision): Duffel Stays booking plugs into the same `BookingProvider` via the same Duffel token — a second real booking type for near-zero extra effort. Wire it alongside flight booking here.

**Key detail:** booking must be a deliberate, gated action — not something the agent does speculatively. Wire it so a booking only happens on an explicit decision in the graph, setting up the confirmation gate in Step 5.

**Done when:** a flight books for real against the Duffel sandbox (real order/confirmation, cancel working), and a hotel books via Duffel Stays through the same provider.

---

## Step 4 — Enforce + test the no-hallucinated-booking gate

**Objective:** Close the Phase 3 loose end. The structural gate now has real agents to guard.

**Build (`backend/app/guardrails/output.py`):**
- Enforce the rule designed in Phase 3: **only** the Booking/Action agent may assert a reservation, and **only** after the provider returns a confirmation ID. The generator model is structurally prevented from claiming a booking happened.
- Add the test that couldn't exist in Phase 3: induce the model to claim a booking with no confirmation ID → the gate blocks it. Conversely, a real confirmation flows through.

**Key detail:** this is a structural guarantee, not a prompt instruction — the assertion of a booking is gated on the *presence of a confirmation ID in state*, which only a provider call can produce. That's why it's robust. Make the enforcement visible in the trace.

**Done when:** a fabricated booking claim is blocked; a real one (with a confirmation ID) passes; both are covered by an eval case.

---

## Step 5 — Action agent: calendar + drafted email + confirmation gate

**Objective:** The risk-tiered action model — low-risk actions taken automatically, high-risk actions drafted for confirmation.

**Build (`backend/app/agents/action.py`, `tools/calendar.py`):**
- **Low-risk, automatic:** generate a calendar hold as an **`.ics`** file (via `icalendar`) — no key, no external write, safe to do automatically.
- **High-risk, gated:** draft the booking summary + itinerary email but **do not send** — surface it for confirmation via a **graph-edge confirmation gate** (a LangGraph interrupt). Sending (or real booking) only proceeds past the gate on explicit user confirmation.

**Key detail:** the confirmation gate is a *graph edge*, not a model decision (Section 12). The high-risk path structurally cannot complete without passing the gate. This risk-tiering — auto for `.ics`, gated for email/booking — is the Responsible-AI story for action-taking.

**Done when:** a calendar `.ics` is auto-created; an itinerary email is drafted and held at the confirmation gate; confirming releases it, declining discards it.

---

## Step 6 — Activities/Booking subagent: restaurants/events search + reservation

**Objective:** The fifth specialist agent — find activities and make a real (mock) restaurant reservation.

**Build (`backend/app/agents/activities_booking.py`, `tools/places.py`, `tools/events.py`):**
- **Restaurant/attraction search** via **Overpass** (OSM, no key, fair-use); **event search** via **Ticketmaster Discovery** + **Eventbrite** (free keys from Phase 0).
- **Restaurant reservation:** route a chosen restaurant through the `mock_provider` → reservation service, returning a real confirmation ID. Same `BookingProvider` contract as Duffel flights.
- **Events are search-only** — surface a deep link; no in-app ticketing (partner-gated, real money).
- Search calls on `small` tier; selection reasoning on `large`.

**Key detail:** the symmetry is the point — a restaurant reservation and a flight booking go through the *same* interface despite one being real-API and one being self-built. That's what makes "swap in OpenTable as a config change" true rather than aspirational.

**Done when:** restaurants and events are found for the destination; a chosen restaurant reserves through the mock service and returns a confirmation ID; events surface as deep links.

---

## Step 7 — Advanced RAG: query decomposition

**Objective:** The multi-passport/multi-city fan-out that powers the full demo narrative — deferred from Phase 2, now built.

**Build (`backend/app/rag/decompose.py`, `orchestrator/nodes/plan.py`):**
- A **decomposition node** (`small` tier) that splits a multi-part query into sub-queries: *"one US passport, one Indian passport → Japan"* → two visa lookups (US→JP, IN→JP); *"Tokyo then Kyoto then Osaka"* → per-city retrieval.
- The RAG agent **fans out** — retrieves per sub-query independently (reusing the Phase 2 pipeline) — and the synthesis step (`large`) **merges** into one grounded, per-traveler/per-city answer.
- Decomposition-aware planning: the plan node accounts for the fan-out when deciding parallelism.

**Key detail:** this is the capability the headline demo query was written around. Decompose → retrieve-per-subquery → merge is the structure; make sure the merge produces a *per-traveler* answer ("US passport: visa-free 90 days; Indian passport: visa required") rather than a mushed-together one. Both the split and the merge are eval-checked in Step 9.

**Done when:** the two-passport Japan query produces two correct, separately-grounded visa answers merged into one per-traveler response.

---

## Step 8 — Advanced RAG: staleness detection + automated re-ingestion

**Objective:** Keep the corpus fresh automatically, and warn when it isn't — using the hooks seeded in Phase 2.

**Build (`backend/app/rag/staleness.py`, `scripts/reingest.py`, `.github/workflows/reingest.yml`):**
- A **scheduled job** re-fetches each source on a per-collection cadence (advisories daily, visa weekly, guides monthly), recomputes the **`content_hash`**, and **re-ingests only changed documents** (re-chunk, re-embed, idempotent upsert), updating `last_verified`.
- Run it via a **GitHub Actions scheduled workflow** (Phase 0 choice) — *not* the web app — so re-ingestion survives free-tier sleep (Challenge #5).
- At query time, if a retrieved chunk is older than its staleness threshold, attach a **"verify before travel"** warning to the answer. Coordinate with the Phase 3 API cache's data-versioned keys so a stale chunk is never served from cache either.

**Key detail:** the job re-ingests *only changed* documents (hash diff), not the whole corpus — that's what makes it cheap enough to run on free GitHub Actions minutes. The "verify before travel" warning is both a freshness signal and a Responsible-AI item.

**Done when:** changing a source document causes the scheduled job to detect the hash diff and re-ingest only that document; a deliberately-aged chunk produces a staleness warning on the answer.

---

## Step 9 — Decomposition + booking-gate eval cases + demo fixtures

**Objective:** Grow the eval harness with Phase 4's surface and capture the full-narrative fixtures.

**Build (`backend/tests/eval/`, `data/fixtures/`):**
- **Decomposition eval cases** (≥90% target): multi-passport and multi-city queries with labeled correct splits and merges.
- **Booking-gate cases:** fabricated-booking-claim blocked; real-confirmation passes (from Step 4).
- **Reservation-semantics unit tests** (from Step 2) folded into CI.
- **Full-narrative fixtures:** capture the entire multi-passport Japan run (decomposition, flight booking, restaurant reservation, calendar, email draft) so the headline demo replays without live calls or rate-limit risk.

**Key detail:** the full-narrative fixture is your demo insurance — a recruiter walkthrough should never depend on a live Duffel sandbox call or the Gemini daily quota holding up. Replayability is the safety net the fixtures have been building toward since Phase 2.

**Done when:** decomposition and booking-gate cases run in CI and gate the build; the full multi-passport narrative replays entirely from fixtures.

---

## Step 10 — Assemble full itinerary + verify the milestone

**Objective:** Compose the complete acting itinerary and verify the full demo narrative.

**Build:** extend the assemble step to fold reservations (with confirmation IDs), the calendar hold, and the drafted email into the itinerary; add *just enough* UI to show reservation confirmations and the action draft (not Phase 6 polish).

**Verify the exit milestone** — the full headline query end-to-end:
1. Multi-passport Japan query → **decomposition** produces correct per-passport visa answers.
2. A flight **books for real** against Duffel (confirmation ID).
3. A chosen restaurant **reserves** through the mock service (confirmation ID).
4. A **calendar `.ics`** hold is auto-created.
5. An itinerary **email is drafted** and held at the confirmation gate.
6. The **no-hallucinated-booking gate** is enforced (no booking claimed without a confirmation ID).
7. The **staleness job** re-ingests a changed document.
8. The whole narrative **replays from fixtures**.

---

## Phase 4 exit checklist

- [ ] `BookingProvider` interface unifies real + mock booking; backend selection is config-driven.
- [ ] Mock reservation service: idempotency keys, confirmation IDs, conflicts, cancellation/rollback — unit-tested.
- [ ] Real Duffel flight booking via the provider (against "Duffel Airways"); cancel works.
- [ ] Real Duffel Stays hotel booking via the same provider (Phase 0 hotels-enabled decision).
- [ ] No-hallucinated-booking gate **enforced and tested**: fabricated claims blocked, real confirmations pass.
- [ ] Action agent: `.ics` auto-created (low-risk); email drafted + held at a graph-edge confirmation gate (high-risk).
- [ ] Activities subagent: Overpass restaurants/attractions + Ticketmaster/Eventbrite events; restaurant reserves via mock provider; events as deep links.
- [ ] Query decomposition: multi-passport/multi-city split → fan-out → per-traveler/per-city merge.
- [ ] Staleness detection + automated re-ingestion via GitHub Actions; only-changed-docs re-ingested; "verify before travel" warning on aged chunks.
- [ ] Decomposition + booking-gate eval cases in the CI gate; reservation-semantics unit tests in CI.
- [ ] Full multi-passport narrative replays from fixtures.
- [ ] Exit milestone verified end-to-end on the live URL.

---

## What is NOT in Phase 4 (deferred)

No real payments / real money (sandbox + mock only — by design), no eval *depth* beyond the cases needed to gate this phase (LLM-judge breadth and the full ~40-case set are Phase 5), no observability dashboards (Phase 5), no CI/CD hardening beyond the existing gate (Phase 5), no frontend polish (Phase 6).

---

## Hand-off to Phase 5

Phase 5 ("Eval Depth, Dashboards & CI/CD") makes the quality and observability story airtight and gates it. The eval harness — seeded in Phase 1 and grown every phase — is now **expanded to the full ~40-case set** (retrieval Hit@k, faithfulness via LLM-judge, decomposition correctness, routing accuracy, guardrail precision/recall, itinerary budget/temporal validity) and split into **deterministic** (always-run, CI-gating) vs. **LLM-as-judge** (sampled). The **CI eval gate** is hardened so a regression below threshold fails the build and blocks deploy. **LangSmith dashboards** surface latency, **token cost by tier**, **cache-hit rate**, **retry rate**, and eval scores over time — the live artifact you screen-share in interviews (mind the free-tier trace cap via the Phase 1 sampling flag). The **GitHub Actions CI/CD** pipeline finalizes lint + test + eval-gate + deploy. Exit milestone: a recruiter opens the URL, runs the full demo, and sees dashboards plus a passing eval gate — with a deliberate regression demonstrably turning the gate red.
