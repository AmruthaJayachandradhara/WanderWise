# WanderWise — Phase 6: Frontend Polish, Demo Hardening & Documentation
### Phase Design Document (implementation roadmap, code-light)

| | |
|---|---|
| **Phase** | 6 of 6 — Frontend Polish, Demo Hardening & Documentation |
| **Goal** | Make everything recruiter-ready: a polished UI, a bulletproof demo, and documentation + interview narratives that let the work speak for itself |
| **Duration** | ~Week 5 tail (or a focused few days) |
| **Prereq** | Phase 5 complete — full demo works end-to-end; dashboards live; CI eval-gate hardened; fixtures captured since Phase 2 |
| **Reframing** | Because every prior phase shipped *just-enough UI* and captured fixtures as it went, this is **genuine polish and packaging, not a frontend cliff or a fixture scramble** |
| **Exit milestone** | A recruiter opens the live URL, runs the demo, reads the README, can watch a backup video — and you can walk any component from diagram → code → trace → dashboard |

---

## What Phase 6 is (and isn't)

Phase 6 is packaging. The system is feature-complete after Phase 4 and quality-proven after Phase 5; this phase makes it *land* with a recruiter who has five minutes. Three workstreams: **frontend polish** (turn the incremental just-enough UI into a clean, legible interface), **demo hardening** (make a live walkthrough impossible to break — fixtures, fallback, a recorded video), and **documentation + narrative** (README with architecture diagram and dashboard screenshots, a demo script, and the resume/interview framing that maps each component to a JD ask).

The deliberate payoff of earlier discipline shows here: there's no frontend cliff because each phase added the minimum UI for its capability, and there's no fixture scramble because fixtures have been captured since Phase 2. Phase 6 refines and assembles rather than builds.

What Phase 6 is *not*: no new capability, no architecture changes, no eval/dashboard changes (Phase 5 froze those). If you find yourself adding a feature here, it belongs in the post-MVP backlog, not Phase 6.

---

## Repo structure at the end of Phase 6 (final MVP layout)

Complete root tree, incremental from Phase 5: **(new)** = created this phase, **(extended)** = changed this phase, **(unchanged)** = carried forward. This is the final MVP repo.

```
wanderwise/
├── README.md                        # finalized: overview, architecture, dashboards, demo, setup (extended)
├── .env / .env.example              # (unchanged)
├── .gitignore                       # (unchanged)
├── pyproject.toml                   # (unchanged)
├── Dockerfile                       # (unchanged)
├── docker-compose.yml               # (unchanged)
├── docs/
│   ├── design-doc.md                # (unchanged)
│   ├── decision-log.md              # (unchanged)
│   ├── phase0–5.md                  # (unchanged)
│   ├── phase6.md                    # (new)
│   ├── eval-report.md               # (unchanged)
│   ├── architecture.png             # rendered system diagram (new)
│   ├── demo-script.md               # the recruiter walkthrough script (new)
│   └── interview-prep.md            # narratives mapped to JD asks (new)
├── .github/workflows/               # (unchanged — ci.yml, reingest.yml, eval-nightly.yml)
├── backend/
│   ├── app/
│   │   ├── main.py                  # + demo-mode toggle (serve from fixtures) (extended)
│   │   ├── config.py                # + DEMO_MODE flag (extended)
│   │   └── ... (all subsystems unchanged — frozen after Phase 5)
│   └── tests/                       # (unchanged)
├── frontend/                        # POLISHED (extended)
│   └── src/
│       ├── components/
│       │   ├── Chat.jsx             # streaming chat (polished)
│       │   ├── ItineraryCard.jsx    # day-by-day itinerary (polished/new)
│       │   ├── BudgetBar.jsx        # budget breakdown bar (polished/new)
│       │   ├── Citations.jsx        # inline RAG citations + "verify before travel" (polished/new)
│       │   ├── ReservationCard.jsx  # confirmation IDs for flight/restaurant (polished/new)
│       │   └── ActionDraft.jsx      # email draft + confirm/decline gate UI (polished/new)
│       ├── hooks/                   # (polished)
│       └── api/                     # (polished)
├── data/
│   ├── corpus/                      # (unchanged)
│   └── fixtures/                    # finalized full-narrative demo set (extended)
└── scripts/                         # (unchanged)
```

