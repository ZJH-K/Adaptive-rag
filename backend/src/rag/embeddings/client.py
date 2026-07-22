"""OpenAI-compatible client for document and query embeddings."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from openai import APIError, OpenAI

from src.config import Settings
from src.rag.embeddings.exceptions import (
    EmbeddingConfigurationError,
    EmbeddingInputError,
    EmbeddingRequestError,
    EmbeddingResponseError,
)


class EmbeddingAPIResource(Protocol):
    """Minimal embeddings endpoint required from an injected API client."""

    def create(
        self,
        *,
        input: list[str],
        model: str,
        dimensions: int,
    ) -> Any:
        """Create embeddings for one ordered batch."""
        ...


class EmbeddingAPIClient(Protocol):
    """Minimal protocol implemented by the OpenAI client and test fakes."""

    embeddings: EmbeddingAPIResource


class EmbeddingClient:
    """Generate validated embeddings through an OpenAI-compatible API."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        dimension: int | None = None,
        batch_size: int | None = None,
        timeout_seconds: float | None = None,
        api_client: EmbeddingAPIClient | None = None,
    ) -> None:
        """Initialize configuration without making a network connection."""
        configured = settings or Settings()
        self.base_url = (
            configured.embedding_base_url if base_url is None else base_url
        )
        self.api_key = configured.embedding_api_key if api_key is None else api_key
        self.model = configured.embedding_model if model is None else model
        self.dimension = (
            configured.embedding_dimension if dimension is None else dimension
        )
        self.batch_size = (
            configured.embedding_batch_size if batch_size is None else batch_size
        )
        self.timeout_seconds = (
            configured.embedding_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        self._api_client = api_client
        self._validate_configuration()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed documents in ordered batches and preserve input order."""
        if not texts:
            return []
        self._validate_texts(texts)
        client = self._get_api_client()

        embeddings: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            embeddings.extend(self._embed_batch(client, batch))
        return embeddings

    def embed_query(self, text: str) -> list[float]:
        """Embed a single non-blank retrieval query."""
        if not isinstance(text, str) or not text.strip():
            raise EmbeddingInputError("Query text must be a non-empty string")
        return self.embed_documents([text])[0]

    def _validate_configuration(self) -> None:
        """Validate all constructor configuration except the optional API key."""
        if not isinstance(self.base_url, str) or not self.base_url.strip():
            raise EmbeddingConfigurationError("Embedding base URL is required")
        if not isinstance(self.model, str) or not self.model.strip():
            raise EmbeddingConfigurationError("Embedding model is required")
        if not isinstance(self.dimension, int) or isinstance(self.dimension, bool):
            raise EmbeddingConfigurationError(
                "Embedding dimension must be a positive integer"
            )
        if self.dimension <= 0:
            raise EmbeddingConfigurationError(
                "Embedding dimension must be a positive integer"
            )
        if not isinstance(self.batch_size, int) or isinstance(self.batch_size, bool):
            raise EmbeddingConfigurationError(
                "Embedding batch size must be a positive integer"
            )
        if self.batch_size <= 0:
            raise EmbeddingConfigurationError(
                "Embedding batch size must be a positive integer"
            )
        if (
            not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds <= 0
        ):
            raise EmbeddingConfigurationError(
                "Embedding timeout must be greater than zero"
            )

    def _validate_texts(self, texts: list[str]) -> None:
        """Reject blank or non-string document inputs before calling the API."""
        for index, text in enumerate(texts):
            if not isinstance(text, str) or not text.strip():
                raise EmbeddingInputError(
                    f"Document text at index {index} must be a non-empty string"
                )

    def _get_api_client(self) -> EmbeddingAPIClient:
        """Validate the API key and lazily create the underlying client."""
        if not isinstance(self.api_key, str) or not self.api_key.strip():
            raise EmbeddingConfigurationError("Embedding API key is required")
        if self._api_client is None:
            self._api_client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=float(self.timeout_seconds),
                max_retries=0,
            )
        return self._api_client

    def _embed_batch(
        self,
        client: EmbeddingAPIClient,
        batch: list[str],
    ) -> list[list[float]]:
        """Request and validate one embedding batch."""
        try:
            response = client.embeddings.create(
                input=batch,
                model=self.model,
                dimensions=self.dimension,
            )
        except APIError as exc:
            error_type = type(exc).__name__
            raise EmbeddingRequestError(
                f"Embedding request failed ({error_type})"
            ) from exc

        data = getattr(response, "data", None)
        if not isinstance(data, Sequence) or isinstance(data, (str, bytes)):
            raise EmbeddingResponseError("Embedding response has no valid data list")
        if len(data) != len(batch):
            raise EmbeddingResponseError(
                "Embedding response count does not match request count: "
                f"expected {len(batch)}, got {len(data)}"
            )

        indexed_items: list[tuple[int, Any]] = []
        for item in data:
            index = getattr(item, "index", None)
            if not isinstance(index, int) or isinstance(index, bool):
                raise EmbeddingResponseError(
                    "Embedding response item has an invalid index"
                )
            indexed_items.append((index, item))

        expected_indices = list(range(len(batch)))
        actual_indices = sorted(index for index, _ in indexed_items)
        if actual_indices != expected_indices:
            raise EmbeddingResponseError(
                "Embedding response indices do not match request order"
            )

        ordered_items = [item for _, item in sorted(indexed_items)]
        return [self._validate_vector(item) for item in ordered_items]

    def _validate_vector(self, item: Any) -> list[float]:
        """Validate and normalize one response vector."""
        embedding = getattr(item, "embedding", None)
        if not isinstance(embedding, Sequence) or isinstance(
            embedding, (str, bytes)
        ):
            raise EmbeddingResponseError(
                "Embedding response item has no valid vector"
            )
        if len(embedding) != self.dimension:
            raise EmbeddingResponseError(
                "Embedding vector dimension does not match configuration: "
                f"expected {self.dimension}, got {len(embedding)}"
            )
        try:
            return [float(value) for value in embedding]
        except (TypeError, ValueError) as exc:
            raise EmbeddingResponseError(
                "Embedding vector contains a non-numeric value"
            ) from exc
