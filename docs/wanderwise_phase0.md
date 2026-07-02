# WanderWise — Phase 0: Decisions, Accounts & Dev Environment
### Phase Design Document (build plan, no application code)

| | |
|---|---|
| **Phase** | 0 of 6 — Foundation prerequisites |
| **Goal** | Remove every stall risk before Week 1: lock all open decisions, provision all accounts/keys, stand up the dev environment |
| **Duration** | ~½ to 1 day (decisions + signups + tooling) |
| **Produces** | **Zero running application code.** Decisions, credentials, an empty repo, and a verified toolchain only |
| **Exit gate** | All 10 open decisions logged; all API keys provisioned and smoke-tested; repo initialized with toolchain verified |
| **Hard rule** | The moment you write a config loader, an agent, or any app logic — that's Phase 1, not Phase 0 |

---

## Why Phase 0 exists

Mid-build stalls almost always trace back to a decision you didn't make or a credential you didn't have. If you're three days into Phase 1 and discover you never picked a vector DB, or that your Duffel key isn't activated, you lose momentum at the worst time. Phase 0 front-loads all of that into a single, cheap block of work so that **Phase 1 never blocks on a signup or an unresolved choice.**

The discipline that keeps this phase from bloating: Phase 0 produces no application code. If you're writing Python, you've drifted into Phase 1.

---

## Step 1 — Lock the 10 open decisions

Your design doc (Section 16) lists 10 decisions as "your call before Week 1." Two are already resolved (booking stack, LLM provider). Below are the remaining eight with a one-line tradeoff and a recommended default so you can lock fast. **Fill in the Decision Log at the end of this step — that log becomes the source of truth your `config.py` will encode in Phase 1.**

### 1.1 Decisions already resolved (carry forward, no action)

| # | Decision | Locked choice |
|---|---|---|
| 1 | Booking stack | Duffel (real flight sandbox) + self-built mock reservation service, both behind one `BookingProvider` contract |
| 6 | LLM provider | Google Gemini API (AI Studio free tier): Flash-Lite (small) + Flash (large) + Gemini Embedding; Groq wired as fallback |

### 1.2 Decisions to make now — **now locked** (recommendations kept for rationale)

The table below shows the original options and tradeoffs; the **Locked** column records the final call (also captured in the decision log at 1.3).