---

## Build order at a glance

Polish the UI (1–4), harden the demo (5–7), then document and finalize (8–10).

| Step | Builds | Depends on |
|---|---|---|
| 1 | Apply a coherent visual direction (frontend-design pass) | Phase 1–4 UI |
| 2 | Itinerary card + budget bar | Phase 2/4 data shapes |
| 3 | Citations + reservation confirmations + action-draft UI | Phase 4 outputs |
| 4 | Streaming/loading/error states polish | SSE (Phase 1) |
| 5 | Demo mode (serve full narrative from fixtures) | Phase 2/4 fixtures |
| 6 | Demo script | full demo |
| 7 | Recorded demo video | 5, 6 |
| 8 | Architecture diagram | design doc |
| 9 | README finalization | 7, 8, dashboards |
| 10 | Interview prep + resume framing; final verify | all |

---

## Step 1 — Coherent visual direction

**Objective:** Turn the accumulated just-enough UI into something that looks intentional, not templated.

**Build (`frontend/`):**
- Apply a single, restrained visual direction — consistent type scale, spacing, color, and component styling — so the interface reads as designed rather than scaffolded. (This is the one place the **frontend-design** guidance applies: distinctive, intentional, not default-looking.)
- Don't over-design. A clean, legible, fast interface beats a flashy one for a portfolio engineering project — the product is the *system*, and the UI's job is to make the system legible.

**Key detail:** recruiters spend seconds forming a first impression. A coherent, calm interface signals care; a default-bootstrap look undercuts the senior-engineering story the backend earns. Aim for "clearly considered," not "designer portfolio."

**Done when:** the app has one consistent visual language across all screens.

---

## Step 2 — Itinerary card + budget bar

**Objective:** Render the core output — the budget-aware day-by-day itinerary — legibly.

**Build (`ItineraryCard.jsx`, `BudgetBar.jsx`):**
- **Itinerary card:** day-by-day structure with flights, lodging, activities, and weather per day — the assembled output from Phase 2/4.
- **Budget bar:** a visual breakdown of spend vs. the stated budget (the Phase 2 budget reasoning made visible), currency-normalized.

**Key detail:** these render data shapes that already exist — you're presenting Phase 2/4 outputs, not computing anything new. Keep the components dumb (presentation only); all logic stays in the backend.

**Done when:** a completed plan renders as a clean day-by-day itinerary with a budget breakdown.

---

## Step 3 — Citations, reservation confirmations, action-draft UI

**Objective:** Make the trust-and-action signals visible — the things that distinguish this from a chatbot.

**Build (`Citations.jsx`, `ReservationCard.jsx`, `ActionDraft.jsx`):**
- **Citations:** inline source citations on RAG-derived claims (visa/advisory), with `last_verified` dates and the **"verify before travel"** staleness warning surfaced (Phase 4).
- **Reservation cards:** confirmation IDs for the real flight booking and the mock restaurant reservation — the proof that actions actually happened (and the visible counterpart to the no-hallucinated-booking gate).
- **Action draft:** the drafted itinerary email with **confirm / decline** controls — the UI for the Phase 4 confirmation gate.

**Key detail:** these three components *are* the demo's punchline — grounded+cited answers, real confirmations, and gated high-risk actions are the production-shaped behaviors. Make them prominent, not buried. The confirmation IDs especially: they're the visible evidence of the whole booking architecture.

**Done when:** citations, confirmation IDs, and the confirm/decline action draft all render and work end-to-end.

---

## Step 4 — Streaming, loading, and error-state polish

**Objective:** Make the latency-heavy multi-agent flow feel responsive and trustworthy.

