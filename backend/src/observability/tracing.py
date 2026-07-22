"""Provider-neutral, request-local tracing contracts and offline implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Literal, Protocol
from uuid import uuid4


ObservationKind = Literal["span", "generation"]
ObservationLevel = Literal["DEFAULT", "WARNING", "ERROR"]


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
    """One sanitized observation captured by the offline fake."""

    trace_id: str
    name: str
    kind: ObservationKind
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    level: ObservationLevel = "DEFAULT"
    status_message: str | None = None


class TraceObserver(Protocol):
    """Minimal tracing capability injected into workflow nodes."""

    def create_trace(self) -> str:
        """Return a request-local 32-character trace identifier."""
        ...

    def record(
        self,
        *,
        trace_id: str,
        name: str,
        kind: ObservationKind,
        input: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        level: ObservationLevel = "DEFAULT",
        status_message: str | None = None,
    ) -> None:
        """Record and close one workflow observation."""
        ...

    def finish_trace(
        self,
        trace_id: str,
        *,
        output: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Mark the request trace complete after its terminal observation."""
        ...


class SafeTraceObserver(ABC):
    """Apply one redaction policy before delegating to a provider adapter."""

    _BLOCKED_KEYS = {
        "api_key",
        "authorization",
        "context",
        "document_text",
        "headers",
        "prompt",
        "request_headers",
        "secret_key",
        "text",
    }

    def __init__(self, policy: TracingPolicy | None = None) -> None:
        self.policy = policy or TracingPolicy()

    def create_trace(self) -> str:
        """Create a provider trace ID, falling back to a local W3C-sized ID."""
        try:
            trace_id = self._create_trace()
        except Exception:
            trace_id = None
        return trace_id if _valid_trace_id(trace_id) else uuid4().hex

    def record(
        self,
        *,
        trace_id: str,
        name: str,
        kind: ObservationKind,
        input: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        level: ObservationLevel = "DEFAULT",
        status_message: str | None = None,
    ) -> None:
        """Sanitize and emit without allowing telemetry to break the request."""
        try:
            self._emit(
                ObservationRecord(
                    trace_id=trace_id,
                    name=name,
                    kind=kind,
                    input=self._sanitize(input or {}),
                    output=self._sanitize(output or {}),
                    metadata=self._sanitize(metadata or {}),
                    level=level,
                    status_message=self._truncate(status_message),
                )
            )
        except Exception:
            return

    def finish_trace(
        self,
        trace_id: str,
        *,
        output: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Sanitize completion data and keep provider failures non-fatal."""
        try:
            self._finish(
                trace_id,
                self._sanitize(output or {}),
                self._sanitize(metadata or {}),
            )
        except Exception:
            return

    def _sanitize(self, value: Any, *, key: str | None = None) -> Any:
        if isinstance(value, dict):
            return {
                str(item_key): self._sanitize(item_value, key=str(item_key))
                for item_key, item_value in value.items()
                if str(item_key).lower() not in self._BLOCKED_KEYS
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

    def _create_trace(self) -> str | None:
        return uuid4().hex

    @abstractmethod
    def _emit(self, record: ObservationRecord) -> None:
        """Send one already-sanitized observation."""

    def _finish(
        self,
        trace_id: str,
        output: dict[str, Any],
        metadata: dict[str, Any],
    ) -> None:
        return


class NoOpTraceObserver(SafeTraceObserver):
    """Generate trace IDs while deliberately emitting no telemetry."""

    def _emit(self, record: ObservationRecord) -> None:
        return


class FakeTraceObserver(SafeTraceObserver):
    """Thread-safe in-memory observer for deterministic offline tests."""

    def __init__(self, policy: TracingPolicy | None = None) -> None:
        super().__init__(policy)
        self.records: list[ObservationRecord] = []
        self.finished_trace_ids: list[str] = []
        self.finished_outputs: dict[str, dict[str, Any]] = {}
        self._lock = Lock()

    def _emit(self, record: ObservationRecord) -> None:
        with self._lock:
            self.records.append(record)

    def _finish(
        self,
        trace_id: str,
        output: dict[str, Any],
        metadata: dict[str, Any],
    ) -> None:
        with self._lock:
            self.finished_trace_ids.append(trace_id)
            self.finished_outputs[trace_id] = {
                "output": output,
                "metadata": metadata,
            }

    def records_for(self, trace_id: str) -> list[ObservationRecord]:
        """Return one request's observations without relying on call adjacency."""
        with self._lock:
            return [record for record in self.records if record.trace_id == trace_id]


def _valid_trace_id(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 32:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True
