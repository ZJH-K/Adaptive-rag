"""Opt-in real Langfuse smoke test; excluded from default offline runs."""

import os

import pytest

from src.config import Settings
from src.observability.langfuse import LangfuseTraceObserver, build_trace_observer


@pytest.mark.external_langfuse
def test_real_langfuse_observation_smoke() -> None:
    """Send one redacted observation when explicitly authorized by env."""
    if os.getenv("RUN_LANGFUSE_SMOKE") != "1":
        pytest.skip("Set RUN_LANGFUSE_SMOKE=1 to send a real Langfuse trace")

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

    trace_id = observer.create_trace()
    observer.record(
        trace_id=trace_id,
        name="adaptive_rag_smoke",
        kind="span",
        input={"question": "Langfuse connectivity smoke"},
        output={"status": "ok"},
        metadata={"smoke": True},
    )
    observer.finish_trace(trace_id, output={"status": "ok"})
    observer.client.flush()

    assert len(trace_id) == 32
