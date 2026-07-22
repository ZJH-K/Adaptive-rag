"""Provider-neutral request tracing lifecycle and safe offline observers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict


ObservationKind = Literal["span", "generation"]
ObservationLevel = Literal["DEFAULT", "WARNING", "ERROR"]
TraceOutcome = Literal["success", "failure", "cancelled"]


class TracingStatus(BaseModel):
    """Safe readiness and export state for one local request."""

    model_config = ConfigDict(frozen=True)

    request_id: str | None = None
    tracing_enabled: bool
    tracing_configured: bool
    tracing_available: bool
    trace_id: str | None = None
    trace_exported: bool = False
    trace_error_code: str | None = None


@dataclass(frozen=True, slots=True)
class TracingPolicy:
    """Control text capture without changing workflow instrumentation."""

    capture_question: bool = False
    capture_answer: bool = False
    max_text_chars: int = 200

    def __post_init__(self) -> None:
        if self.max_text_chars <= 0:
            raise ValueError("max_text_chars must be positive")


@dataclass(frozen=True, slots=True)
class ObservationRecord:
    """One sanitized observation with explicit parent and timestamps."""

    request_id: str
    trace_id: str | None
    name: str
    kind: ObservationKind
    parent_name: str = "chat_request"
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    level: ObservationLevel = "DEFAULT"
    status_message: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: datetime | None = None
    outcome: TraceOutcome = "success"


@dataclass(slots=True)
class ObservationToken:
    """Opaque request-local handle returned before a business operation starts."""

    request_id: str
    trace_id: str | None
    name: str
    kind: ObservationKind
    input: dict[str, Any]
    metadata: dict[str, Any]
    started_at: datetime
    provider_handle: Any = None


class TraceObserver(Protocol):
    """Lifecycle capability injected into workflow nodes."""

    def startup(self) -> TracingStatus: ...
    def start_request(self, request_id: str | None = None) -> TracingStatus: ...

    def start_observation(
        self,
        *,
        request_id: str,
        name: str,
        kind: ObservationKind,
        input: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ObservationToken: ...

    def record(
        self,
        *,
        request_id: str,
        name: str,
        kind: ObservationKind,
        input: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        level: ObservationLevel = "DEFAULT",
        status_message: str | None = None,
    ) -> None: ...

    def finish_observation(
        self,
        token: ObservationToken,
        *,
        output: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        level: ObservationLevel = "DEFAULT",
        status_message: str | None = None,
        outcome: TraceOutcome = "success",
    ) -> None: ...

    def finish_request(
        self,
        request_id: str,
        *,
        output: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        outcome: TraceOutcome = "success",
    ) -> TracingStatus: ...

    def cancel_request(self, request_id: str) -> TracingStatus: ...
    def get_status(self, request_id: str | None = None) -> TracingStatus: ...
    def flush(self) -> bool: ...
    def shutdown(self) -> None: ...


class SafeTraceObserver(ABC):
    """Apply redaction and contain all telemetry failures."""

    _BLOCKED_KEYS = {
        "api_key", "authorization", "context", "document_text", "headers",
        "prompt", "request_headers", "secret_key", "text",
    }

    def __init__(
        self,
        policy: TracingPolicy | None = None,
        *,
        enabled: bool,
        configured: bool,
        available: bool,
        error_code: str | None = None,
    ) -> None:
        self.policy = policy or TracingPolicy()
        self._enabled = enabled
        self._configured = configured
        self._available = available
        self._startup_error_code = error_code
        self._statuses: dict[str, TracingStatus] = {}
        self._lock = Lock()

    def startup(self) -> TracingStatus:
        """Return provider readiness for application lifespan startup."""
        return self.get_status()

    def start_request(self, request_id: str | None = None) -> TracingStatus:
        """Create a local request and a provider trace only when available."""
        local_id = request_id if _valid_request_id(request_id) else uuid4().hex
        trace_id: str | None = None
        error_code = self._startup_error_code
        if self._available:
            try:
                trace_id = self._start_request(local_id)
                if not _valid_trace_id(trace_id):
                    trace_id = None
                    error_code = "trace_creation_failed"
            except Exception:
                trace_id = None
                error_code = "trace_creation_failed"
        status = TracingStatus(
            request_id=local_id,
            tracing_enabled=self._enabled,
            tracing_configured=self._configured,
            tracing_available=self._available and trace_id is not None,
            trace_id=trace_id,
            trace_error_code=error_code,
        )
        with self._lock:
            self._statuses[local_id] = status
        return status

    def start_observation(
        self,
        *,
        request_id: str,
        name: str,
        kind: ObservationKind,
        input: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ObservationToken:
        status = self.get_status(request_id)
        token = ObservationToken(
            request_id=request_id,
            trace_id=status.trace_id,
            name=name,
            kind=kind,
            input=self._sanitize(input or {}),
            metadata=self._sanitize(metadata or {}),
            started_at=datetime.now(timezone.utc),
        )
        if status.tracing_available:
            try:
                token.provider_handle = self._start_observation(token)
            except Exception:
                self._set_error(request_id, "trace_observation_start_failed")
        return token

    def record(
        self,
        *,
        request_id: str,
        name: str,
        kind: ObservationKind,
        input: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        level: ObservationLevel = "DEFAULT",
        status_message: str | None = None,
    ) -> None:
        """Compatibility helper for instantaneous, non-business observations."""
        token = self.start_observation(
            request_id=request_id,
            name=name,
            kind=kind,
            input=input,
        )
        self.finish_observation(
            token,
            output=output,
            metadata=metadata,
            level=level,
            status_message=status_message,
            outcome="failure" if level == "ERROR" else "success",
        )

    def finish_observation(
        self,
        token: ObservationToken,
        *,
        output: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        level: ObservationLevel = "DEFAULT",
        status_message: str | None = None,
        outcome: TraceOutcome = "success",
    ) -> None:
        record = ObservationRecord(
            request_id=token.request_id,
            trace_id=token.trace_id,
            name=token.name,
            kind=token.kind,
            input=token.input,
            output=self._sanitize(output or {}),
            metadata={**token.metadata, **self._sanitize(metadata or {})},
            level=level,
            status_message=self._truncate(status_message),
            started_at=token.started_at,
            ended_at=datetime.now(timezone.utc),
            outcome=outcome,
        )
        try:
            self._finish_observation(token, record)
        except Exception:
            self._set_error(token.request_id, "trace_observation_finish_failed")

    def finish_request(
        self,
        request_id: str,
        *,
        output: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        outcome: TraceOutcome = "success",
    ) -> TracingStatus:
        try:
            self._finish_request(
                request_id,
                self._sanitize(output or {}),
                self._sanitize(metadata or {}),
                outcome,
            )
        except Exception:
            self._set_error(request_id, "trace_finish_failed")
        exported = self.flush() if self.get_status(request_id).tracing_available else False
        if exported:
            self._update_status(request_id, trace_exported=True)
        elif self.get_status(request_id).tracing_available:
            self._set_error(request_id, "trace_export_failed")
        return self.get_status(request_id)

    def cancel_request(self, request_id: str) -> TracingStatus:
        return self.finish_request(request_id, outcome="cancelled")

    def get_status(self, request_id: str | None = None) -> TracingStatus:
        if request_id is not None:
            with self._lock:
                status = self._statuses.get(request_id)
            if status is not None:
                return status
        return TracingStatus(
            request_id=request_id,
            tracing_enabled=self._enabled,
            tracing_configured=self._configured,
            tracing_available=self._available,
            trace_error_code=self._startup_error_code,
        )

    def flush(self) -> bool:
        if not self._available:
            return False
        try:
            self._flush()
            return True
        except Exception:
            return False

    def shutdown(self) -> None:
        try:
            self._shutdown()
        except Exception:
            with self._lock:
                request_ids = tuple(self._statuses)
            for request_id in request_ids:
                self._set_error(request_id, "trace_shutdown_failed")

    def _set_error(self, request_id: str, code: str) -> None:
        self._update_status(request_id, trace_exported=False, trace_error_code=code)

    def _update_status(self, request_id: str, **updates: Any) -> None:
        with self._lock:
            current = self._statuses.get(request_id)
            if current is not None:
                self._statuses[request_id] = current.model_copy(update=updates)

    def _sanitize(self, value: Any, *, key: str | None = None) -> Any:
        if isinstance(value, dict):
            return {
                str(k): self._sanitize(v, key=str(k))
                for k, v in value.items()
                if str(k).lower() not in self._BLOCKED_KEYS
            }
        if isinstance(value, (list, tuple)):
            return [self._sanitize(item) for item in value]
        if isinstance(value, str):
            normalized_key = (key or "").lower()
            if normalized_key == "question" and not self.policy.capture_question:
                return f"[redacted;length={len(value)}]"
            if normalized_key == "answer" and not self.policy.capture_answer:
                return f"[redacted;length={len(value)}]"
            return self._truncate(value)
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return self._truncate(str(value))

    def _truncate(self, value: str | None) -> str | None:
        if value is None or len(value) <= self.policy.max_text_chars:
            return value
        return value[: self.policy.max_text_chars] + "…[truncated]"

    def _start_request(self, request_id: str) -> str | None:
        return None

    def _start_observation(self, token: ObservationToken) -> Any:
        return None

    @abstractmethod
    def _finish_observation(
        self, token: ObservationToken, record: ObservationRecord
    ) -> None: ...

    def _finish_request(
        self,
        request_id: str,
        output: dict[str, Any],
        metadata: dict[str, Any],
        outcome: TraceOutcome,
    ) -> None:
        return

    def _flush(self) -> None:
        return

    def _shutdown(self) -> None:
        return


class NoOpTraceObserver(SafeTraceObserver):
    """Disabled or unavailable observer that never fabricates a trace ID."""

    def __init__(
        self,
        policy: TracingPolicy | None = None,
        *,
        enabled: bool = False,
        configured: bool = False,
        error_code: str | None = None,
    ) -> None:
        super().__init__(
            policy,
            enabled=enabled,
            configured=configured,
            available=False,
            error_code=error_code,
        )

    def _finish_observation(
        self, token: ObservationToken, record: ObservationRecord
    ) -> None:
        return


class FakeTraceObserver(SafeTraceObserver):
    """Thread-safe lifecycle observer for deterministic offline tests."""

    def __init__(
        self,
        policy: TracingPolicy | None = None,
        *,
        fail_flush: bool = False,
    ) -> None:
        super().__init__(policy, enabled=True, configured=True, available=True)
        self.records: list[ObservationRecord] = []
        self.finished_request_ids: list[str] = []
        self.finished_outputs: dict[str, dict[str, Any]] = {}
        self.fail_flush = fail_flush
        self._fake_lock = Lock()
        self._request_started: dict[str, datetime] = {}

    @property
    def finished_trace_ids(self) -> list[str]:
        """Backward-compatible provider trace IDs for completed requests."""
        return [
            status.trace_id
            for request_id in self.finished_request_ids
            if (status := self.get_status(request_id)).trace_id is not None
        ]

    def _start_request(self, request_id: str) -> str | None:
        with self._fake_lock:
            self._request_started[request_id] = datetime.now(timezone.utc)
        return uuid4().hex

    def _finish_observation(
        self, token: ObservationToken, record: ObservationRecord
    ) -> None:
        with self._fake_lock:
            self.records.append(record)

    def _finish_request(
        self,
        request_id: str,
        output: dict[str, Any],
        metadata: dict[str, Any],
        outcome: TraceOutcome,
    ) -> None:
        with self._fake_lock:
            status = self.get_status(request_id)
            self.records.append(
                ObservationRecord(
                    request_id=request_id,
                    trace_id=status.trace_id,
                    name="chat_request",
                    kind="span",
                    parent_name="",
                    input={"request_id": request_id},
                    output=output,
                    metadata=metadata,
                    level="ERROR" if outcome == "failure" else "DEFAULT",
                    status_message=outcome,
                    started_at=self._request_started.pop(
                        request_id, datetime.now(timezone.utc)
                    ),
                    ended_at=datetime.now(timezone.utc),
                    outcome=outcome,
                )
            )
            self.finished_request_ids.append(request_id)
            self.finished_outputs[request_id] = {
                "output": output,
                "metadata": metadata,
                "outcome": outcome,
            }

    def _flush(self) -> None:
        if self.fail_flush:
            raise RuntimeError("synthetic export failure")

    def records_for(self, request_or_trace_id: str) -> list[ObservationRecord]:
        """Return records by local request ID or real provider trace ID."""
        with self._fake_lock:
            records = [
                record for record in self.records
                if record.request_id == request_or_trace_id
                or record.trace_id == request_or_trace_id
            ]
        return sorted(records, key=lambda record: record.started_at)


def _valid_request_id(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_trace_id(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 32:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True
