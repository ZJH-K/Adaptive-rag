"""Typed SSE encoding and streaming workflow sequence tests."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator, Mapping, Sequence
from typing import Any, TypeVar

from pydantic import BaseModel

from src.agent.state import RewriteResult, RouteDecision
from src.api.chat import ChatStreamingService
from src.api.sse import (
    ChatSSEEvent,
    ChatStreamRequest,
    DoneEvent,
    DoneEventData,
    RouteEvent,
    RouteEventData,
    encode_sse_event,
)
from src.llm.client import ChatMessage
from src.llm.exceptions import LLMResponseError, LLMTimeoutError
from src.observability.tracing import FakeTraceObserver, NoOpTraceObserver
from src.rag.context_builder import ContextBuilder
from src.rag.retrieval.exceptions import RetrievalUnavailableError
from src.rag.retrieval.pipeline import RetrievalDiagnostics, RetrievalResult
from src.rag.schemas import SearchHit


StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)


class ClosableDeltas(Iterator[str]):
    """Provider iterator that proves cancellation reaches upstream."""

    def __init__(
        self,
        deltas: list[str],
        *,
        error_after: int | None = None,
    ) -> None:
        self.deltas = deltas
        self.error_after = error_after
        self.index = 0
        self.closed = False

    def __next__(self) -> str:
        if self.error_after is not None and self.index == self.error_after:
            raise LLMTimeoutError("secret timeout")
        if self.index >= len(self.deltas):
            raise StopIteration
        value = self.deltas[self.index]
        self.index += 1
        return value

    def close(self) -> None:
        self.closed = True


class WorkflowLLM:
    """Deterministic structured decisions plus provider-style token deltas."""

    def __init__(
        self,
        *,
        retrieval: bool,
        deltas: list[str] | None = None,
        invalid_router: bool = False,
        stream_error_after: int | None = None,
    ) -> None:
        self.retrieval = retrieval
        self.deltas = deltas or ["answer"]
        self.invalid_router = invalid_router
        self.stream_error_after = stream_error_after
        self.streams: list[ClosableDeltas] = []
        self.stream_calls: list[list[ChatMessage | Mapping[str, object]]] = []

    def generate_structured(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
        response_model: type[StructuredOutputT],
    ) -> StructuredOutputT:
        if response_model is RouteDecision:
            if self.invalid_router:
                raise LLMResponseError("secret invalid router output")
            return response_model.model_validate(
                {
                    "need_retrieval": self.retrieval,
                    "reason": "document required" if self.retrieval else "general",
                }
            )
        if response_model is RewriteResult:
            return response_model.model_validate(
                {"rewritten_query": "standalone retrieval query"}
            )
        raise AssertionError("unexpected structured model")

    def generate(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
    ) -> str:
        raise AssertionError("streaming workflow must not call generate()")

    def stream_generate(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
    ) -> Iterator[str]:
        self.stream_calls.append(list(messages))
        stream = ClosableDeltas(
            list(self.deltas),
            error_after=self.stream_error_after,
        )
        self.streams.append(stream)
        return stream


class StaticRetriever:
    def __init__(self, hits: list[SearchHit]) -> None:
        self.hits = hits
        self.queries: list[str] = []

    def retrieve(self, query: str) -> list[SearchHit]:
        self.queries.append(query)
        return list(self.hits)


class DiagnosticRetriever(StaticRetriever):
    def __init__(
        self,
        hits: list[SearchHit],
        diagnostics: RetrievalDiagnostics,
    ) -> None:
        super().__init__(hits)
        self.diagnostics = diagnostics

    def retrieve_with_diagnostics(self, query: str) -> RetrievalResult:
        self.queries.append(query)
        return RetrievalResult(hits=self.hits, diagnostics=self.diagnostics)


class FailingRetriever:
    def retrieve(self, query: str) -> list[SearchHit]:
        raise RetrievalUnavailableError()


def _request() -> ChatStreamRequest:
    return ChatStreamRequest(
        question="文档中如何工作？",
        knowledge_base_id="technical_docs",
        chat_history=[],
    )


def _hit(
    chunk_id: str,
    text: str,
    *,
    content_hash: str,
    source: str = "guide.md",
    section: str = "Install",
) -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        text=text,
        metadata={
            "source": source,
            "source_type": "markdown",
            "section": section,
            "heading_path": [section],
            "content_hash": content_hash,
        },
        dense_score=0.9,
        bm25_score=2.0,
        fused_score=0.03,
    )


def _diagnostics(**updates: Any) -> RetrievalDiagnostics:
    values: dict[str, Any] = {
        "mode": "hybrid",
        "requested_mode": "hybrid",
        "rrf_entered": True,
        "rerank_entered": False,
        "final_count": 1,
        "dense_count": 1,
        "bm25_count": 1,
        "fused_count": 1,
        "rerank_input_count": 0,
        "rerank_output_count": 0,
        "reranker_enabled": False,
        "reranker_degraded": False,
        "dense_latency_ms": 1.0,
        "bm25_latency_ms": 1.0,
        "fusion_latency_ms": 1.0,
        "rerank_latency_ms": 0.0,
        "total_latency_ms": 3.0,
    }
    values.update(updates)
    return RetrievalDiagnostics(**values)


async def _collect(service: ChatStreamingService) -> list[ChatSSEEvent]:
    return [event async for event in service.stream(_request(), request_id="req-1")]


def test_direct_branch_order_and_multiple_provider_deltas() -> None:
    llm = WorkflowLLM(retrieval=False, deltas=["真", "流", "式"])
    service = ChatStreamingService(
        llm,
        StaticRetriever([]),
        NoOpTraceObserver(),
    )

    events = asyncio.run(_collect(service))

    assert [event.event for event in events] == [
        "route", "token", "token", "token", "done"
    ]
    assert [event.data.text for event in events if event.event == "token"] == [
        "真", "流", "式"
    ]
    assert llm.streams[0].closed is True
    assert events[-1].data.status == "success"
    assert events[-1].data.trace_id is None


def test_rag_order_and_sources_are_exact_context_builder_output() -> None:
    hits = [
        _hit("used", "Short evidence.", content_hash="same"),
        _hit("deduped", "Duplicate evidence.", content_hash="same"),
        _hit("truncated", "X" * 300, content_hash="other"),
    ]
    llm = WorkflowLLM(retrieval=True, deltas=["依据", " [S1]"])
    service = ChatStreamingService(
        llm,
        StaticRetriever(hits),
        NoOpTraceObserver(),
        context_builder=ContextBuilder(max_chars=120),
    )

    events = asyncio.run(_collect(service))

    assert [event.event for event in events] == [
        "route", "rewrite", "retrieval", "token", "token", "sources", "done"
    ]
    source_event = next(event for event in events if event.event == "sources")
    assert source_event.data.context_chunk_ids == ["used", "truncated"]
    assert [source.chunk_id for source in source_event.data.sources] == [
        "used", "truncated"
    ]
    assert [source.citation_id for source in source_event.data.sources] == [
        "S1", "S2"
    ]
    assert "deduped" not in source_event.data.context_chunk_ids


def test_retrieval_degradation_is_observable_but_answer_completes() -> None:
    diagnostics = _diagnostics(
        mode="dense",
        bm25_count=0,
        reranker_enabled=True,
        rerank_entered=True,
        reranker_degraded=True,
        degradation_codes=("bm25_retrieval_unavailable", "reranker_request_failed"),
        degraded_sources=("bm25",),
    )
    service = ChatStreamingService(
        WorkflowLLM(retrieval=True, deltas=["answer"]),
        DiagnosticRetriever(
            [_hit("one", "Evidence", content_hash="one")],
            diagnostics,
        ),
        NoOpTraceObserver(),
    )

    events = asyncio.run(_collect(service))
    retrieval = next(event for event in events if event.event == "retrieval")

    assert retrieval.data.mode == "dense"
    assert retrieval.data.degraded_sources == ["bm25"]
    assert retrieval.data.reranker_degraded is True
    assert events[-1].event == "done"
    assert events[-1].data.status == "success"


def test_dual_retrieval_failure_emits_error_then_failed_done() -> None:
    service = ChatStreamingService(
        WorkflowLLM(retrieval=True),
        FailingRetriever(),
        NoOpTraceObserver(),
    )

    events = asyncio.run(_collect(service))

    assert [event.event for event in events] == [
        "route", "rewrite", "error", "done"
    ]
    assert events[-2].data.code == "retrieval_unavailable"
    assert events[-1].data.status == "failed"


def test_invalid_router_output_conservatively_uses_retrieval() -> None:
    service = ChatStreamingService(
        WorkflowLLM(retrieval=False, invalid_router=True),
        StaticRetriever([_hit("one", "Evidence", content_hash="one")]),
        NoOpTraceObserver(),
    )

    events = asyncio.run(_collect(service))

    assert events[0].event == "route"
    assert events[0].data.need_retrieval is True
    assert events[0].data.reason == "router_output_parse_failed"
    assert events[1].event == "rewrite"
    assert events[-1].data.status == "success"


def test_midstream_timeout_preserves_prior_token_then_fails() -> None:
    service = ChatStreamingService(
        WorkflowLLM(
            retrieval=False,
            deltas=["first", "never"],
            stream_error_after=1,
        ),
        StaticRetriever([]),
        NoOpTraceObserver(),
    )

    events = asyncio.run(_collect(service))

    assert [event.event for event in events] == [
        "route", "token", "error", "done"
    ]
    assert events[1].data.text == "first"
    assert events[2].data.code == "llm_timeout"
    assert "secret" not in events[2].data.message
    assert events[3].data.status == "failed"


def test_client_cancellation_closes_provider_and_trace() -> None:
    observer = FakeTraceObserver()
    llm = WorkflowLLM(retrieval=False, deltas=["first", "second"])
    service = ChatStreamingService(llm, StaticRetriever([]), observer)

    async def cancel_after_first_token() -> None:
        events = service.stream(_request(), request_id="cancel-1")
        assert (await anext(events)).event == "route"
        assert (await anext(events)).event == "token"
        await events.aclose()

    asyncio.run(cancel_after_first_token())

    assert llm.streams[0].closed is True
    assert llm.streams[0].index == 1
    assert observer.finished_outputs["cancel-1"]["outcome"] == "cancelled"


def test_trace_export_failure_does_not_fail_answer() -> None:
    observer = FakeTraceObserver(fail_flush=True)
    service = ChatStreamingService(
        WorkflowLLM(retrieval=False),
        StaticRetriever([]),
        observer,
    )

    events = asyncio.run(_collect(service))
    done = events[-1]

    assert done.data.status == "success"
    assert done.data.trace_id is not None
    assert done.data.tracing_enabled is True
    assert done.data.trace_exported is False
    assert done.data.trace_error_code == "trace_export_failed"


def test_sse_encoding_is_utf8_json_and_uses_blank_line_terminator() -> None:
    events: list[ChatSSEEvent] = [
        RouteEvent(data=RouteEventData(need_retrieval=False, reason="通用问题")),
        DoneEvent(
            data=DoneEventData(
                status="success",
                request_id="request-1",
                tracing_enabled=False,
                tracing_configured=False,
                tracing_available=False,
                trace_exported=False,
            )
        ),
    ]

    for event in events:
        encoded = encode_sse_event(event)
        lines = encoded.rstrip("\n").splitlines()
        payload = json.loads(lines[1].removeprefix("data: "))
        assert lines[0] == f"event: {event.event}"
        assert payload == event.data.model_dump(mode="json")
        assert encoded.endswith("\n\n")
    assert "通用问题" in encode_sse_event(events[0])
