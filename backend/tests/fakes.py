"""Deterministic test doubles shared by RAG integration tests."""

from __future__ import annotations


class FakeEmbeddingClient:
    """Generate deterministic vectors without making network requests."""

    def __init__(
        self,
        *,
        vectors_by_token: dict[str, list[float]] | None = None,
        default_vector: list[float] | None = None,
        document_error: Exception | None = None,
        query_error: Exception | None = None,
    ) -> None:
        self.vectors_by_token = vectors_by_token or {}
        self.default_vector = default_vector or [0.0, 0.0, 1.0]
        self.document_error = document_error
        self.query_error = query_error
        self.document_calls: list[list[str]] = []
        self.query_calls: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Record and embed one document batch in input order."""
        self.document_calls.append(list(texts))
        if self.document_error is not None:
            raise self.document_error
        return [self._vector_for(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        """Record and embed one query."""
        self.query_calls.append(text)
        if self.query_error is not None:
            raise self.query_error
        return self._vector_for(text)

    def _vector_for(self, text: str) -> list[float]:
        """Select a configured vector by case-insensitive token matching."""
        normalized = text.casefold()
        for token, vector in self.vectors_by_token.items():
            if token.casefold() in normalized:
                return list(vector)
        return list(self.default_vector)

