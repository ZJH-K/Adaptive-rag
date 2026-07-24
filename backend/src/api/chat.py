"""Thin SSE adapter over the single compiled LangGraph workflow."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Protocol

from starlette.concurrency import run_in_threadpool

from src.agent.failures import WorkflowFailure, classify_llm_failure
from src.agent.state import AgentState
from src.api.sse import (
    ChatSSEEvent,
    ChatStreamRequest,
    DoneEvent,
    DoneEventData,
    ErrorEvent,
    ErrorEventData,
    RetrievalEvent,
    RetrievalEventData,
    RetrievalHitSummary,
    RewriteEvent,
    RewriteEventData,
    RouteEvent,
    RouteEventData,
    SourcesEvent,
    SourcesEventData,
    TokenEvent,
    TokenEventData,
)
from src.llm.exceptions import LLMError
from src.observability.tracing import TraceObserver, TracingStatus
from src.rag.context_builder import ContextSource


class StreamingWorkflow(Protocol):
    """Minimal compiled-graph interface required by the SSE adapter."""

    def astream(
        self,
        input: AgentState,
        *,
        config: dict[str, Any],
        stream_mode: list[str],
    ) -> AsyncIterator[tuple[str, Any]]: ...


class ChatStreamingService:
    """Map authoritative LangGraph state/custom events to typed SSE events."""

    def __init__(
        self,
        workflow: StreamingWorkflow,
        observer: TraceObserver,
    ) -> None:
        self.workflow = workflow
        self.observer = observer

    async def stream(
        self,
        request: ChatStreamRequest,
        *,
        request_id: str,
        client_request_id: str | None = None,
    ) -> AsyncIterator[ChatSSEEvent]:
        """Execute one graph run and expose its observable production events."""
        state: AgentState = {
            "question": request.question,
            "chat_history": [
                message.model_dump() for message in request.chat_history
            ],
            "request_id": request_id,
            "degradation_events": [],
        }
        started_trace = await self._start_trace(request_id, client_request_id)
        state["tracing_status"] = started_trace
        stage = "router"
        answer_parts: list[str] = []
        terminal_failure: WorkflowFailure | None = None
        graph_events = self.workflow.astream(
            state,
            config={"configurable": {"stream_tokens": True}},
            stream_mode=["custom", "tasks", "updates"],
        )
        graph_closed = False
        try:
            async for mode, payload in graph_events:
                if mode == "custom":
                    token = self._custom_token(payload)
                    if token is not None:
                        answer_parts.append(token)
                        yield TokenEvent(data=TokenEventData(text=token))
                    continue
                if mode == "tasks" and isinstance(payload, dict):
                    node_name = payload.get("name")
                    if isinstance(node_name, str):
                        stage = self._stage_for_node(node_name)
                    continue
                if mode != "updates" or not isinstance(payload, dict):
                    continue

                for node_name, update in payload.items():
                    if not isinstance(update, dict):
                        continue
                    self._merge_state(state, update)
                    stage = self._stage_for_node(node_name)
                    fatal = update.get("fatal_error")
                    if isinstance(fatal, WorkflowFailure):
                        terminal_failure = fatal
                        raise _WorkflowStreamError.from_failure(fatal)

                    if node_name == "route_query":
                        yield RouteEvent(
                            data=RouteEventData(
                                need_retrieval=bool(state["need_retrieval"]),
                                reason=self._bounded_text(
                                    state.get("route_reason"),
                                    fallback="retrieval_fallback",
                                    limit=240,
                                ),
                            )
                        )
                    elif node_name == "rewrite_query":
                        yield RewriteEvent(
                            data=RewriteEventData(
                                rewritten_query=self._bounded_text(
                                    state.get("rewritten_query"),
                                    fallback=request.question,
                                    limit=4000,
                                )
                            )
                        )
                    elif node_name == "retrieve":
                        yield RetrievalEvent(data=self._retrieval_data(state))
                    elif node_name == "generate_answer":
                        yield SourcesEvent(
                            data=SourcesEventData(
                                sources=self._context_sources(state),
                                context_chunk_ids=self._context_chunk_ids(state),
                            )
                        )

            tracing = self._terminal_status(state, request_id)
            yield DoneEvent(data=self._done_data("success", request_id, tracing))
        except (asyncio.CancelledError, GeneratorExit):
            graph_closed = True
            try:
                await asyncio.shield(graph_events.aclose())
            except Exception:
                pass
            await asyncio.shield(self._cancel_trace(request_id))
            raise
        except Exception as exc:
            failure = self._safe_failure(exc, stage)
            yield ErrorEvent(
                data=ErrorEventData(
                    code=failure.code,
                    message=failure.message,
                    retryable=failure.retryable,
                )
            )
            tracing = (
                self._terminal_status(state, request_id)
                if terminal_failure is not None
                else await self._finish_failed_trace(
                    request_id,
                    answer="".join(answer_parts),
                    stage=stage,
                )
            )
            yield DoneEvent(data=self._done_data("failed", request_id, tracing))
        finally:
            if not graph_closed:
                await graph_events.aclose()

    @staticmethod
    def _custom_token(payload: object) -> str | None:
        if not isinstance(payload, dict) or payload.get("event") != "token":
            return None
        text = payload.get("text")
        return text if isinstance(text, str) and text != "" else None

    @staticmethod
    def _merge_state(state: AgentState, update: AgentState) -> None:
        existing_failures = list(state.get("degradation_events", []))
        new_failures = list(update.get("degradation_events", []))
        state.update(update)
        state["degradation_events"] = existing_failures + new_failures

    @staticmethod
    def _retrieval_data(state: AgentState) -> RetrievalEventData:
        diagnostics = state.get("retrieval_diagnostics")
        hits = state.get("retrieved_documents", [])
        summaries = [
            RetrievalHitSummary(
                chunk_id=hit.chunk_id,
                source=_optional_text(hit.metadata.get("source")),
                page=_optional_int(hit.metadata.get("page")),
                section=_optional_text(hit.metadata.get("section")),
                heading_path=_string_list(hit.metadata.get("heading_path")),
                dense_score=hit.dense_score,
                bm25_score=hit.bm25_score,
                fused_score=hit.fused_score,
                rerank_score=hit.rerank_score,
            )
            for hit in hits
        ]
        if diagnostics is None:
            return RetrievalEventData(
                mode="unknown",
                dense_count=sum(hit.dense_score is not None for hit in hits),
                bm25_count=sum(hit.bm25_score is not None for hit in hits),
                fused_count=sum(hit.fused_score is not None for hit in hits),
                final_count=len(hits),
                rrf_entered=False,
                rerank_entered=False,
                reranker_degraded=False,
                total_latency_ms=0.0,
                hits=summaries,
            )
        return RetrievalEventData(
            mode=diagnostics.mode,
            dense_count=diagnostics.dense_count,
            bm25_count=diagnostics.bm25_count,
            fused_count=diagnostics.fused_count,
            final_count=diagnostics.final_count,
            rrf_entered=diagnostics.rrf_entered,
            rerank_entered=diagnostics.rerank_entered,
            reranker_degraded=diagnostics.reranker_degraded,
            degradation_codes=list(diagnostics.degradation_codes),
            degraded_sources=list(diagnostics.degraded_sources),
            total_latency_ms=diagnostics.total_latency_ms,
            hits=summaries,
        )

    @staticmethod
    def _context_sources(state: AgentState) -> list[ContextSource]:
        return [
            source
            for source in state.get("context_sources", [])
            if isinstance(source, ContextSource)
        ]

    @staticmethod
    def _context_chunk_ids(state: AgentState) -> list[str]:
        return [
            value
            for value in state.get("context_chunk_ids", [])
            if isinstance(value, str)
        ]

    async def _start_trace(
        self,
        request_id: str,
        client_request_id: str | None,
    ) -> TracingStatus:
        try:
            return await run_in_threadpool(
                self.observer.start_request,
                request_id,
                client_request_id=client_request_id,
            )
        except Exception:
            return self._trace_status(request_id)

    async def _finish_failed_trace(
        self,
        request_id: str,
        *,
        answer: str,
        stage: str,
    ) -> TracingStatus:
        try:
            return await run_in_threadpool(
                self.observer.finish_request,
                request_id,
                output={"answer": answer},
                metadata={"current_stage": stage},
                outcome="failure",
            )
        except Exception:
            return self._trace_status(request_id)

    async def _cancel_trace(self, request_id: str) -> TracingStatus:
        try:
            return await run_in_threadpool(
                self.observer.cancel_request,
                request_id,
            )
        except Exception:
            return self._trace_status(request_id)

    def _trace_status(self, request_id: str) -> TracingStatus:
        try:
            return self.observer.get_status(request_id)
        except Exception:
            return TracingStatus(
                request_id=request_id,
                tracing_enabled=False,
                tracing_configured=False,
                tracing_available=False,
                trace_error_code="tracing_status_unavailable",
            )

    def _terminal_status(
        self,
        state: AgentState,
        request_id: str,
    ) -> TracingStatus:
        """Use the graph-returned terminal snapshot, never a global lookup."""
        status = state.get("tracing_status")
        if isinstance(status, TracingStatus) and status.completed:
            return status
        return TracingStatus(
            request_id=request_id,
            client_request_id=(
                status.client_request_id
                if isinstance(status, TracingStatus)
                else None
            ),
            tracing_enabled=(
                status.tracing_enabled
                if isinstance(status, TracingStatus)
                else False
            ),
            tracing_configured=(
                status.tracing_configured
                if isinstance(status, TracingStatus)
                else False
            ),
            tracing_available=False,
            trace_exported=False,
            trace_error_code="trace_terminal_snapshot_missing",
            completed=True,
        )

    @staticmethod
    def _done_data(
        status: str,
        request_id: str,
        tracing: TracingStatus,
    ) -> DoneEventData:
        return DoneEventData(
            status=status,
            request_id=request_id,
            client_request_id=tracing.client_request_id,
            trace_id=tracing.trace_id,
            tracing_enabled=tracing.tracing_enabled,
            tracing_configured=tracing.tracing_configured,
            tracing_available=tracing.tracing_available,
            trace_exported=tracing.trace_exported,
            trace_error_code=tracing.trace_error_code,
        )

    @staticmethod
    def _stage_for_node(node_name: str) -> str:
        return {
            "route_query": "router",
            "rewrite_query": "rewrite",
            "retrieve": "retrieval",
            "direct_answer": "direct_answer",
            "generate_answer": "generation",
        }.get(node_name, "workflow")

    @staticmethod
    def _safe_failure(exc: Exception, stage: str) -> "_SafeStreamFailure":
        if isinstance(exc, _WorkflowStreamError):
            return _SafeStreamFailure(exc.code, exc.message, exc.retryable)
        if isinstance(exc, LLMError):
            _, code = classify_llm_failure(exc)
            return _SafeStreamFailure(
                code,
                "Answer generation is temporarily unavailable.",
                code in {"llm_timeout", "llm_request_failed"},
            )
        code = {
            "router": "router_failed",
            "rewrite": "rewrite_failed",
            "retrieval": "retrieval_failed",
            "direct_answer": "generation_failed",
            "generation": "generation_failed",
        }.get(stage, "chat_stream_failed")
        return _SafeStreamFailure(
            code,
            "The chat request could not be completed.",
            stage in {"retrieval", "direct_answer", "generation"},
        )

    @staticmethod
    def _bounded_text(value: object, *, fallback: str, limit: int) -> str:
        if not isinstance(value, str) or not value.strip():
            return fallback
        return value.strip()[:limit]


class _WorkflowStreamError(RuntimeError):
    def __init__(self, code: str, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    @classmethod
    def from_failure(cls, failure: WorkflowFailure) -> "_WorkflowStreamError":
        return cls(
            failure.code or failure.error_type,
            failure.safe_message,
            failure.provider in {"llm", "retrieval", "reranker"},
        )


class _SafeStreamFailure:
    def __init__(self, code: str, message: str, retryable: bool) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _string_list(value: object) -> list[str]:
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    return []
