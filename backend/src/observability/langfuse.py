"""Langfuse SDK v4 lifecycle adapter behind provider-neutral contracts."""

from __future__ import annotations

from typing import Any, Callable

from src.config import Settings
from src.observability.tracing import (
    NoOpTraceObserver,
    ObservationRecord,
    ObservationToken,
    SafeTraceObserver,
    TraceObserver,
    TraceOutcome,
    TracingPolicy,
)


class LangfuseTraceObserver(SafeTraceObserver):
    """Create one Langfuse root span and parent all request observations."""

    def __init__(
        self,
        client: Any,
        *,
        environment: str,
        policy: TracingPolicy | None = None,
    ) -> None:
        super().__init__(policy, enabled=True, configured=True, available=True)
        self.client = client
        self.environment = environment
        self._roots: dict[str, Any] = {}

    @property
    def active_root_count(self) -> int:
        """Return request roots that have not reached a terminal lifecycle."""
        return len(self._roots)

    def _start_request(
        self,
        request_id: str,
        client_request_id: str | None,
    ) -> str | None:
        trace_id = self.client.create_trace_id()
        metadata = {"environment": self.environment}
        if client_request_id is not None:
            metadata["client_request_id"] = client_request_id
        root = self.client.start_observation(
            as_type="span",
            name="chat_request",
            input={"request_id": request_id},
            metadata=metadata,
            trace_context={"trace_id": trace_id},
        )
        self._roots[request_id] = root
        return trace_id

    def _start_observation(self, token: ObservationToken) -> Any:
        root = self._roots[token.request_id]
        return root.start_observation(
            as_type=token.kind,
            name=token.name,
            input=token.input,
            metadata={"environment": self.environment, **token.metadata},
        )

    def _finish_observation(
        self,
        token: ObservationToken,
        record: ObservationRecord,
    ) -> None:
        if token.provider_handle is None:
            return
        metadata = {"environment": self.environment, **record.metadata}
        try:
            token.provider_handle.update(
                output=record.output,
                metadata=metadata,
                level=record.level,
                status_message=record.status_message or record.outcome,
            )
        finally:
            token.provider_handle.end()

    def _finish_request(
        self,
        request_id: str,
        output: dict[str, Any],
        metadata: dict[str, Any],
        outcome: TraceOutcome,
    ) -> None:
        root = self._roots.pop(request_id, None)
        if root is None:
            return
        try:
            root.update(
                output=output,
                metadata={"environment": self.environment, **metadata},
                level="ERROR" if outcome == "failure" else "DEFAULT",
                status_message=outcome,
            )
        finally:
            root.end()

    def _flush(self) -> None:
        self.client.flush()

    def _shutdown(self) -> None:
        self.client.shutdown()


def build_trace_observer(
    settings: Settings | None = None,
    *,
    client_factory: Callable[..., Any] | None = None,
) -> TraceObserver:
    """Build disabled, unavailable, or live tracing with explicit readiness."""
    configured = settings or Settings()
    policy = TracingPolicy(
        capture_question=configured.langfuse_capture_question,
        capture_answer=configured.langfuse_capture_answer,
        max_text_chars=configured.langfuse_max_text_chars,
    )
    if not configured.langfuse_enabled:
        return NoOpTraceObserver(policy)

    has_credentials = bool(
        configured.langfuse_public_key and configured.langfuse_secret_key
    )
    if not has_credentials:
        return NoOpTraceObserver(
            policy,
            enabled=True,
            configured=False,
            error_code="langfuse_not_configured",
        )

    factory = client_factory
    if factory is None:
        try:
            factory = _load_langfuse_factory()
        except ImportError:
            return NoOpTraceObserver(
                policy,
                enabled=True,
                configured=True,
                error_code="langfuse_dependency_missing",
            )

    try:
        client = factory(
            public_key=configured.langfuse_public_key,
            secret_key=configured.langfuse_secret_key,
            base_url=configured.langfuse_base_url,
            environment=configured.langfuse_environment,
        )
    except Exception:
        return NoOpTraceObserver(
            policy,
            enabled=True,
            configured=True,
            error_code="langfuse_initialization_failed",
        )
    return LangfuseTraceObserver(
        client,
        environment=configured.langfuse_environment,
        policy=policy,
    )


def _load_langfuse_factory() -> Callable[..., Any]:
    """Load the optional SDK in one monkeypatchable dependency boundary."""
    from langfuse import Langfuse

    return Langfuse