| # | Decision | Options | One-line tradeoff | **Locked** |
|---|---|---|---|---|
| 2 | **Hotels: search-only vs. book** | Search-only · Enable booking | Duffel Stays makes booking near-free effort and adds a second real booking type to the demo | **Enable booking** |
| 3 | **Vector DB** | Chroma · Qdrant · pgvector | Chroma = zero infra, fastest start; Qdrant = stronger prod story + native hybrid search | **Qdrant** (native hybrid search aligns with Phase 2's vector+BM25 requirement) |
| 4 | **Cache / session store** | Upstash Redis · in-memory · GPTCache | Upstash = serverless, persists, no always-on box; in-memory = simplest but volatile | **Redis (Upstash)** for cache + session; custom Redis-backed semantic cache |
| 5 | **Guardrails framework** | Custom via LangChain middleware · Guardrails AI · NeMo | Custom = most transparent + best learning; frameworks = faster but more opaque | **Custom via middleware** |
| 7 | **Re-ingestion scheduler** | GitHub Actions workflow · APScheduler · cron | GH Actions = free, external, survives free-tier sleep; APScheduler = dies with the app | **GitHub Actions scheduled workflow** |
| 8 | **Deployment target** | Render · HF Spaces · Railway | Render = all-rounder w/ managed Postgres; HF = ML-friendly single container; Railway = easy multi-service | **Hugging Face Spaces** (single-container fit) |
| 9 | **Demo countries** | Drive from demo queries | Depth where demoed beats breadth across 195 | **50-country list** (see 1.4) — covers travel-warning use cases + major economies + Middle East |
| 10 | **Embeddings** | Gemini Embedding · `bge-small-en` (local) | Gemini = same key/SDK, generous free limits; bge = fully local, no quota | **Gemini Embedding** (`bge-small-en` as offline fallback) |

### 1.3 Decision Log (fill this in — it drives Phase 1 config)

> This is the locked decision log — copy it into `docs/decision-log.md` as the runtime config source of truth. All eight are now decided.

| # | Decision | **Locked choice** | Notes / rationale |
|---|---|---|---|
| 2 | Hotels search vs. book | **Enable booking** | Same Duffel token; adds a second real booking type to the demo for near-zero extra effort |
| 3 | Vector DB | **Qdrant** | Chose the stronger prod story over Chroma's faster start; Qdrant has **native hybrid (vector + sparse/BM25) search**, which aligns directly with the Phase 2 hybrid-retrieval requirement |
| 4 | Cache / session store | **Redis (Upstash free tier)** | Serverless, persists, no always-on box — good for both semantic + API cache and session store on a single-container HF Spaces deploy |
| 5 | Guardrails framework | **Custom via LangChain middleware** | Most transparent; can explain every check in interviews |
| 7 | Re-ingestion scheduler | **GitHub Actions scheduled workflow** | Free, external, survives free-tier sleep |
| 8 | Deployment target | **Hugging Face Spaces** | ML-friendly, Docker support, single-container model fits the "serve React static from FastAPI" single deployable |
| 9 | Demo countries | **50-country curated list** (see 1.4 below) | Expanded from ~15–25 to cover travel-warning use cases (varying advisory levels), major economies/superpowers (incl. China, Russia), and Middle East destinations alongside classic tourist countries |
| 10 | Embeddings | **Gemini Embedding** | Same API key/SDK, generous free limits (10M tokens/min); `bge-small-en` noted as offline fallback |

### 1.4 Demo country list (50)

Curated to exercise every RAG use case — not just visa-free tourist destinations, but **varying travel-advisory levels** (the warning use case), major economies/superpowers, and Middle East coverage. The multi-passport demo (US + India → Japan) is fully covered. Curate depth here; the remaining ~145 countries are a backlog item.

| Region | Countries |
|---|---|
| **Europe** | France, Italy, Spain, United Kingdom, Germany, Greece, Portugal, Netherlands, Switzerland, Austria, Ireland, Croatia, Iceland, Czech Republic |
| **Russia & Eurasia** | Russia |
| **Asia** | Japan, China, India, Thailand, Vietnam, South Korea, Singapore, Indonesia, Malaysia, Philippines, Sri Lanka, Nepal |
| **Middle East** | United Arab Emirates, Saudi Arabia, Qatar, Israel, Jordan, Egypt, Turkey, Oman |
| **Americas** | United States, Canada, Mexico, Brazil, Argentina, Peru, Colombia, Costa Rica |
| **Oceania** | Australia, New Zealand |
| **Africa** | South Africa, Morocco, Kenya, Tanzania |
| **Indian Ocean** | Maldives |

*Coverage rationale:* superpowers/big economies (US, China, Russia, Japan, Germany, India, UK, France); travel-warning spread (Russia, China, Egypt, Turkey, Mexico, Colombia, Israel, Saudi Arabia, Kenya, Tanzania carry varying US State Dept advisory levels — ideal for demoing the advisory/"verify before travel" path); Middle East breadth (8 countries); and classic high-volume tourist destinations across every region.

> **Scope note:** corpus ingestion is automated (scrape `travel.state.gov` + CDC per country → embed → upsert), so 50 vs. 25 countries is low marginal *effort* — mostly more pages to scrape and embed (well within Gemini Embedding's free limits). Budget a little extra Phase 2 ingestion time and ensure the eval set samples a few higher-advisory countries to prove the warning path.

**Step 1 exit:** all eight decisions locked (above); the 50-country list recorded.

---

## Step 2 — Provision all accounts & API keys

Provision everything up front, even the instant ones, so Phase 1 never blocks. All MVP credentials are free and instant-issue — there's no lead-time dependency (Sabre, which needed 7–21 days, is out of scope). As you collect each secret, drop it into a **local `.env` file that is never committed** (you'll create `.env.example` as the committed template in Step 3).

> **Note on limits:** the free-tier numbers below are from your design doc's June 2026 research. Free tiers shift — confirm the current limits on each provider's dashboard at signup and update your doc if they've changed.

### 2.1 Credentials to obtain

| Service | What you need | Where | Free limit (per doc) | Env var (suggested) |
|---|---|---|---|---|
| **Google AI Studio (Gemini)** | API key | `aistudio.google.com/apikey` | 1,500 RPD shared, 1M TPM; covers both tiers + embeddings | `GEMINI_API_KEY` |
| **Duffel** | API key (test/sandbox) | Duffel dashboard → Developers → Access tokens | Unlimited sandbox; "Duffel Airways" test airline | `DUFFEL_API_KEY` |
| **Ticketmaster Discovery** | API key | Ticketmaster developer portal | 5,000 calls/day | `TICKETMASTER_API_KEY` |
| **Eventbrite** | OAuth token | Eventbrite account → API keys | 1,000 calls/hr | `EVENTBRITE_TOKEN` |
| **OpenRouteService** | API key | ORS dashboard | 2,000 calls/day | `ORS_API_KEY` |
| **LangSmith** | API key | `smith.langchain.com` → Settings → API Keys | Free Developer tier (single-seat; monthly trace cap) | `LANGSMITH_API_KEY`, `LANGSMITH_TRACING`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT` |
| **Upstash Redis** | REST URL + token | Upstash console → create Redis DB | Free tier (request caps) | `UPSTASH_REDIS_URL`, `UPSTASH_REDIS_TOKEN` |
| **Qdrant Cloud** | API key + cluster URL | `cloud.qdrant.io` → create free cluster | Free tier (~1GB cluster, no card) | `QDRANT_URL`, `QDRANT_API_KEY` |
| **Groq (fallback)** | API key | Groq console | 1,000 RPD, OpenAI-compatible | `GROQ_API_KEY` |
| **Hugging Face** | Account + token (Spaces) | `huggingface.co` → Settings → Access Tokens | Free Spaces (Docker SDK) | `HF_TOKEN` (for deploy/push) |
| **GitHub** | Repo + Actions enabled | github.com | Free for public repos | n/a |

### 2.2 No-key services (note them, nothing to provision)

These need no signup — listed so you know they're ready: **Open-Meteo** (weather), **Nominatim** (geocoding, 1 req/sec — respect the rate limit and set a descriptive User-Agent), **Overpass** (OSM places, fair-use), **Frankfurter** (FX), **REST Countries** (ISO metadata). The `.ics` calendar action is a local Python library (`icalendar`), no key.

> **Qdrant local vs. cloud:** for local dev you can run Qdrant in Docker (no key) via docker-compose; the Qdrant Cloud free cluster (keyed, above) is the cleaner fit for the single-container HF Spaces deploy so the app doesn't have to host the vector DB itself. Use the same `qdrant-client` for both — local URL in dev, cloud URL + key in prod, switched by config.

**Step 2 exit:** every keyed service above has a working credential pasted into your local `.env`, and you've confirmed which platform account you created for deployment.

---

## Step 3 — Stand up the dev environment

This is tooling and repo skeleton only — no application logic. The goal is a repo you can clone tomorrow and immediately start Phase 1 in.

### 3.1 Toolchain (install + pin versions)

| Tool | Version | Why |
|---|---|---|
| **Python** | 3.12 | Compatible with current Gemini SDK + LangGraph; stable |
| **uv** | latest | Fast, reproducible Python dependency + venv management (recommended over pip/poetry) |
| **Node.js** | 20 LTS+ | React/Vite frontend |
| **Docker + Docker Compose** | latest | Local backend + vector DB + redis parity with deploy |
| **Git** | latest | Version control |

Record exact installed versions in `docs/decision-log.md` so the environment is reproducible.

### 3.2 Initialize the repository

1. Create the GitHub repo (public — needed for free GitHub Actions minutes and a visible portfolio artifact).
2. Initialize locally with a sensible `.gitignore` (must exclude `.env`, `__pycache__/`, `node_modules/`, vector DB files, `.venv/`).
3. Create the **committed** `.env.example` listing every env var name from Step 2 with placeholder values (no real secrets). This is the template; the real `.env` stays local and ignored.
4. Create a minimal `docs/` folder and drop in: this Phase 0 doc, the main design doc, and your `decision-log.md`.
5. Lay down empty top-level directories matching the repo structure from the design doc (`backend/`, `frontend/`, `data/`, `scripts/`, `.github/workflows/`) so Phase 1 files have a home. Leave them empty or with a `.gitkeep` — no code.

### 3.3 Branch & workflow strategy

Pick and document a simple strategy now so you're not improvising later:

- **Trunk-based with short-lived feature branches** is the right fit for a solo project: `main` is always deployable; each phase (or sub-step) gets a branch like `phase-1/skeleton`, merged via PR (even solo — the PR gives you a CI surface and a clean history for interviews).
- Protect `main`: require the CI check to pass before merge (you'll add the CI workflow in Phase 1; the rule can be set now).

### 3.4 Secrets hygiene (set up the guardrail before any secret exists in history)

1. Install **pre-commit** and add a secret scanner (`gitleaks` or `detect-secrets`) as a hook so a key can never be accidentally committed.
2. Run the scanner once against the empty repo to confirm the hook fires.
3. Confirm `.env` is in `.gitignore` *before* you ever save real keys into it locally.

**Step 3 exit:** repo is cloned-and-ready — toolchain installed and version-pinned, `.gitignore` + `.env.example` committed, empty directory skeleton in place, branch strategy documented, pre-commit secret scanner active.

---

## Step 4 — Smoke-test every credential (verification, not app code)

Before declaring Phase 0 done, confirm each key actually works. These are throwaway one-liners (curl or the provider's CLI/SDK in a REPL) — **not** application code, just "does this credential authenticate." Catching a dead key now saves a confusing debugging session in Phase 1.

Minimum checks:

- **Gemini** — one trivial completion call against Flash-Lite and one against Flash; confirm both return 200 and that embeddings respond. Confirms the single key covers all three uses.
- **Duffel** — one offer-request (search) call in sandbox; confirm "Duffel Airways" appears. Confirms sandbox is live.
- **Ticketmaster / Eventbrite / ORS** — one minimal authenticated GET each; confirm 200, not 401.
- **LangSmith** — set `LANGSMITH_TRACING=true` plus the API key and run one traced call; confirm the trace appears in your LangSmith project. Confirms tracing will work from Phase 1's first node.
- **Upstash** — one `SET`/`GET` round-trip via the REST API; confirm it persists.
- **Qdrant Cloud** — one client connection + create-a-test-collection call; confirm it returns and the collection lists. Confirms the cluster is live and the key authenticates.
- **Groq** — one completion call; confirm the fallback provider authenticates.
- **Hugging Face** — confirm the token authenticates (e.g., `huggingface-cli whoami`) and that you can create an empty Space. Confirms the Phase 1 deploy target is ready.
- **No-key services** — one GET each to Open-Meteo, Nominatim, Overpass, Frankfurter, REST Countries; confirm reachable (and that Nominatim accepts your User-Agent).

Record results in a simple checklist in `decision-log.md` (service → ✅/❌ → date).

**Step 4 exit:** every credential returns a successful authenticated response, logged.

---

## Phase 0 exit checklist

Phase 0 is complete — and Phase 1 is unblocked — when **all** of these are true:

- [ ] All 8 open decisions recorded in the Decision Log with final choices.
- [ ] All keyed services provisioned; secrets in a local, git-ignored `.env`.
- [ ] `.env.example` committed with every var name (no real values).
- [ ] Toolchain installed and versions pinned in `decision-log.md`.
- [ ] GitHub repo created (public), `.gitignore` correct, empty directory skeleton committed.
- [ ] Branch strategy documented; `main` protection rule set.
- [ ] Pre-commit secret scanner active and verified.
- [ ] Every credential smoke-tested with a logged ✅.

---

## Explicitly NOT in Phase 0 (these are Phase 1)

To keep the boundary sharp — do **not** do any of the following in Phase 0:

- Writing `config.py` or any config-loading logic.
- Scaffolding FastAPI, the LangGraph skeleton, or the LLM abstraction layer.
- Building the React app (beyond `npm create vite` is fine as toolchain verification, but no components).
- Writing the CI workflow YAML (the *rule* requiring CI can be set; the workflow itself is Phase 1).
- Any agent, tool wrapper, or ingestion code.

If you find yourself doing any of these, you've started Phase 1 — which is fine, just know you've crossed the line.

---

## Hand-off to Phase 1

Phase 1 ("Foundation & Skeleton") begins from a clean, fully-credentialed repo. Its first acts will be: encode the Decision Log into `config.py`, build the 2-tier LLM abstraction (Gemini primary, Groq fallback), wire LangSmith tracing into the first node, stand up the FastAPI streaming endpoint and a minimal React chat UI, build the LangGraph skeleton with one agent (Weather), seed the empty eval harness + CI gate stub, and deploy the skeleton to your chosen platform — proving the full path works end-to-end before any real complexity lands.

updating keys
