"""Public vector store interface."""

from src.rag.vectorstore.chroma import (
    ChromaVectorStore,
    VectorQueryResult,
    deserialize_chunk_metadata,
    serialize_chunk_metadata,
)
from src.rag.vectorstore.exceptions import (
    VectorStoreConfigurationError,
    VectorStoreError,
    VectorStoreInputError,
    VectorStoreResponseError,
)
from src.rag.retrieval.exceptions import VectorStoreUnavailableError

__all__ = [
    "ChromaVectorStore",
    "VectorQueryResult",
    "VectorStoreConfigurationError",
    "VectorStoreError",
    "VectorStoreInputError",
    "VectorStoreResponseError",
    "VectorStoreUnavailableError",
    "deserialize_chunk_metadata",
    "serialize_chunk_metadata",
]
