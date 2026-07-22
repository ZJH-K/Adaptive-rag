"""Offline tests for request-local tracing state and lifecycle semantics."""

from src.observability.tracing import FakeTraceObserver, NoOpTraceObserver


def test_disabled_observer_has_request_id_without_fake_trace_id() -> None:
    observer = NoOpTraceObserver()

    readiness = observer.startup()
    status = observer.start_request()

    assert readiness.request_id is None
    assert readiness.tracing_available is False
    assert status.request_id is not None
    assert status.trace_id is None
    assert status.tracing_enabled is False
    assert status.tracing_available is False
    assert status.trace_exported is False


def test_observation_lifecycle_is_nested_under_root_with_real_timestamps() -> None:
    observer = FakeTraceObserver()
    started = observer.start_request()
    assert started.request_id is not None
    token = observer.start_observation(
        request_id=started.request_id,
        name="router",
        kind="generation",
        input={"question": "private"},
    )
    observer.finish_observation(token, output={"route": "retrieve"})
    finished = observer.finish_request(started.request_id, outcome="success")

    records = observer.records_for(started.request_id)
    assert [record.name for record in records] == ["chat_request", "router"]
    root, child = records
    assert child.parent_name == "chat_request"
    assert root.started_at <= child.started_at <= child.ended_at <= root.ended_at
    assert root.outcome == "success"
    assert finished.trace_id is not None
    assert finished.trace_exported is True


def test_export_failure_is_diagnostic_and_does_not_raise() -> None:
    observer = FakeTraceObserver(fail_flush=True)
    status = observer.start_request()
    assert status.request_id is not None

    finished = observer.finish_request(status.request_id)

    assert finished.trace_exported is False
    assert finished.trace_error_code == "trace_export_failed"


def test_cancelled_request_has_distinct_root_outcome() -> None:
    observer = FakeTraceObserver()
    status = observer.start_request()
    assert status.request_id is not None

    cancelled = observer.cancel_request(status.request_id)

    assert observer.records_for(status.request_id)[0].outcome == "cancelled"
    assert cancelled.trace_exported is True


def test_shutdown_failure_is_contained_and_diagnostic() -> None:
    class FailedShutdownObserver(FakeTraceObserver):
        def _shutdown(self) -> None:
            raise RuntimeError("provider detail")

    observer = FailedShutdownObserver()
    status = observer.start_request()
    assert status.request_id is not None

    observer.shutdown()

    assert observer.get_status(status.request_id).trace_error_code == (
        "trace_shutdown_failed"
    )
