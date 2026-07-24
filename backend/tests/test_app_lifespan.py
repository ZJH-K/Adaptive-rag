"""Lifecycle and dependency reuse tests for the FastAPI application."""

from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends
from fastapi.testclient import TestClient

from src.api.dependencies import (
    get_chat_service,
    get_ingestion_service,
    get_runtime,
    get_settings,
)
from src.app import create_app
from src.config import Settings
from src.observability.tracing import NoOpTraceObserver
from src.rag.retrieval.bm25_index import BM25IndexStatus
from src.rag.retrieval.reranker import NoOpReranker


class RecordingObserver(NoOpTraceObserver):
    """Record the observer lifecycle without external I/O."""

    def __init__(self) -> None:
        super().__init__()
        self.flush_calls = 0
        self.shutdown_calls = 0

    def flush(self) -> bool:
        self.flush_calls += 1
        return super().flush()

    def shutdown(self) -> None:
        self.shutdown_calls += 1
        super().shutdown()


class RecordingRuntime:
    """Record runtime close and expose shared dependency identities."""

    def __init__(self) -> None:
        self.vector_store = _VectorStore()
        self.reranker = NoOpReranker()
        self.retriever = object()
        self.ingestion_pipeline = object()
        self.close_calls = 0

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
        self.close_calls += 1


class RecordingLLM:
    """Record both SDK client lifecycle surfaces."""

    def __init__(self) -> None:
        self.close_calls = 0
        self.aclose_calls = 0

    def close(self) -> None:
        self.close_calls += 1

    async def aclose(self) -> None:
        self.aclose_calls += 1


class _VectorStore:
    def count(self) -> int:
        return 0


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        llm_api_key="offline-llm-key",
        embedding_api_key="offline-embedding-key",
        reranker_enabled=False,
        langfuse_enabled=False,
    )


def test_importing_asgi_entrypoint_does_not_start_runtime() -> None:
    sys.modules.pop("src.main", None)
    module = importlib.import_module("src.main")

    assert not hasattr(module.app.state, "services")


def test_lifespan_builds_once_and_closes_shared_services() -> None:
    runtime = RecordingRuntime()
    observer = RecordingObserver()
    runtime_builds = 0
    observer_builds = 0

    def runtime_factory(settings: Settings) -> Any:
        nonlocal runtime_builds
        runtime_builds += 1
        return runtime

    def observer_factory(settings: Settings) -> Any:
        nonlocal observer_builds
        observer_builds += 1
        return observer

    app = create_app(
        _settings(),
        runtime_factory=runtime_factory,
        observer_factory=observer_factory,
    )
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/health").status_code == 200
        assert app.state.services.accepting_operations is True
        assert (
            app.state.services.chat_service.workflow
            is app.state.services.workflow
        )

    assert runtime_builds == 1
    assert observer_builds == 1
    assert observer.flush_calls == 1
    assert observer.shutdown_calls == 1
    assert runtime.close_calls == 1
    assert app.state.services.accepting_operations is False


def test_dependencies_return_lifespan_owned_objects() -> None:
    runtime = RecordingRuntime()
    settings = _settings()
    app = create_app(settings, runtime_factory=lambda configured: runtime)

    @app.get("/test/dependencies")
    def dependencies(
        injected_settings: Settings = Depends(get_settings),
        injected_runtime: Any = Depends(get_runtime),
        ingestion: Any = Depends(get_ingestion_service),
        chat: Any = Depends(get_chat_service),
    ) -> dict[str, bool]:
        return {
            "settings": injected_settings is settings,
            "runtime": injected_runtime is runtime,
            "ingestion": ingestion is runtime.ingestion_pipeline,
            "chat": chat is app.state.services.chat_service,
        }

    with TestClient(app) as client:
        response = client.get("/test/dependencies")

    assert response.status_code == 200
    assert all(response.json().values())


def test_lifespan_closes_llm_sync_and_async_clients_once() -> None:
    runtime = RecordingRuntime()
    llm = RecordingLLM()
    app = create_app(
        _settings(),
        runtime_factory=lambda configured: runtime,
        llm_factory=lambda configured: llm,
    )

    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200

    assert llm.aclose_calls == 1
    assert llm.close_calls == 1
    assert runtime.close_calls == 1


def test_shutdown_failures_do_not_block_remaining_cleanup() -> None:
    events: list[str] = []

    class FailingObserver(RecordingObserver):
        def flush(self) -> bool:
            events.append("flush")
            raise RuntimeError("flush failed")

        def shutdown(self) -> None:
            events.append("shutdown")
            raise RuntimeError("shutdown failed")

    class FailingRuntime(RecordingRuntime):
        def close(self) -> None:
            events.append("close")
            raise RuntimeError("close failed")

    class FailingLLM(RecordingLLM):
        async def aclose(self) -> None:
            events.append("llm_aclose")
            raise RuntimeError("async llm close failed")

        def close(self) -> None:
            events.append("llm_close")
            raise RuntimeError("sync llm close failed")

    app = create_app(
        _settings(),
        runtime_factory=lambda settings: FailingRuntime(),
        observer_factory=lambda settings: FailingObserver(),
        llm_factory=lambda settings: FailingLLM(),
    )
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200

    assert events == [
        "llm_aclose", "llm_close", "flush", "shutdown", "close"
    ]
