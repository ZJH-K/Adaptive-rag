"""Optional Langfuse SDK v4 adapter behind the provider-neutral contract."""

from __future__ import annotations

from typing import Any

from src.config import Settings
from src.observability.tracing import (
    NoOpTraceObserver,
    ObservationRecord,
    SafeTraceObserver,
    TraceObserver,
    TracingPolicy,
)


class LangfuseTraceObserver(SafeTraceObserver):
    """Translate sanitized records to Langfuse v4 observations."""

    def __init__(
        self,
        client: Any,
        *,
        environment: str,
        policy: TracingPolicy | None = None,
    ) -> None:
        super().__init__(policy)
        self.client = client
        self.environment = environment

    def _create_trace(self) -> str | None:
        return self.client.create_trace_id()

    def _emit(self, record: ObservationRecord) -> None:
        metadata = {"environment": self.environment, **record.metadata}
        with self.client.start_as_current_observation(
            as_type=record.kind,
            name=record.name,
            input=record.input,
            metadata=metadata,
            trace_context={"trace_id": record.trace_id},
        ) as observation:
            observation.update(
                output=record.output,
                metadata=metadata,
                level=record.level,
                status_message=record.status_message,
            )


def build_trace_observer(settings: Settings | None = None) -> TraceObserver:
    """Build Langfuse only when explicitly enabled and fully configured."""

    configured = settings or Settings()
    policy = TracingPolicy(
        capture_question=configured.langfuse_capture_question,
        capture_answer=configured.langfuse_capture_answer,
        max_text_chars=configured.langfuse_max_text_chars,
    )
    if not (
        configured.langfuse_enabled
        and configured.langfuse_public_key
        and configured.langfuse_secret_key
    ):
        return NoOpTraceObserver(policy)

    try:
        from langfuse import Langfuse

        client = Langfuse(
            public_key=configured.langfuse_public_key,
            secret_key=configured.langfuse_secret_key,
            base_url=configured.langfuse_base_url,
            environment=configured.langfuse_environment,
        )
    except Exception:
        return NoOpTraceObserver(policy)
    return LangfuseTraceObserver(
        client,
        environment=configured.langfuse_environment,
        policy=policy,
    )
