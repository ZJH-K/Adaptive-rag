"""Public document retrieval interface."""

from src.rag.retrieval.dense import (
    DenseRetrievalConfigurationError,
    DenseRetrievalInputError,
    DenseRetriever,
    QueryEmbedder,
)

__all__ = [
    "DenseRetrievalConfigurationError",
    "DenseRetrievalInputError",
    "DenseRetriever",
    "QueryEmbedder",
]

