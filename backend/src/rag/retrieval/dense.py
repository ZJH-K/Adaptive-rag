"""Dense vector retrieval over pre-ingested Chroma chunks."""

from __future__ import annotations

from typing import Protocol

from src.rag.embeddings.exceptions import EmbeddingRequestError
from src.rag.retrieval.exceptions import (
    DenseRetrievalUnavailableError,
    VectorStoreUnavailableError,
)
from src.rag.schemas import SearchHit
from src.rag.vectorstore.chroma import ChromaVectorStore


class QueryEmbedder(Protocol):
    """Query embedding capability required by dense retrieval."""

    def embed_query(self, text: str) -> list[float]:
        """Return one vector for a retrieval query."""
        ...


class DenseRetrievalConfigurationError(ValueError):
    """Raised when dense retrieval parameters are invalid."""


class DenseRetrievalInputError(ValueError):
    """Raised when a retrieval query is blank or invalid."""


class DenseRetriever:
    """Embed a query and map cosine-distance results into SearchHit models."""

    def __init__(
        self,
        embedding_client: QueryEmbedder,
        vector_store: ChromaVectorStore,
        *,
        top_k: int = 20,
    ) -> None:
        """Configure the retriever's fixed maximum result count."""
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k <= 0:
            raise DenseRetrievalConfigurationError(
                "DenseRetriever top_k must be a positive integer"
            )
        self.embedding_client = embedding_client
        self.vector_store = vector_store
        self.top_k = top_k

    def retrieve(
        self,
        query: str,
        *,
        top_n: int | None = None,
    ) -> list[SearchHit]:
        """Return dense results using an optional request-level result limit."""
        if not isinstance(query, str) or not query.strip():
            raise DenseRetrievalInputError("Query must be a non-empty string")
        effective_top_n = self.top_k if top_n is None else top_n
        if (
            not isinstance(effective_top_n, int)
            or isinstance(effective_top_n, bool)
            or effective_top_n <= 0
        ):
            raise DenseRetrievalConfigurationError(
                "DenseRetriever top_n must be a positive integer"
            )

        try:
            query_embedding = self.embedding_client.embed_query(query)
        except EmbeddingRequestError as exc:
            raise DenseRetrievalUnavailableError(
                code="embedding_request_failed",
            ) from exc
        try:
            results = self.vector_store.query_by_vector(
                query_embedding,
                top_k=effective_top_n,
            )
        except VectorStoreUnavailableError as exc:
            raise DenseRetrievalUnavailableError(
                code=exc.code,
                safe_message=exc.safe_message,
            ) from exc
        return [
            SearchHit(
                chunk_id=result.chunk_id,
                text=result.text,
                metadata=result.metadata,
                dense_score=1.0 - result.distance,
            )
            for result in results
        ]
