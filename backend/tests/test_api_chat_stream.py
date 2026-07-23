"""FastAPI boundary tests for the chat Server-Sent Events endpoint."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import TypeVar

from fastapi.testclient import TestClient
from pydantic import BaseModel

from src.agent.state import RewriteResult, RouteDecision
from src.app import create_app
from src.config import Settings
from src.llm.client import ChatMessage
from src.observability.tracing import FakeTraceObserver, NoOpTraceObserver
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


def _app(
    *,
    retrieval: bool = False,
    retrieval_failure: bool = False,
    observer: FakeTraceObserver | NoOpTraceObserver | None = None,
):
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
        observer_factory=lambda configured: observer or NoOpTraceObserver(),
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
    internal_request_id = response.headers["x-request-id"]
    assert internal_request_id != "chat-request-1"
    assert response.headers["x-client-request-id"] == "chat-request-1"
    assert [name for name, _ in events] == ["route", "token", "token", "done"]
    assert [data["text"] for name, data in events if name == "token"] == [
        "第一段", "第二段"
    ]
    assert events[-1][1]["request_id"] == internal_request_id
    assert events[-1][1]["client_request_id"] == "chat-request-1"
    assert events[-1][1]["trace_id"] is None
    assert events[-1][1]["trace_exported"] is False
    assert events[-1][1]["tracing_enabled"] is False
    assert events[-1][1]["tracing_available"] is False


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


def test_duplicate_client_ids_use_isolated_internal_requests_and_traces() -> None:
    observer = FakeTraceObserver()
    app = _app(observer=observer)

    with TestClient(app) as client:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    client.post,
                    "/api/chat/stream",
                    json=_payload(question=f"question {index}"),
                    headers={"X-Request-ID": "shared-client-id"},
                )
                for index in range(2)
            ]
            responses = [future.result(timeout=10) for future in futures]

    done_events = [
        _events(response.text)[-1][1] for response in responses
    ]
    request_ids = [done["request_id"] for done in done_events]
    trace_ids = [done["trace_id"] for done in done_events]
    assert len(set(request_ids)) == 2
    assert len(set(trace_ids)) == 2
    assert all(done["client_request_id"] == "shared-client-id" for done in done_events)
    assert all(
        response.headers["X-Client-Request-ID"] == "shared-client-id"
        for response in responses
    )
    for request_id, trace_id in zip(request_ids, trace_ids, strict=True):
        roots = [
            record
            for record in observer.records_for(trace_id)
            if record.name == "chat_request"
        ]
        assert len(roots) == 1
        assert roots[0].request_id == request_id
    assert observer.active_request_count == 0


def test_invalid_client_request_id_is_rejected_without_becoming_internal_id() -> None:
    app = _app()

    with TestClient(app) as client:
        responses = [
            client.post(
                "/api/chat/stream",
                json=_payload(),
                headers={"X-Request-ID": invalid},
            )
            for invalid in ("contains space", "x" * 129)
        ]

    for response in responses:
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_client_request_id"
        internal_id = response.headers["X-Request-ID"]
        assert len(internal_id) == 32
        assert response.json()["error"]["request_id"] == internal_id
        assert "X-Client-Request-ID" not in response.headers
