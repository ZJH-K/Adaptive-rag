"""HTTP contract tests for the frontend backend client."""

from __future__ import annotations

import json

import httpx
import pytest

from api_client import APIClientError, AdaptiveRAGAPIClient


class ChunkedStream(httpx.SyncByteStream):
    """Yield chosen network chunks and expose response cleanup."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.closed = False

    def __iter__(self):
        yield from self.chunks

    def close(self) -> None:
        self.closed = True


def _client(handler) -> AdaptiveRAGAPIClient:
    transport = httpx.MockTransport(handler)
    return AdaptiveRAGAPIClient(
        "http://backend.test",
        client=httpx.Client(transport=transport),
    )


def test_upload_load_stats_and_health_contracts() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/documents/upload":
            body = request.read()
            assert b"guide.md" in body
            assert b"markdown_heading" in body
            assert request.headers["content-type"].startswith("multipart/form-data")
            return httpx.Response(
                200,
                json={"status": "done", "document_id": "d1", "chunks_count": 1},
            )
        if request.url.path == "/api/documents/load-default":
            assert json.loads(request.read()) == {
                "knowledge_base_id": "technical_docs",
                "chunk_strategy": "auto",
            }
            return httpx.Response(200, json={"status": "done", "processed": 5})
        if request.url.path == "/api/documents/stats":
            return httpx.Response(
                200,
                json={"documents_count": 5, "chunks_count": 22},
            )
        if request.url.path == "/api/health":
            return httpx.Response(
                200,
                json={
                    "status": "degraded",
                    "reranker": {"enabled": False, "available": False},
                    "tracing": {"enabled": False, "available": False},
                },
            )
        raise AssertionError(request.url.path)

    client = _client(handler)
    upload = client.upload_document(
        filename="guide.md",
        content=b"# Guide",
        content_type="text/markdown",
        knowledge_base_id="technical_docs",
        chunk_strategy="markdown_heading",
    )
    loaded = client.load_default(knowledge_base_id="technical_docs")

    assert upload["status"] == "done"
    assert loaded["processed"] == 5
    assert client.stats()["chunks_count"] == 22
    assert client.health()["status"] == "degraded"
    assert calls == [
        ("POST", "/api/documents/upload"),
        ("POST", "/api/documents/load-default"),
        ("GET", "/api/documents/stats"),
        ("GET", "/api/health"),
    ]


def test_chat_stream_is_incremental_across_arbitrary_chunks() -> None:
    encoded = (
        'event: route\ndata: {"need_retrieval":false,"reason":"通用"}\n\n'
        'event: token\ndata: {"text":"你"}\n\n'
        'event: token\ndata: {"text":"好"}\n\n'
        'event: done\ndata: {"status":"success"}\n\n'
    ).encode("utf-8")
    stream = ChunkedStream([bytes([byte]) for byte in encoded])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat/stream"
        assert json.loads(request.read())["question"] == "hello"
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream; charset=utf-8"},
            stream=stream,
        )

    events = list(
        _client(handler).stream_chat(
            question="hello",
            knowledge_base_id="technical_docs",
            chat_history=[],
        )
    )

    assert [event.event for event in events] == ["route", "token", "token", "done"]
    assert [event.data["text"] for event in events[1:3]] == ["你", "好"]
    assert stream.closed is True


def test_closing_chat_generator_closes_http_response() -> None:
    stream = ChunkedStream(
        [
            b'event: token\ndata: {"text":"first"}\n\n',
            b'event: token\ndata: {"text":"never"}\n\n',
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            stream=stream,
        )

    events = _client(handler).stream_chat(
        question="hello",
        knowledge_base_id="technical_docs",
        chat_history=[],
    )
    assert next(events).data["text"] == "first"
    events.close()

    assert stream.closed is True


def test_backend_error_envelope_is_preserved_without_raw_details() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            headers={"X-Request-ID": "req-1"},
            json={
                "error": {
                    "code": "runtime_unavailable",
                    "message": "Try again later.",
                    "request_id": "req-1",
                }
            },
        )

    with pytest.raises(APIClientError) as raised:
        _client(handler).stats()

    assert raised.value.code == "runtime_unavailable"
    assert raised.value.safe_message == "Try again later."
    assert raised.value.request_id == "req-1"


def test_invalid_sse_json_becomes_frontend_error() -> None:
    stream = ChunkedStream([b"event: token\ndata: private-stack\n\n"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            stream=stream,
        )

    with pytest.raises(APIClientError) as raised:
        list(
            _client(handler).stream_chat(
                question="hello",
                knowledge_base_id="technical_docs",
                chat_history=[],
            )
        )

    assert raised.value.code == "invalid_json"
    assert "private-stack" not in raised.value.safe_message


def test_unreachable_backend_is_safe() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret host details", request=request)

    with pytest.raises(APIClientError) as raised:
        _client(handler).health()

    assert raised.value.code == "backend_unavailable"
    assert "secret" not in raised.value.safe_message
