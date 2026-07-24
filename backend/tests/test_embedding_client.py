"""Unit tests for the OpenAI-compatible embedding client."""

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import APIConnectionError

from src.config import Settings
from src.rag.embeddings import (
    EmbeddingClient,
    EmbeddingConfigurationError,
    EmbeddingInputError,
    EmbeddingRequestError,
    EmbeddingResponseError,
)


@dataclass
class FakeEmbedding:
    index: int
    embedding: list[float]


class FakeEmbeddingsResource:
    def __init__(
        self,
        *,
        dimension: int = 3,
        error: Exception | None = None,
        response_factory: Any | None = None,
    ) -> None:
        self.dimension = dimension
        self.error = error
        self.response_factory = response_factory
        self.calls: list[dict[str, Any]] = []

    def create(
        self,
        *,
        input: list[str],
        model: str,
        dimensions: int,
    ) -> Any:
        self.calls.append(
            {"input": list(input), "model": model, "dimensions": dimensions}
        )
        if self.error is not None:
            raise self.error
        if self.response_factory is not None:
            return self.response_factory(input)
        data = [
            FakeEmbedding(
                index=index,
                embedding=[float(len(text)), float(index), 1.0],
            )
            for index, text in enumerate(input)
        ]
        return SimpleNamespace(data=data)


class FakeAPIClient:
    def __init__(self, resource: FakeEmbeddingsResource | None = None) -> None:
        self.embeddings = resource or FakeEmbeddingsResource()


def _client(
    fake: FakeAPIClient | None = None,
    **overrides: Any,
) -> EmbeddingClient:
    arguments: dict[str, Any] = {
        "settings": Settings(_env_file=None),
        "api_key": "test-api-key",
        "dimension": 3,
        "batch_size": 2,
        "api_client": fake or FakeAPIClient(),
    }
    arguments.update(overrides)
    return EmbeddingClient(**arguments)


def test_embed_query_returns_single_vector() -> None:
    fake = FakeAPIClient()

    vector = _client(fake).embed_query("query")

    assert vector == [5.0, 0.0, 1.0]
    assert fake.embeddings.calls == [
        {"input": ["query"], "model": "BAAI/bge-m3", "dimensions": 3}
    ]


def test_documents_are_batched_and_output_order_is_preserved() -> None:
    fake = FakeAPIClient()
    texts = ["a", "bb", "ccc", "dddd", "eeeee"]

    vectors = _client(fake, batch_size=2).embed_documents(texts)

    assert [call["input"] for call in fake.embeddings.calls] == [
        ["a", "bb"],
        ["ccc", "dddd"],
        ["eeeee"],
    ]
    assert [vector[0] for vector in vectors] == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_shuffled_api_items_are_restored_to_input_order() -> None:
    def reversed_response(texts: list[str]) -> Any:
        data = [
            FakeEmbedding(index=index, embedding=[float(index), 0.0, 0.0])
            for index in reversed(range(len(texts)))
        ]
        return SimpleNamespace(data=data)

    fake = FakeAPIClient(
        FakeEmbeddingsResource(response_factory=reversed_response)
    )

    vectors = _client(fake, batch_size=10).embed_documents(["a", "b", "c"])

    assert [vector[0] for vector in vectors] == [0.0, 1.0, 2.0]


def test_empty_document_list_returns_without_api_call() -> None:
    fake = FakeAPIClient()

    assert _client(fake).embed_documents([]) == []
    assert fake.embeddings.calls == []


@pytest.mark.parametrize("query", ["", "   ", "\n\t"])
def test_empty_query_is_rejected(query: str) -> None:
    with pytest.raises(EmbeddingInputError, match="non-empty"):
        _client().embed_query(query)


def test_blank_document_is_rejected_before_api_call() -> None:
    fake = FakeAPIClient()

    with pytest.raises(EmbeddingInputError, match="index 1"):
        _client(fake).embed_documents(["valid", " "])
    assert fake.embeddings.calls == []