**Build (`frontend/src/hooks`, `api`):**
- Polish the **SSE streaming** UX (from Phase 1): show node-level progress ("searching flights…", "checking visa requirements…") so the multi-second multi-agent run feels alive rather than frozen (Challenge #3 mitigation, made visible).
- **Graceful error states:** when a tool degrades (the typed failure modes from Phase 2+), show an honest partial result with a flag — never a spinner that hangs or a raw error.

**Key detail:** graceful degradation in the UI is the FDE story made visible — "it works in a messy real environment." A partial itinerary with "couldn't reach live hotel inventory, showing cached options" reads as production maturity, not failure.

**Done when:** progress streams legibly; an induced tool failure shows a graceful, honest partial result.

---

## Step 5 — Demo mode (serve the full narrative from fixtures)

**Objective:** A live walkthrough that cannot be broken by a rate limit, cold start, or flaky sandbox.

**Build (`backend/app/main.py`, `config.py`, `data/fixtures/`):**
- A **`DEMO_MODE` toggle** that serves the full multi-passport narrative from the captured fixtures (Phase 2/4) instead of live calls — same code path, fixtures swapped in at the tool boundary.
- Finalize the fixture set so the entire headline run (decomposition → flights → reservation → calendar → email draft) replays deterministically.

**Key detail:** this is your demo insurance, and it's nearly free because fixtures have accumulated since Phase 2. The Gemini 1,500 RPD limit and Duffel sandbox flakiness (Challenges #1, #4) can never kill a recruiter walkthrough if demo mode is one toggle away. Keep a *live* mode too — you want to show real calls when conditions allow.

**Done when:** flipping `DEMO_MODE` replays the entire headline narrative with zero live external calls.

---

## Step 6 — Demo script

**Objective:** A tight, rehearsed walkthrough that hits every capability in order.

**Build (`docs/demo-script.md`):**
- A step-by-step script for the headline multi-passport Japan query that surfaces, in sequence: decomposition (two passports), parallel tool execution, routing (tier choices), budget reasoning, a guardrail block (a quick red-team aside), the self-reflection catch (the induced hallucination), real booking + reservation confirmations, the gated email draft, and a pivot to the **LangSmith dashboard** for the cost/cache/retry story.
- Include the **"break the eval gate"** moment from Phase 5 as an optional deep-dive.

**Key detail:** sequence the script so each beat maps to a JD ask (orchestration → cost/latency → reliability → trustworthiness → action-taking). A rehearsed 5-minute path that tells a story beats clicking around hoping the right thing happens.

**Done when:** a written script walks the full capability set in a logical, JD-aligned order.

---

## Step 7 — Recorded demo video

**Objective:** An async artifact recruiters can watch without you present, and a fallback if live ever fails.

**Build:**
- Record the demo-script walkthrough (demo mode for reliability, with a note that live mode works too). Keep it tight — a few minutes.
- Host it (link in the README).

**Key detail:** the video doubles as insurance and reach — it works when you're not in the room and when a live environment misbehaves. It's the final layer of the demo-hardening the fixtures began in Phase 2.

**Done when:** a tight recorded walkthrough exists and is linked.

---

## Step 8 — Architecture diagram

**Objective:** A clear visual of the system — the anchor for any technical conversation.

**Build (`docs/architecture.png`):**
- Render the design doc's system shape (Section 2.1) as a clean diagram: frontend → FastAPI → LangGraph orchestrator (input guardrails → router → plan → parallel agents → observe → output guardrails + self-reflection → assemble → action gates), the five agents and their tools, and the cross-cutting layers (LLM routing, memory, observability/eval, booking abstraction).
- Keep it legible at a glance — the goal is orientation, not exhaustive detail.

**Key detail:** this diagram is what you point at in interviews to walk diagram → code → trace → dashboard. It should make "RAG is one tool among many" visually obvious — the orchestration framing, not a RAG chatbot.

**Done when:** a clean, legible architecture diagram exists for the README and interviews.

---

## Step 9 — README finalization

**Objective:** The front door — a recruiter's first and sometimes only read.

**Build (`README.md`):**
- Lead with a crisp **overview** (what it is, the orchestration framing), the **architecture diagram** (Step 8), the **dashboard screenshots** (Phase 5), the **demo video link** (Step 7), and concise **setup/run instructions** (local + the live URL).
- Summarize the production-shaped capabilities (routing, guardrails, reliability, advanced RAG, memory, real booking + booking abstraction, always-on observability, CI-gated eval) — each in a line, linking to where it lives.
- Follow copyright/attribution hygiene for any third-party data sources (travel.state.gov, CDC, OSM/ODbL attribution for Overpass data).

**Key detail:** structure for skimming — a recruiter forms an impression from the README's first screen. Lead with the diagram and the demo link; depth is one scroll down. The README is a portfolio artifact in its own right.

**Done when:** the README gives overview, architecture, dashboards, demo, and setup, skimmable in under a minute.

---

## Step 10 — Interview prep + resume framing; final verify

**Objective:** The narrative layer — turn the system into stories that map to what these roles probe, and do the final end-to-end check.

**Build (`docs/interview-prep.md`):**
- Map each component to a JD ask (from the design doc Section 15): **orchestration** ("RAG is one tool among many"), **cost/latency** (routing + cost-by-tier dashboard), **reliability** (induce a hallucination, show the self-reflection loop catch it), **trustworthiness** (CI eval-gate blocking deploys; staleness warnings), **FDE-specific** (broad tool integration, graceful degradation everywhere, a live fault-tolerant deployment).
- Finalize the **resume line** (design doc Section 15) and rehearse the "principled call where no API exists" story (mock reservation service behind the `BookingProvider` contract).

**Verify the exit milestone:**
1. A recruiter (or a stand-in) opens the **live URL** and runs the demo from the script.
2. The **README** orients them — diagram, dashboards, demo video, setup.
3. The **backup video** plays if live conditions are poor.
4. You can walk any component **diagram → code → trace → dashboard** on request.
5. **Demo mode** guarantees the walkthrough survives rate limits / cold starts.

---

## Phase 6 exit checklist

- [ ] Coherent visual direction applied across the whole UI.
- [ ] Itinerary card + budget bar render the core output cleanly.
- [ ] Citations (with staleness warnings), reservation confirmations (IDs), and the confirm/decline action draft all work.
- [ ] Streaming progress + graceful error/partial states polished.
- [ ] `DEMO_MODE` replays the full headline narrative with zero live calls; live mode also works.
- [ ] Demo script walks the full capability set in JD-aligned order.
- [ ] Recorded demo video exists and is linked.
- [ ] Architecture diagram rendered and legible.
- [ ] README finalized: overview, diagram, dashboard screenshots, demo video, setup — skimmable.
- [ ] Interview-prep doc maps components to JD asks; resume line finalized.
- [ ] Exit milestone verified — recruiter-ready, walkable diagram → code → trace → dashboard.

---

## What is NOT in Phase 6 (and what comes after)

No new capability, no architecture or eval/dashboard changes. Anything tempting here goes to the **post-MVP backlog**, which the design doc already scopes: multi-user auth & persistence (the schema is ready — Phase 1 threaded `user_id` throughout), the **FinTravel** financial extension (Plaid, points optimization, insurance arbitration), real payments, voice/multimodal input, 3-tier routing, Supabase for free auth/multi-user, real event ticketing (currently search-only/deep-link), and Sabre's MCP server behind the existing `BookingProvider` seam.

---

## Project complete

At the end of Phase 6, WanderWise is a deployed, production-shaped agentic AI system with: a LangGraph orchestrator, 2-tier LLM routing, input/output guardrails, infra + self-reflection reliability, an advanced RAG subsystem (hybrid retrieval, decomposition, staleness-triggered re-ingestion), short/long-term memory + semantic caching, real flight booking via Duffel and a provider-agnostic booking abstraction, always-on tracing, a CI-gated eval suite, live dashboards, and a hardened, recruiter-ready demo. Every capability maps to an AI Engineer / FDE interview ask, and every claim is backed by something you can show: code, a trace, a dashboard, or a passing gate.
