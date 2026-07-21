"""Public embedding client interface."""

from src.rag.embeddings.client import (
    EmbeddingAPIClient,
    EmbeddingAPIResource,
    EmbeddingClient,
)
from src.rag.embeddings.exceptions import (
    EmbeddingConfigurationError,
    EmbeddingError,
    EmbeddingInputError,
    EmbeddingRequestError,
    EmbeddingResponseError,
)

__all__ = [
    "EmbeddingAPIClient",
    "EmbeddingAPIResource",
    "EmbeddingClient",
    "EmbeddingConfigurationError",
    "EmbeddingError",
    "EmbeddingInputError",
    "EmbeddingRequestError",
    "EmbeddingResponseError",
]

