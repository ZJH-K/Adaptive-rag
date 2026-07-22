"""Offline contract tests for the FastAPI health and error foundation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import Depends
from fastapi.testclient import TestClient

from src.api.dependencies import ServiceUnavailableError, get_runtime
from src.app import create_app
from src.config import Settings
from src.observability.tracing import NoOpTraceObserver
from src.rag.retrieval.bm25_index import BM25IndexStatus
from src.rag.retrieval.reranker import NoOpReranker


class FakeVectorStore:
    """Expose only the local count operation used by health."""

    def __init__(self, *, count: int = 3, fail: bool = False) -> None:
        self._count = count
        self._fail = fail

    def count(self) -> int:
        if self._fail:
            raise RuntimeError("sensitive vector path")
        return self._count


class FakeRuntime:
    """Minimal runtime surface required by application assembly."""

    def __init__(
        self,
        *,
        needs_rebuild: bool = False,
        vector_store: FakeVectorStore | None = None,
    ) -> None:
        self.vector_store = vector_store or FakeVectorStore()
        self.reranker = NoOpReranker("disabled-test-model")
        self.retriever = object()
        self.ingestion_pipeline = object()
        self._needs_rebuild = needs_rebuild

    def get_index_status(self) -> BM25IndexStatus:
        return BM25IndexStatus(
            generation=2,
            chunk_count=3,
            needs_rebuild=self._needs_rebuild,
            last_successful_rebuild_at=datetime.now(timezone.utc),
            last_failure_code=("bm25_rebuild_failed" if self._needs_rebuild else None),
            is_rebuilding=False,
        )

    def close(self) -> None:
        return


def _settings(**updates: Any) -> Settings:
    values: dict[str, Any] = {
        "llm_api_key": "offline-llm-key",
        "embedding_api_key": "offline-embedding-key",
        "reranker_enabled": False,
        "langfuse_enabled": False,
    }
    values.update(updates)
    return Settings(_env_file=None, **values)


def test_health_ok_uses_shared_runtime_and_request_id() -> None:
    runtime = FakeRuntime()
    build_count = 0

    def factory(settings: Settings) -> Any:
        nonlocal build_count
        build_count += 1
        return runtime

    app = create_app(_settings(), runtime_factory=factory)
    with TestClient(app) as client:
        first = client.get("/api/health", headers={"X-Request-ID": "local-123"})
        second = client.get("/api/health")

    assert first.status_code == 200
    assert first.json()["status"] == "ok"
    assert first.json()["request_id"] == "local-123"
    assert first.headers["X-Request-ID"] == "local-123"
    assert second.status_code == 200
    assert build_count == 1


def test_health_reports_stale_bm25_as_degraded() -> None:
    app = create_app(
        _settings(),
        runtime_factory=lambda settings: FakeRuntime(needs_rebuild=True),
    )
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["bm25"]["status"] == "degraded"
    assert response.json()["bm25"]["needs_rebuild"] is True


def test_missing_langfuse_extra_is_optional_but_diagnostic() -> None:
    observer = NoOpTraceObserver(
        enabled=True,
        configured=True,
        error_code="langfuse_dependency_missing",
    )
    app = create_app(
        _settings(langfuse_enabled=True),
        runtime_factory=lambda settings: FakeRuntime(),
        observer_factory=lambda settings: observer,
    )
    with TestClient(app) as client:
        response = client.get("/api/health")

    tracing = response.json()["tracing"]
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert tracing == {
        "enabled": True,
        "configured": True,
        "available": False,
        "last_error_code": "langfuse_dependency_missing",
    }


def test_core_runtime_startup_failure_returns_503() -> None:
    def fail_factory(settings: Settings) -> Any:
        raise RuntimeError("secret startup details")

    app = create_app(_settings(), runtime_factory=fail_factory)
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert "secret" not in response.text


def test_chroma_unavailable_returns_503_without_leaking_details() -> None:
    app = create_app(
        _settings(),
        runtime_factory=lambda settings: FakeRuntime(
            vector_store=FakeVectorStore(fail=True)
        ),
    )
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["chroma"]["error_code"] == "chroma_unavailable"
    assert "sensitive vector path" not in response.text


def test_known_error_has_safe_envelope_and_request_id() -> None:
    app = create_app(
        _settings(),
        runtime_factory=lambda settings: FakeRuntime(),
    )

    @app.get("/test/unavailable")
    def unavailable(runtime: Any = Depends(get_runtime)) -> None:
        raise ServiceUnavailableError("test_unavailable", "Try again later.")

    with TestClient(app) as client:
        response = client.get(
            "/test/unavailable",
            headers={"X-Request-ID": "error-456"},
        )

    assert response.status_code == 503
    assert response.headers["X-Request-ID"] == "error-456"
    assert response.json() == {
        "error": {
            "code": "test_unavailable",
            "message": "Try again later.",
            "request_id": "error-456",
        }
    }


def test_unknown_error_returns_generic_message() -> None:
    app = create_app(
        _settings(),
        runtime_factory=lambda settings: FakeRuntime(),
    )

    @app.get("/test/error")
    def fail() -> None:
        raise RuntimeError("api-key=must-not-leak")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/test/error")

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == response.json()["error"]["request_id"]
    assert response.json()["error"]["code"] == "internal_error"
    assert "must-not-leak" not in response.text
