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


def test_noop_observer_releases_1000_completed_requests() -> None:
    observer = NoOpTraceObserver()

    for _ in range(1000):
        started = observer.start_request()
        assert started.request_id is not None
        terminal = observer.finish_request(started.request_id)
        assert terminal.completed is True

    assert observer.active_request_count == 0
    assert observer.terminal_cache_count <= observer.TERMINAL_CACHE_CAPACITY


def test_duplicate_requested_internal_id_cannot_overwrite_active_request() -> None:
    observer = NoOpTraceObserver()

    first = observer.start_request("fixed-id")
    second = observer.start_request("fixed-id")

    assert first.request_id == "fixed-id"
    assert second.request_id != first.request_id
    assert observer.active_request_count == 2
    assert first.request_id and second.request_id
    observer.cancel_request(first.request_id)
    observer.cancel_request(second.request_id)
    assert observer.active_request_count == 0


def test_all_terminal_paths_release_active_state() -> None:
    observer = NoOpTraceObserver()
    outcomes = []

    completed = observer.start_request()
    failed = observer.start_request()
    cancelled = observer.start_request()
    assert completed.request_id and failed.request_id and cancelled.request_id
    outcomes.append(observer.finish_request(completed.request_id).outcome)
    outcomes.append(observer.fail_request(failed.request_id).outcome)
    outcomes.append(observer.cancel_request(cancelled.request_id).outcome)

    assert outcomes == ["success", "failure", "cancelled"]
    assert observer.active_request_count == 0


def test_repeated_finish_and_cancel_are_idempotent_and_isolated() -> None:
    observer = FakeTraceObserver()
    first = observer.start_request()
    second = observer.start_request()
    assert first.request_id and second.request_id

    first_terminal = observer.finish_request(first.request_id)
    repeated = observer.cancel_request(first.request_id)

    assert repeated == first_terminal
    assert repeated.outcome == "success"
    assert observer.active_request_count == 1
    second_terminal = observer.cancel_request(second.request_id)
    assert second_terminal.outcome == "cancelled"
    assert observer.active_request_count == 0


def test_finish_exception_still_releases_request_state() -> None:
    class FinishFailureObserver(FakeTraceObserver):
        def _finish_request(self, *args, **kwargs) -> None:
            raise RuntimeError("private provider failure")

    observer = FinishFailureObserver()
    started = observer.start_request()
    assert started.request_id

    terminal = observer.fail_request(started.request_id)

    assert terminal.completed is True
    assert terminal.trace_exported is False
    assert terminal.trace_error_code == "trace_finish_failed"
    assert observer.active_request_count == 0
