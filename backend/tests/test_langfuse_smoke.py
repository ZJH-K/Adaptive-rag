"""Opt-in real Langfuse smoke test; excluded from default offline runs."""

import os

import pytest

from src.config import Settings
from src.observability.langfuse import LangfuseTraceObserver, build_trace_observer


@pytest.mark.external_langfuse
def test_real_langfuse_observation_smoke() -> None:
    """Send one redacted observation when explicitly authorized by env."""
    if os.getenv("RUN_EXTERNAL_LANGFUSE_SMOKE") != "1":
        pytest.skip(
            "Set RUN_EXTERNAL_LANGFUSE_SMOKE=1 to send a real Langfuse trace"
        )

    settings = Settings()
    if not (
        settings.langfuse_enabled
        and settings.langfuse_public_key
        and settings.langfuse_secret_key
    ):
        pytest.skip("Langfuse is not enabled or credentials are not configured")
    observer = build_trace_observer(settings)
    if not isinstance(observer, LangfuseTraceObserver):
        pytest.fail("Langfuse is not enabled, configured, and installed")

    status = observer.start_request()
    assert status.request_id is not None
    first = observer.start_observation(
        request_id=status.request_id,
        name="smoke_router",
        kind="generation",
        input={"question": "Langfuse connectivity smoke"},
        metadata={"smoke": True},
    )
    observer.finish_observation(first, output={"route": "direct"})
    second = observer.start_observation(
        request_id=status.request_id,
        name="smoke_answer",
        kind="generation",
    )
    observer.finish_observation(second, output={"status": "ok"})
    exported = observer.finish_request(
        status.request_id, output={"status": "ok"}
    )

    assert exported.trace_id is not None
    assert exported.trace_exported is True
    print("langfuse smoke:", {"trace_id": exported.trace_id})
