"""ONNX embedding wrapper using fastembed.

Uses BAAI/bge-small-en-v1.5 — 384-dim, runs on CPU via ONNX runtime.
No torch or sentence-transformers required (keeps the Docker image small
for HF Spaces deployment).
"""

from fastembed import TextEmbedding

_model: TextEmbedding | None = None

_MODEL_NAME = "BAAI/bge-small-en-v1.5"


def _get_model() -> TextEmbedding:
    global _model
    if _model is None:
        _model = TextEmbedding(_MODEL_NAME)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts. Returns a list of 384-dim vectors."""
    return [vec.tolist() for vec in _get_model().embed(texts)]


def embed_query(query: str) -> list[float]:
    """Embed a single query string."""
    return embed_texts([query])[0]
