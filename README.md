---
title: WanderWise
emoji: ✈️
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# WanderWise — AI Travel Planning Agent

A production-shaped agentic travel planner: LangGraph orchestrator with 2-tier LLM routing
(Gemini 2.5 Flash-Lite + Flash), streaming SSE API, LangSmith observability, and a CI-gated eval harness.

**Phase 1 skeleton** — weather query end-to-end with full tracing.

## Running locally

```bash
# Backend
uv sync
uv run uvicorn backend.app.main:app --reload

# Frontend (separate terminal)
cd frontend && npm install && npm run dev
```

Copy `.env.example` to `.env` and fill in your `GEMINI_API_KEY` and `LANGSMITH_API_KEY`.

## Running with Docker

```bash
docker compose up --build
```
