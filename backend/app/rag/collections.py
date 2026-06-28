"""Qdrant collection configs and chunking strategies for the RAG pipeline."""

from dataclasses import dataclass


@dataclass
class CollectionConfig:
    strategy: str       # "whole_document" | "sliding_window"
    chunk_size: int = 300
    overlap: float = 0.10
    vector_size: int = 384


COLLECTION_CONFIGS: dict[str, CollectionConfig] = {
    "visa_entry": CollectionConfig("whole_document"),
    "advisories": CollectionConfig("sliding_window", chunk_size=200, overlap=0.10),
    "destination_guides": CollectionConfig("sliding_window", chunk_size=300, overlap=0.15),
}


def chunk_text(text: str, config: CollectionConfig) -> list[str]:
    """Split text into chunks according to the collection's strategy."""
    if config.strategy == "whole_document":
        return [text.strip()] if text.strip() else []

    words = text.split()
    if not words:
        return []

    size = config.chunk_size
    step = max(1, int(size * (1 - config.overlap)))
    chunks = []
    for i in range(0, len(words), step):
        chunk = " ".join(words[i : i + size])
        if chunk:
            chunks.append(chunk)
        if i + size >= len(words):
            break
    return chunks