def test_missing_api_key_fails_only_when_embedding_is_requested() -> None:
    fake = FakeAPIClient()
    client = EmbeddingClient(
        settings=Settings(_env_file=None),
        api_client=fake,
        dimension=3,
    )

    assert client.embed_documents([]) == []
    with pytest.raises(EmbeddingConfigurationError, match="API key"):
        client.embed_query("query")
    assert fake.embeddings.calls == []


def test_api_request_error_is_wrapped_without_exposing_api_key() -> None:
    secret = "secret-value-that-must-not-leak"
    fake = FakeAPIClient(
        FakeEmbeddingsResource(
            error=APIConnectionError(
                message=f"upstream rejected {secret}",
                request=httpx.Request("POST", "https://provider.invalid"),
            )
        )
    )
    client = _client(fake, api_key=secret)

    with pytest.raises(EmbeddingRequestError) as error:
        client.embed_query("query")

    assert "APIConnectionError" in str(error.value)
    assert secret not in str(error.value)
    assert secret not in repr(error.value)


def test_unknown_embedding_programming_error_is_not_wrapped() -> None:
    fake = FakeAPIClient(
        FakeEmbeddingsResource(error=RuntimeError("implementation bug"))
    )

    with pytest.raises(RuntimeError, match="implementation bug"):
        _client(fake).embed_query("query")


def test_response_count_mismatch_is_rejected() -> None:
    fake = FakeAPIClient(
        FakeEmbeddingsResource(
            response_factory=lambda texts: SimpleNamespace(data=[])
        )
    )

    with pytest.raises(EmbeddingResponseError, match="count"):
        _client(fake).embed_documents(["one", "two"])


def test_response_dimension_mismatch_is_rejected() -> None:
    fake = FakeAPIClient(
        FakeEmbeddingsResource(
            response_factory=lambda texts: SimpleNamespace(
                data=[FakeEmbedding(index=0, embedding=[1.0, 2.0])]
            )
        )
    )

    with pytest.raises(EmbeddingResponseError, match="dimension"):
        _client(fake).embed_query("query")


@pytest.mark.parametrize(
    "indices",
    [[0, 0], [0, 2], [1, 2]],
)
def test_invalid_response_indices_are_rejected(indices: list[int]) -> None:
    def invalid_response(texts: list[str]) -> Any:
        return SimpleNamespace(
            data=[
                FakeEmbedding(index=index, embedding=[1.0, 2.0, 3.0])
                for index in indices
            ]
        )

    fake = FakeAPIClient(
        FakeEmbeddingsResource(response_factory=invalid_response)
    )

    with pytest.raises(EmbeddingResponseError, match="indices"):
        _client(fake).embed_documents(["one", "two"])


def test_constructor_arguments_override_settings() -> None:
    settings = Settings(
        _env_file=None,
        embedding_base_url="https://settings.example/v1",
        embedding_api_key="settings-key",
        embedding_model="settings-model",
        embedding_dimension=4,
        embedding_batch_size=8,
        embedding_timeout_seconds=20,
    )

    client = EmbeddingClient(
        settings=settings,
        base_url="https://override.example/v1",
        api_key="override-key",
        model="override-model",
        dimension=3,
        batch_size=2,
        timeout_seconds=5,
        api_client=FakeAPIClient(),
    )

    assert client.base_url == "https://override.example/v1"
    assert client.api_key == "override-key"
    assert client.model == "override-model"
    assert client.dimension == 3
    assert client.batch_size == 2
    assert client.timeout_seconds == 5


def test_embedding_provider_client_close_is_idempotent() -> None:
    fake = FakeAPIClient()
    fake.close_calls = 0

    def close() -> None:
        fake.close_calls += 1

    fake.close = close
    client = _client(fake)

    client.close()
    client.close()

    assert fake.close_calls == 1
