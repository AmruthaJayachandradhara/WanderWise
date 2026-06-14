# Phase 0 Decision Log

## Pre-resolved Decisions
| # | Decision | Locked choice |
|---|---|---|
| 1 | Booking stack | Duffel (real flight sandbox) + self-built mock reservation service, both behind one `BookingProvider` contract |
| 6 | LLM provider | Google Gemini API (AI Studio free tier): Flash-Lite (small) + Flash (large) + Gemini Embedding; Groq wired as fallback |

## Locked Decisions from Phase 0

| # | Decision | **Locked choice** | Notes / rationale |
|---|---|---|---|
| 2 | Hotels search vs. book | **Enable booking** | Same Duffel token; adds a second real booking type to the demo for near-zero extra effort |
| 3 | Vector DB | **Qdrant** | Chose the stronger prod story over Chroma's faster start; Qdrant has **native hybrid (vector + sparse/BM25) search**, which aligns directly with the Phase 2 hybrid-retrieval requirement |
| 4 | Cache / session store | **Redis (Upstash free tier)** | Serverless, persists, no always-on box — good for both semantic + API cache and session store on a single-container HF Spaces deploy |
| 5 | Guardrails framework | **Custom via LangChain middleware** | Most transparent; can explain every check in interviews |
| 7 | Re-ingestion scheduler | **GitHub Actions scheduled workflow** | Free, external, survives free-tier sleep |
| 8 | Deployment target | **Hugging Face Spaces** | ML-friendly, Docker support, single-container model fits the "serve React static from FastAPI" single deployable |
| 9 | Demo countries | **50-country curated list** | Expanded from ~15–25 to cover travel-warning use cases (varying advisory levels), major economies/superpowers (incl. China, Russia), and Middle East destinations alongside classic tourist countries |
| 10 | Embeddings | **Gemini Embedding** | Same API key/SDK, generous free limits (10M tokens/min); `bge-small-en` noted as offline fallback |

## Development Environment & Toolchain

### Toolchain Versions
| Tool | Expected Version |
|---|---|
| **Python** | `3.12` |
| **uv** | `latest` |
| **Node.js** | `20 LTS+` |
| **Docker + Docker Compose** | `latest` |
| **Git** | `latest` |

### Branch & Workflow Strategy
**Trunk-based with short-lived feature branches.**
- Main branch (`main`) is always deployable.
- Develop on phase/sub-step branches (e.g., `phase-1/skeleton`) and merge via Pull Requests.
- CI pipeline pass required before merge to `main`.

