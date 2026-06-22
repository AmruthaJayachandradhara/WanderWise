"""FastAPI application — entry point for the WanderWise backend.

Routes:
  GET  /health      — liveness check (used by HF Spaces + CI)
  POST /api/chat    — streams graph progress + final answer via SSE
  GET  /            — serves the built React app (static files)

The chat endpoint streams one SSE event per graph node (progress) plus a
final "done" event carrying the assembled summary and tier metadata.
Streaming is wired now even though Phase 1 is fast — later phases stack
tools, guardrails, and retries, and streaming partials hides that latency.
"""

import json
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from backend.app.config import settings
from backend.app.logging_config import setup_logging
from backend.app.observability.tracing import init_tracing
from backend.app.orchestrator.graph import graph

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.LOG_LEVEL)
    init_tracing()
    logger.info("WanderWise backend starting on port %d", settings.APP_PORT)
    yield
    logger.info("WanderWise backend shutting down")


app = FastAPI(title="WanderWise", version="0.1.0", lifespan=lifespan)


# --- Health check ---

@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


# --- Chat endpoint ---

class ChatRequest(BaseModel):
    query: str
    user_id: str | None = None  # defaults to demo user; auth-ready seam


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """Stream graph progress events followed by a final 'done' event."""
    user_id = request.user_id or settings.DEMO_USER_ID

    async def event_stream() -> AsyncGenerator[dict, None]:
        initial_state = {
            "user_id": user_id,
            "query": request.query,
        }

        # Accumulate state updates so we can emit the final "done" event
        # without running the graph a second time.
        accumulated: dict = {}

        # stream_mode="updates" yields {node_name: {key: value, ...}} per step
        async for chunk in graph.astream(initial_state, stream_mode="updates"):
            for node_name, node_output in chunk.items():
                if node_output:
                    accumulated.update(node_output)
                    yield {
                        "event": "progress",
                        "data": json.dumps({"node": node_name, "status": "done"}),
                    }

        yield {
            "event": "done",
            "data": json.dumps({
                "summary": accumulated.get("summary", ""),
                "location": accumulated.get("location", ""),
                "router_tier": accumulated.get("router_tier", ""),
                "assemble_tier": accumulated.get("assemble_tier", ""),
                "degraded": accumulated.get("degraded", False),
            }),
        }

    return EventSourceResponse(event_stream())


# --- Serve React static build ---
# Mounted last so API routes take precedence.
# frontend/dist is built by the Dockerfile; in dev the React dev server handles /
_dist = settings.FRONTEND_DIST_DIR
if os.path.isdir(_dist):
    app.mount("/", StaticFiles(directory=_dist, html=True), name="static")
    logger.info("Serving frontend from %s", _dist)
