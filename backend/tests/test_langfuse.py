"""Offline Langfuse factory readiness and parent lifecycle tests."""

from typing import Any

import pytest

from src.config import Settings
from src.observability import langfuse as langfuse_module
from src.observability.langfuse import LangfuseTraceObserver, build_trace_observer


class Handle:
    def __init__(self, client: "Client", name: str) -> None:
        self.client = client
        self.name = name

    def start_observation(self, **kwargs: Any) -> "Handle":
        self.client.parents.append((self.name, kwargs["name"]))
        return Handle(self.client, kwargs["name"])

    def update(self, **kwargs: Any) -> None:
        self.client.updated.append(self.name)

    def end(self) -> None:
        self.client.ended.append(self.name)


class Client:
    def __init__(self, *, fail_flush: bool = False) -> None:
        self.fail_flush = fail_flush
        self.parents: list[tuple[str, str]] = []
        self.updated: list[str] = []
        self.ended: list[str] = []
        self.shutdown_called = False

    def create_trace_id(self) -> str:
        return "b" * 32

    def start_observation(self, **kwargs: Any) -> Handle:
        return Handle(self, kwargs["name"])

    def flush(self) -> None:
        if self.fail_flush:
            raise RuntimeError("private export response")

    def shutdown(self) -> None:
        self.shutdown_called = True


def _settings(**overrides: Any) -> Settings:
    values = {
        "_env_file": None,
        "langfuse_enabled": True,
        "langfuse_public_key": "pk-test",
        "langfuse_secret_key": "sk-test",
    }
    values.update(overrides)
    return Settings(**values)


def test_enabled_but_unconfigured_is_explicitly_unavailable() -> None:
    observer = build_trace_observer(
        Settings(_env_file=None, langfuse_enabled=True)
    )

    status = observer.get_status()
    assert status.tracing_enabled is True
    assert status.tracing_configured is False
    assert status.tracing_available is False
    assert status.trace_error_code == "langfuse_not_configured"


def test_missing_dependency_is_explicitly_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing():
        raise ImportError("not installed")

    monkeypatch.setattr(langfuse_module, "_load_langfuse_factory", missing)
    observer = build_trace_observer(_settings())

    status = observer.get_status()
    assert status.tracing_configured is True
    assert status.tracing_available is False
    assert status.trace_error_code == "langfuse_dependency_missing"


def test_initialization_failure_has_safe_code() -> None:
    def failed_factory(**kwargs: Any):
        raise RuntimeError("secret SDK detail")

    observer = build_trace_observer(_settings(), client_factory=failed_factory)

    status = observer.get_status()
    assert status.trace_error_code == "langfuse_initialization_failed"
    assert "secret" not in status.model_dump_json()


def test_root_parents_children_and_successfully_exports() -> None:
    client = Client()
    observer = LangfuseTraceObserver(client, environment="test")
    status = observer.start_request()
    assert status.request_id is not None
    first = observer.start_observation(
        request_id=status.request_id, name="router", kind="generation"
    )
    observer.finish_observation(first)
    second = observer.start_observation(
        request_id=status.request_id, name="final_answer", kind="generation"
    )
    observer.finish_observation(second)

    exported = observer.finish_request(status.request_id)

    assert client.parents == [
        ("chat_request", "router"),
        ("chat_request", "final_answer"),
    ]
    assert set(client.ended) == {"router", "final_answer", "chat_request"}
    assert exported.trace_id == "b" * 32
    assert exported.trace_exported is True


def test_export_failure_keeps_real_trace_id_but_marks_not_exported() -> None:
    observer = LangfuseTraceObserver(Client(fail_flush=True), environment="test")
    status = observer.start_request()
    assert status.request_id is not None

    failed = observer.finish_request(status.request_id)

    assert failed.trace_id == "b" * 32
    assert failed.trace_exported is False
    assert failed.trace_error_code == "trace_export_failed"
