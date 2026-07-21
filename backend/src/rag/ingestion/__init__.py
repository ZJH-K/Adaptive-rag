"""Public document ingestion interface."""

from src.rag.ingestion.pipeline import (
    DocumentEmbedder,
    IngestionError,
    IngestionPipeline,
    IngestionResult,
)

__all__ = [
    "DocumentEmbedder",
    "IngestionError",
    "IngestionPipeline",
    "IngestionResult",
]

