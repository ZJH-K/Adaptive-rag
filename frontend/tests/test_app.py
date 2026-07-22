"""Streamlit AppTest coverage for API contracts and graceful failure."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import api_client
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from sse import SSEEvent


@pytest.fixture(autouse=True)
def clear_streamlit_resource_cache():
    """Keep cached API clients isolated between AppTest sessions."""
    st.cache_resource.clear()
    yield
    st.cache_resource.clear()


class FakeBackend:
    """Record the browser-to-API contract without network calls."""

    def __init__(self) -> None:
        self.chat_calls: list[dict[str, Any]] = []

    def stats(self) -> dict[str, Any]:
        """Return deterministic sidebar statistics."""
        return {
            "documents_count": 2,
            "chunks_count": 7,
            "bm25": {"status": "ready", "generation": 3},
        }

    def health(self) -> dict[str, Any]:
        """Return disabled optional integrations."""
        return {
            "reranker": {
                "enabled": False,
                "configured": False,
                "available": False,
            },
            "tracing": {
                "enabled": False,
                "configured": False,
                "available": False,
            },
        }

    def stream_chat(self, **kwargs: Any):
        """Yield a representative RAG stream and retain its request."""
        self.chat_calls.append(kwargs)
        yield SSEEvent(
            "route", {"need_retrieval": True, "reason": "document question"}
        )
        yield SSEEvent("rewrite", {"rewritten_query": "stable query"})
        yield SSEEvent(
            "retrieval",
            {
                "mode": "hybrid",
                "dense_count": 3,
                "bm25_count": 2,
                "fused_count": 4,
                "final_count": 2,
                "rrf_entered": True,
                "rerank_entered": False,
                "reranker_degraded": False,
                "degraded_sources": [],
                "degradation_codes": [],
            },
        )
        yield SSEEvent("token", {"text": "增量"})
        yield SSEEvent("token", {"text": "回答"})
        yield SSEEvent(
            "sources",
            {
                "sources": [
                    {
                        "citation_id": "S1",
                        "source": "guide.md",
                        "source_type": "markdown",
                        "page": None,
                        "section": "Overview",
                        "heading_path": ["Guide", "Overview"],
                        "chunk_id": "chunk-1",
                    }
                ]
            },
        )
        yield SSEEvent(
            "done",
            {
                "status": "success",
                "request_id": "request-1",
                "tracing_enabled": False,
                "trace_id": None,
                "trace_exported": False,
            },
        )


class ErrorBackend(FakeBackend):
    """Return a structured mid-stream error after a partial answer."""

    def stream_chat(self, **kwargs: Any):
        """Yield partial text, an error, and the terminal failed event."""
        self.chat_calls.append(kwargs)
        yield SSEEvent(
            "route", {"need_retrieval": False, "reason": "direct question"}
        )
        yield SSEEvent("token", {"text": "已收到的部分"})
        yield SSEEvent(
            "error",
            {
                "code": "llm_stream_failed",
                "message": "The answer stream could not be completed.",
                "retryable": True,
            },
        )
        yield SSEEvent(
            "done",
            {
                "status": "failed",
                "request_id": "request-error",
                "tracing_enabled": False,
                "trace_id": None,
                "trace_exported": False,
            },
        )


def test_app_uses_fake_backend_chat_contract(monkeypatch) -> None:
    fake = FakeBackend()
    monkeypatch.setattr(
        api_client.AdaptiveRAGAPIClient,
        "from_env",
        classmethod(lambda cls: fake),
    )
    app_path = Path(__file__).resolve().parents[1] / "app.py"

    app = AppTest.from_file(str(app_path)).run(timeout=15)
    assert any(
        "Reranker: enabled=False, available=False" in item.value
        for item in app.sidebar.caption
    )
    assert any(
        "Tracing: enabled=False, available=False" in item.value
        for item in app.sidebar.caption
    )
    app.chat_input[0].set_value("文档里怎么说？")
    app.run(timeout=15)

    assert not app.exception
    assert fake.chat_calls == [
        {
            "question": "文档里怎么说？",
            "knowledge_base_id": "technical_docs",
            "chat_history": [],
        }
    ]
    assert any("增量回答" in item.value for item in app.markdown)
    assert any("[S1] guide.md" in item.value for item in app.markdown)


def test_app_preserves_partial_text_when_stream_returns_error(monkeypatch) -> None:
    fake = ErrorBackend()
    monkeypatch.setattr(
        api_client.AdaptiveRAGAPIClient,
        "from_env",
        classmethod(lambda cls: fake),
    )
    app_path = Path(__file__).resolve().parents[1] / "app.py"

    app = AppTest.from_file(str(app_path)).run(timeout=15)
    app.chat_input[0].set_value("触发流错误")
    app.run(timeout=15)

    assert not app.exception
    assert any("已收到的部分" in item.value for item in app.markdown)
    assert any("llm_stream_failed" in item.value for item in app.error)


def test_app_renders_when_backend_is_unreachable(
    monkeypatch,
) -> None:
    monkeypatch.setenv("BACKEND_URL", "http://127.0.0.1:9")
    app_path = Path(__file__).resolve().parents[1] / "app.py"

    app = AppTest.from_file(str(app_path)).run(timeout=15)

    assert not app.exception
    assert app.title[0].value == "Adaptive RAG 技术文档助手"
    assert app.chat_input[0].placeholder == "询问通用问题或当前技术文档……"
    assert any("后端不可用" in item.value for item in app.sidebar.error)
