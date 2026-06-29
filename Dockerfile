# ---- Stage 1: Build React frontend ----
FROM node:20-slim AS frontend-build

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


# ---- Stage 2: Python backend + built static files ----
FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy dependency manifests + README (hatchling requires README.md at build time)
COPY pyproject.toml uv.lock README.md ./

# Install production dependencies (no dev extras)
RUN uv sync --no-dev --frozen

# Download the spaCy model required by Presidio's NER recogniser
RUN uv run python -m spacy download en_core_web_lg

# Copy backend source
COPY backend/ ./backend/

# Copy built React app to the path FastAPI will serve from
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# HF Spaces requires port 7860
EXPOSE 7860

CMD ["uv", "run", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "7860"]
