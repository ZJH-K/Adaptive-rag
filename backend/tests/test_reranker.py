"""Offline tests for the provider client and immutable rerank adapter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError

import pytest

from src.config import Settings
from src.rag.retrieval import (
    NoOpReranker,
    RerankScore,
    RerankerAdapter,
    RerankerClient,
    RerankerConfigurationError,
    RerankerInputError,
    RerankerRequestError,
    RerankerResponseError,
    build_reranker,
)
from src.rag.schemas import SearchHit


class FakeTransport:
    """Return one configured provider response and record request details."""

    def __init__(
        self,
        response: bytes | str | Mapping[str, Any] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.response = response if response is not None else {"results": []}
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def post(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout: float,
    ) -> bytes | str | Mapping[str, Any]:
        """Record a call before returning or raising."""
        self.calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "payload": dict(payload),
                "timeout": timeout,
            }
        )
        if self.error is not None:
            raise self.error
        return self.response


class FakeScoringClient:
    """Return injected normalized scores without network access."""

    def __init__(self, scores: list[RerankScore]) -> None:
        self.scores = scores
        self.calls: list[tuple[str, list[str]]] = []

    def score(self, query: str, documents: list[str]) -> list[RerankScore]:
        """Record exact query-document pairs and return configured scores."""
        self.calls.append((query, list(documents)))
        return list(self.scores)


def _hit(index: int) -> SearchHit:
    return SearchHit(
        chunk_id=f"chunk-{index}",
        text=f"Document {index}",
        metadata={"source": "guide.md", "nested": {"position": index}},
        dense_score=0.9 - index * 0.1,
        bm25_score=3.0 - index,
        fused_score=0.03 - index * 0.001,
    )


def _client(transport: FakeTransport, **overrides: Any) -> RerankerClient:
    arguments: dict[str, Any] = {
        "settings": Settings(
            _env_file=None,
            reranker_model="offline-reranker-model",
        ),
        "api_key": "test-reranker-key",
        "transport": transport,
    }
    arguments.update(overrides)
    return RerankerClient(**arguments)


def _response(*items: tuple[int, Any]) -> dict[str, Any]:
    return {
        "results": [
            {"index": index, "relevance_score": score}
            for index, score in items
        ]
    }


def test_empty_candidates_return_without_client_call() -> None:
    client = FakeScoringClient([])

    result = RerankerAdapter(client).rerank("query", [])

    assert result == []
    assert client.calls == []


def test_single_candidate_is_copied_and_scored() -> None:
    original = _hit(0)
    client = FakeScoringClient([RerankScore(index=0, score=0.75)])

    result = RerankerAdapter(client).rerank("query", [original])

    assert [hit.chunk_id for hit in result] == ["chunk-0"]
    assert result[0].rerank_score == 0.75
    assert result[0] is not original


def test_multiple_candidates_are_sorted_with_deterministic_ties() -> None:
    hits = [_hit(0), _hit(1), _hit(2)]
    client = FakeScoringClient(
        [
            RerankScore(index=2, score=0.9),
            RerankScore(index=1, score=0.8),
            RerankScore(index=0, score=0.8),
        ]
    )

    result = RerankerAdapter(client).rerank("query", hits)

    assert [hit.chunk_id for hit in result] == [
        "chunk-2",
        "chunk-0",
        "chunk-1",
    ]
    assert client.calls == [
        ("query", ["Document 0", "Document 1", "Document 2"])
    ]


def test_top_k_limits_reranked_results() -> None:
    hits = [_hit(0), _hit(1), _hit(2)]
    client = FakeScoringClient(
        [
            RerankScore(index=0, score=0.1),
            RerankScore(index=1, score=0.9),
            RerankScore(index=2, score=0.8),
        ]
    )

    result = RerankerAdapter(client, top_k=2).rerank("query", hits)

    assert [hit.chunk_id for hit in result] == ["chunk-1", "chunk-2"]


def test_adapter_preserves_input_and_all_existing_fields() -> None:
    hits = [_hit(0), _hit(1)]
    before = [hit.model_dump() for hit in hits]
    client = FakeScoringClient(
        [RerankScore(index=0, score=0.2), RerankScore(index=1, score=0.7)]
    )

    result = RerankerAdapter(client).rerank("query", hits)

    assert [hit.model_dump() for hit in hits] == before
    assert all(result_hit is not input_hit for result_hit, input_hit in zip(
        sorted(result, key=lambda hit: hit.chunk_id), hits, strict=True
    ))
    reranked_zero = next(hit for hit in result if hit.chunk_id == "chunk-0")
    assert reranked_zero.metadata == hits[0].metadata
    assert reranked_zero.metadata is not hits[0].metadata
    assert reranked_zero.dense_score == hits[0].dense_score
    assert reranked_zero.bm25_score == hits[0].bm25_score
    assert reranked_zero.fused_score == hits[0].fused_score
    assert reranked_zero.rerank_score == 0.2


def test_client_submits_one_batch_and_accepts_shuffled_indices() -> None:
    transport = FakeTransport(_response((2, 0.2), (0, 0.9), (1, 0.4)))

    scores = _client(transport).score("query", ["a", "b", "c"])

    assert [(item.index, item.score) for item in scores] == [
        (2, 0.2),
        (0, 0.9),
        (1, 0.4),
    ]
    assert transport.calls[0]["url"] == "https://api.siliconflow.cn/v1/rerank"
    assert transport.calls[0]["payload"] == {
        "model": "offline-reranker-model",
        "query": "query",
        "documents": ["a", "b", "c"],
        "top_n": 3,
        "return_documents": False,
    }
    assert transport.calls[0]["timeout"] == 30.0


def test_compatibility_score_field_is_normalized() -> None:
    transport = FakeTransport(
        {"results": [{"index": 0, "score": 0.55}]}
    )

    assert _client(transport).score("query", ["doc"]) == [
        RerankScore(index=0, score=0.55)
    ]


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (_response((0, 0.9), (2, 0.1)), "range"),
        (_response((0, 0.9), (0, 0.1)), "duplicated"),
        (_response((0, 0.9)), "missing"),
        ({"results": [{"index": True, "relevance_score": 0.5}]}, "index"),
    ],
)
def test_invalid_provider_indices_are_rejected(
    response: Mapping[str, Any],
    message: str,
) -> None:
    with pytest.raises(RerankerResponseError, match=message):
        _client(FakeTransport(response)).score("query", ["a", "b"])


@pytest.mark.parametrize(
    "result",
    [
        {"index": 0},
        {"index": 0, "relevance_score": "high"},
        {"index": 0, "relevance_score": True},
        {"index": 0, "relevance_score": float("nan")},
        {"index": 0, "relevance_score": 0.5, "score": 0.5},
    ],
)
def test_missing_or_invalid_provider_score_is_rejected(
    result: Mapping[str, Any],
) -> None:
    with pytest.raises(RerankerResponseError, match="score"):
        _client(FakeTransport({"results": [result]})).score("query", ["a"])


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("upstream timeout"),
        HTTPError("https://example.invalid", 500, "failure", None, None),
    ],
)
def test_transport_failures_are_safely_wrapped(error: Exception) -> None:
    with pytest.raises(RerankerRequestError) as caught:
        _client(FakeTransport(error=error)).score("query", ["document"])

    assert type(error).__name__ in str(caught.value)
    assert str(error) not in str(caught.value)


@pytest.mark.parametrize("response", [b"", "  ", b"not-json"])
def test_empty_or_invalid_response_is_rejected(response: bytes | str) -> None:
    with pytest.raises(RerankerResponseError):
        _client(FakeTransport(response)).score("query", ["document"])


def test_error_messages_never_expose_api_key_or_candidate_text() -> None:
    api_key = "secret-reranker-key"
    document = "complete confidential candidate text"
    transport = FakeTransport(
        error=RuntimeError(f"rejected {api_key}: {document}")
    )

    with pytest.raises(RerankerRequestError) as caught:
        _client(transport, api_key=api_key).score("query", [document])

    rendered = f"{caught.value!s} {caught.value!r}"
    assert api_key not in rendered
    assert document not in rendered


def test_blank_inputs_are_rejected_before_transport() -> None:
    transport = FakeTransport(_response((0, 0.5)))
    client = _client(transport)

    with pytest.raises(RerankerInputError, match="query"):
        client.score(" ", ["document"])
    with pytest.raises(RerankerInputError, match="index 0"):
        client.score("query", [" "])
    assert transport.calls == []


def test_missing_api_key_is_lazy_and_empty_input_is_safe() -> None:
    transport = FakeTransport()
    client = RerankerClient(
        settings=Settings(_env_file=None),
        transport=transport,
    )

    assert client.score("", []) == []
    with pytest.raises(RerankerConfigurationError, match="API key"):
        client.score("query", ["document"])
    assert transport.calls == []


@pytest.mark.parametrize("top_k", [0, -1, 1.5, True])
def test_invalid_adapter_top_k_is_rejected(top_k: int) -> None:
    with pytest.raises(RerankerConfigurationError, match="top_k"):
        RerankerAdapter(FakeScoringClient([]), top_k=top_k)  # type: ignore[arg-type]


def test_disabled_factory_returns_noop_without_calling_client() -> None:
    client = FakeScoringClient(
        [RerankScore(index=0, score=1.0)]
    )
    reranker = build_reranker(
        Settings(_env_file=None, reranker_enabled=False),
        client=client,
    )
    hits = [_hit(0)]

    result = reranker.rerank("query", hits)

    assert isinstance(reranker, NoOpReranker)
    assert client.calls == []
    assert result == hits
    assert result is not hits
    assert result[0] is not hits[0]


def test_enabled_factory_uses_configured_top_n() -> None:
    reranker = build_reranker(
        Settings(_env_file=None, reranker_enabled=True, rerank_top_k=1),
        client=FakeScoringClient(
            [
                RerankScore(index=0, score=0.1),
                RerankScore(index=1, score=0.9),
            ]
        ),
    )

    result = reranker.rerank("query", [_hit(0), _hit(1)])

    assert [hit.chunk_id for hit in result] == ["chunk-1"]
