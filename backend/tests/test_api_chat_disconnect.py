"""Real-socket proof that HTTP disconnect cancels the async provider stream."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Event, Thread
from types import SimpleNamespace
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel
import uvicorn

from src.agent.state import RewriteResult, RouteDecision
from src.app import create_app
from src.config import Settings
from src.llm.client import ChatMessage
from src.observability.tracing import FakeTraceObserver, TraceOutcome
from src.rag.retrieval.bm25_index import BM25IndexStatus
from src.rag.retrieval.reranker import NoOpReranker


StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)


class BlockingAsyncLLM:
    """Emit one delta, then wait forever until the ASGI task is cancelled."""

    def __init__(self) -> None:
        self.produced: list[str] = []
        self.stream_closed = Event()
        self.cancelled = Event()
        self.sync_close_calls = 0
        self.async_close_calls = 0

    def generate_structured(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
        response_model: type[StructuredOutputT],
    ) -> StructuredOutputT:
        if response_model is RouteDecision:
            return response_model.model_validate(
                {"need_retrieval": False, "reason": "general"}
            )
        if response_model is RewriteResult:
            return response_model.model_validate(
                {"rewritten_query": "unused"}
            )
        raise AssertionError("unexpected structured output")

    def generate(self, messages: object) -> str:
        raise AssertionError("production SSE must use the async provider")

    def stream_generate(self, messages: object):
        raise AssertionError("production SSE must not use sync streaming")

    async def astream_generate(self, messages: object) -> AsyncIterator[str]:
        try:
            self.produced.append("first")
            yield "first"
            await asyncio.Future()
            self.produced.append("never")
            yield "never"
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        finally:
            self.stream_closed.set()

    def close(self) -> None:
        self.sync_close_calls += 1

    async def aclose(self) -> None:
        self.async_close_calls += 1


class SignalledObserver(FakeTraceObserver):
    """Expose root completion without polling or timing sleeps."""

    def __init__(self) -> None:
        super().__init__()
        self.terminal = Event()

    def _finish_request(
        self,
        request_id: str,
        output: dict[str, Any],
        metadata: dict[str, Any],
        outcome: TraceOutcome,
    ) -> None:
        try:
            super()._finish_request(request_id, output, metadata, outcome)
        finally:
            self.terminal.set()


class Runtime:
    """Minimal lifespan-owned runtime for the direct-answer branch."""

    def __init__(self) -> None:
        self.vector_store = SimpleNamespace(count=lambda: 0)
        self.reranker = NoOpReranker()
        self.retriever = SimpleNamespace(retrieve=lambda query: [])
        self.ingestion_pipeline = object()
        self.closed = False

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
        self.closed = True


class SignalledServer(uvicorn.Server):
    """Signal deterministic Uvicorn startup to the test thread."""

    def __init__(self, config: uvicorn.Config, started: Event) -> None:
        super().__init__(config)
        self.started_event = started

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets=sockets)
        self.started_event.set()


class SentEventRecorder:
    """Record every SSE body chunk the application attempts to send."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.body_chunks: list[bytes] = []

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        async def recording_send(message: dict) -> None:
            if message["type"] == "http.response.body" and message.get("body"):
                self.body_chunks.append(bytes(message["body"]))
            await send(message)

        await self.app(scope, receive, recording_send)


@contextmanager
def _live_server(app: Any):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    started = Event()
    server = SignalledServer(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="critical",
            lifespan="on",
        ),
        started,
    )
    thread = Thread(
        target=server.run,
        kwargs={"sockets": [listener]},
        daemon=True,
    )
    thread.start()
    if not started.wait(timeout=10):
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        raise AssertionError("Uvicorn test server did not start")
    try:
        yield port
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        assert not thread.is_alive(), "Uvicorn test server did not stop"


def test_http_disconnect_after_first_token_cancels_async_provider() -> None:
    settings = Settings(
        _env_file=None,
        llm_api_key="offline",
        embedding_api_key="offline",
        reranker_enabled=False,
        langfuse_enabled=False,
    )
    llm = BlockingAsyncLLM()
    observer = SignalledObserver()
    runtime = Runtime()
    app = create_app(
        settings,
        runtime_factory=lambda configured: runtime,
        observer_factory=lambda configured: observer,
        llm_factory=lambda configured: llm,
    )
    recorded_app = SentEventRecorder(app)

    async def read_through_first_token(port: int) -> tuple[list[str], str]:
        names: list[str] = []
        current_event: str | None = None
        async with httpx.AsyncClient(timeout=10.0) as client:
            async with client.stream(
                "POST",
                f"http://127.0.0.1:{port}/api/chat/stream",
                json={
                    "question": "general question",
                    "knowledge_base_id": "technical_docs",
                    "chat_history": [],
                },
            ) as response:
                response.raise_for_status()
                request_id = response.headers["X-Request-ID"]
                async for line in response.aiter_lines():
                    if line.startswith("event: "):
                        current_event = line.removeprefix("event: ")
                    elif line.startswith("data: ") and current_event is not None:
                        names.append(current_event)
                        if current_event == "token":
                            return names, request_id
        raise AssertionError("stream ended before the first token")

    with _live_server(recorded_app) as port:
        names, request_id = asyncio.run(read_through_first_token(port))
        assert llm.stream_closed.wait(timeout=5)
        assert observer.terminal.wait(timeout=5)

        assert names == ["route", "token"]
        assert llm.produced == ["first"]
        assert llm.cancelled.is_set()
        assert observer.finished_outputs[request_id]["outcome"] == "cancelled"
        assert observer.active_request_count == 0
        attempted_output = b"".join(recorded_app.body_chunks).decode("utf-8")
        assert attempted_output.count("event: token") == 1
        assert "event: sources" not in attempted_output
        assert "event: done" not in attempted_output

    assert llm.async_close_calls == 1
    assert llm.sync_close_calls == 1
    assert runtime.closed is True
