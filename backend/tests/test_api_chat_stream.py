"""FastAPI boundary tests for the chat Server-Sent Events endpoint."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import TypeVar

from fastapi.testclient import TestClient
from pydantic import BaseModel

from src.agent.state import RewriteResult, RouteDecision
from src.app import create_app
from src.config import Settings
from src.llm.client import ChatMessage
from src.observability.tracing import NoOpTraceObserver
from src.rag.retrieval.bm25_index import BM25IndexStatus
from src.rag.retrieval.exceptions import RetrievalUnavailableError
from src.rag.retrieval.reranker import NoOpReranker
from src.rag.schemas import SearchHit


StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)


class APILLM:
    """Offline route/rewrite decisions and exact stream deltas."""

    def __init__(self, *, retrieval: bool = False) -> None:
        self.retrieval = retrieval

    def generate_structured(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
        response_model: type[StructuredOutputT],
    ) -> StructuredOutputT:
        if response_model is RouteDecision:
            return response_model.model_validate(
                {"need_retrieval": self.retrieval, "reason": "safe reason"}
            )
        if response_model is RewriteResult:
            return response_model.model_validate(
                {"rewritten_query": "rewritten query"}
            )
        raise AssertionError("unexpected model")

    def generate(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
    ) -> str:
        raise AssertionError("SSE endpoint must not call non-streaming generate")

    def stream_generate(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
    ) -> Iterator[str]:
        return iter(["第一段", "第二段"])


class APIRetriever:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def retrieve(self, query: str) -> list[SearchHit]:
        if self.fail:
            raise RetrievalUnavailableError()
        return [
            SearchHit(
                chunk_id="chunk-1",
                text="Grounded evidence.",
                metadata={
                    "source": "manual.pdf",
                    "source_type": "pdf",
                    "page": 2,
                    "content_hash": "hash-1",
                },
                dense_score=0.9,
            )
        ]


class APIRuntime:
    def __init__(self, retriever: APIRetriever) -> None:
        self.vector_store = SimpleNamespace(count=lambda: 0)
        self.reranker = NoOpReranker()
        self.retriever = retriever
        self.ingestion_pipeline = object()

    def get_index_status(self) -> BM25IndexStatus:
        return BM25IndexStatus(
            generation=1,
            chunk_count=0,
            needs_rebuild=False,
            last_successful_rebuild_at=datetime.now(timezone.utc),
            last_failure_code=None,
            is_rebuilding=False,
        )

    def close(self) -> None:
        return


def _app(*, retrieval: bool = False, retrieval_failure: bool = False):
    settings = Settings(
        _env_file=None,
        llm_api_key="offline",
        embedding_api_key="offline",
        knowledge_base_id="technical_docs",
        reranker_enabled=False,
        langfuse_enabled=False,
    )
    runtime = APIRuntime(APIRetriever(fail=retrieval_failure))
    llm = APILLM(retrieval=retrieval)
    return create_app(
        settings,
        runtime_factory=lambda configured: runtime,
        observer_factory=lambda configured: NoOpTraceObserver(),
        llm_factory=lambda configured: llm,
    )


def _payload(**updates):
    payload = {
        "question": "请回答这个问题",
        "knowledge_base_id": "technical_docs",
        "chat_history": [],
    }
    payload.update(updates)
    return payload


def _events(text: str) -> list[tuple[str, dict]]:
    normalized = text.replace("\r\n", "\n").strip()
    events: list[tuple[str, dict]] = []
    for block in normalized.split("\n\n"):
        lines = block.splitlines()
        assert lines[0].startswith("event: ")
        assert lines[1].startswith("data: ")
        events.append(
            (
                lines[0].removeprefix("event: "),
                json.loads(lines[1].removeprefix("data: ")),
            )
        )
    return events


def test_direct_sse_headers_order_tokens_and_request_id() -> None:
    app = _app()
    with TestClient(app) as client:
        response = client.post(
            "/api/chat/stream",
            json=_payload(),
            headers={"X-Request-ID": "chat-request-1"},
        )

    events = _events(response.text)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "text/event-stream; charset=utf-8"
    )
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert response.headers["x-request-id"] == "chat-request-1"
    assert [name for name, _ in events] == ["route", "token", "token", "done"]
    assert [data["text"] for name, data in events if name == "token"] == [
        "第一段", "第二段"
    ]
    assert events[-1][1]["request_id"] == "chat-request-1"
    assert events[-1][1]["trace_id"] is None


def test_rag_sse_sources_use_context_builder_location() -> None:
    app = _app(retrieval=True)
    with TestClient(app) as client:
        response = client.post("/api/chat/stream", json=_payload())

    events = _events(response.text)
    assert [name for name, _ in events] == [
        "route", "rewrite", "retrieval", "token", "token", "sources", "done"
    ]
    sources = next(data for name, data in events if name == "sources")
    assert sources["context_chunk_ids"] == ["chunk-1"]
    assert sources["sources"] == [
        {
            "citation_id": "S1",
            "citation": "manual.pdf | page 2",
            "chunk_id": "chunk-1",
            "source": "manual.pdf",
            "source_type": "pdf",
            "page": 2,
            "section": None,
            "heading_path": [],
        }
    ]


def test_stream_failure_is_structured_and_connection_completes() -> None:
    app = _app(retrieval=True, retrieval_failure=True)
    with TestClient(app) as client:
        response = client.post("/api/chat/stream", json=_payload())

    events = _events(response.text)
    assert response.status_code == 200
    assert [name for name, _ in events] == ["route", "rewrite", "error", "done"]
    assert events[-2][1]["code"] == "retrieval_unavailable"
    assert events[-1][1]["status"] == "failed"


def test_invalid_requests_return_json_before_sse_opens() -> None:
    app = _app()
    cases = [
        (_payload(question="   "), 422, "invalid_request"),
        (_payload(question="x" * 4001), 422, "invalid_request"),
        (
            _payload(
                chat_history=[{"role": "user", "content": "x"}] * 21
            ),
            422,
            "invalid_request",
        ),
        (_payload(knowledge_base_id="another-kb"), 400, "invalid_knowledge_base"),
    ]

    with TestClient(app) as client:
        for payload, expected_status, expected_code in cases:
            response = client.post("/api/chat/stream", json=payload)
            assert response.status_code == expected_status
            assert response.headers["content-type"].startswith("application/json")
            assert response.json()["error"]["code"] == expected_code
            assert response.json()["error"]["request_id"] == response.headers[
                "X-Request-ID"
            ]
