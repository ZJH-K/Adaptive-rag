"""Streaming chat orchestration over the existing Agent business functions."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from typing import Any, Protocol

from starlette.concurrency import run_in_threadpool

from src.agent.failures import WorkflowFailure, classify_llm_failure
from src.agent.nodes import (
    TextGenerator,
    bounded_chat_history,
    build_direct_answer_messages,
    retrieve,
    rewrite_query,
    route_query,
)
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
from src.llm.client import ChatMessage
from src.llm.exceptions import LLMError
from src.observability.tracing import TraceObserver, TracingStatus
from src.rag.context_builder import ContextBuilder, ContextSource
from src.rag.service import (
    NO_EVIDENCE_ANSWER,
    ContextConstructor,
    Retriever,
    build_rag_messages,
)


_END = object()


class StreamingTextGenerator(TextGenerator, Protocol):
    """Agent LLM capability extended with provider-native deltas."""

    def stream_generate(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
    ) -> Iterator[str]:
        """Yield the exact text deltas returned by the provider stream."""
        ...


class ChatStreamingService:
    """Adapt shared Agent steps into typed, ordered streaming events."""

    def __init__(
        self,
        llm_client: StreamingTextGenerator,
        retriever: Retriever,
        observer: TraceObserver,
        *,
        context_builder: ContextConstructor | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.retriever = retriever
        self.observer = observer
        self.context_builder = context_builder or ContextBuilder()

    async def stream(
        self,
        request: ChatStreamRequest,
        *,
        request_id: str,
    ) -> AsyncIterator[ChatSSEEvent]:
        """Run one direct or RAG branch and emit its fixed event sequence."""
        history = bounded_chat_history(
            [message.model_dump() for message in request.chat_history]
        )
        state: AgentState = {
            "question": request.question,
            "chat_history": history,
            "request_id": request_id,
            "degradation_events": [],
        }
        self._start_trace(request_id)
        stage = "router"
        answer_parts: list[str] = []
        generation_observation: Any = None
        try:
            route_update = await run_in_threadpool(
                route_query,
                state,
                self.llm_client,
                self.observer,
            )
            self._merge_state(state, route_update)
            need_retrieval = bool(state.get("need_retrieval", True))
            yield RouteEvent(
                data=RouteEventData(
                    need_retrieval=need_retrieval,
                    reason=self._bounded_text(
                        state.get("route_reason"),
                        fallback="retrieval_fallback",
                        limit=240,
                    ),
                )
            )

            if not need_retrieval:
                stage = "direct_answer"
                messages = build_direct_answer_messages(request.question, history)
                generation_observation = self._start_generation(
                    request_id,
                    "direct_answer",
                    request.question,
                    [],
                )
                provider_tokens = self._provider_tokens(messages)
                try:
                    async for token in provider_tokens:
                        answer_parts.append(token)
                        yield TokenEvent(data=TokenEventData(text=token))
                finally:
                    await provider_tokens.aclose()
                self._finish_generation(
                    generation_observation,
                    answer="".join(answer_parts),
                    sources=[],
                )
                generation_observation = None
            else:
                stage = "rewrite"
                rewrite_update = await run_in_threadpool(
                    rewrite_query,
                    state,
                    self.llm_client,
                    self.observer,
                )
                self._merge_state(state, rewrite_update)
                rewritten_query = self._bounded_text(
                    state.get("rewritten_query"),
                    fallback=request.question,
                    limit=4000,
                )
                yield RewriteEvent(
                    data=RewriteEventData(rewritten_query=rewritten_query)
                )

                stage = "retrieval"
                retrieval_update = await run_in_threadpool(
                    retrieve,
                    state,
                    self.retriever,
                    self.context_builder,
                    self.observer,
                    False,
                )
                self._merge_state(state, retrieval_update)
                fatal = state.get("fatal_error")
                if fatal is not None:
                    raise _WorkflowStreamError.from_failure(fatal)
                yield RetrievalEvent(data=self._retrieval_data(state))

                stage = "generation"
                context = state.get("context", "")
                sources = self._context_sources(state)
                context_chunk_ids = self._context_chunk_ids(state)
                if not isinstance(context, str) or not context.strip() or not sources:
                    answer_parts.append(NO_EVIDENCE_ANSWER)
                    yield TokenEvent(data=TokenEventData(text=NO_EVIDENCE_ANSWER))
                else:
                    generation_observation = self._start_generation(
                        request_id,
                        "final_answer",
                        request.question,
                        context_chunk_ids,
                    )
                    provider_tokens = self._provider_tokens(
                        build_rag_messages(request.question, context)
                    )
                    try:
                        async for token in provider_tokens:
                            answer_parts.append(token)
                            yield TokenEvent(data=TokenEventData(text=token))
                    finally:
                        await provider_tokens.aclose()
                    self._finish_generation(
                        generation_observation,
                        answer="".join(answer_parts),
                        sources=sources,
                    )
                    generation_observation = None
                yield SourcesEvent(
                    data=SourcesEventData(
                        sources=sources,
                        context_chunk_ids=context_chunk_ids,
                    )
                )

            trace_status = self._finish_trace(
                request_id,
                answer="".join(answer_parts),
                outcome="success",
                stage=stage,
            )
            yield DoneEvent(
                data=self._done_data("success", request_id, trace_status)
            )
        except (asyncio.CancelledError, GeneratorExit):
            if generation_observation is not None:
                self._finish_generation(
                    generation_observation,
                    answer="".join(answer_parts),
                    sources=[],
                    outcome="cancelled",
                )
            self._cancel_trace(request_id)
            raise
        except Exception as exc:
            if generation_observation is not None:
                self._finish_generation(
                    generation_observation,
                    answer="".join(answer_parts),
                    sources=[],
                    outcome="failure",
                )
            failure = self._safe_failure(exc, stage)
            yield ErrorEvent(
                data=ErrorEventData(
                    code=failure.code,
                    message=failure.message,
                    retryable=failure.retryable,
                )
            )
            trace_status = self._finish_trace(
                request_id,
                answer="".join(answer_parts),
                outcome="failure",
                stage=stage,
            )
            yield DoneEvent(
                data=self._done_data("failed", request_id, trace_status)
            )

    async def _provider_tokens(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
    ) -> AsyncIterator[str]:
        async_stream_generate = getattr(self.llm_client, "astream_generate", None)
        if callable(async_stream_generate):
            async_iterator = async_stream_generate(messages)
            try:
                async for token in async_iterator:
                    if isinstance(token, str) and token != "":
                        yield token
            finally:
                close = getattr(async_iterator, "aclose", None)
                if callable(close):
                    try:
                        await close()
                    except Exception:
                        pass
            return
        iterator = iter(self.llm_client.stream_generate(messages))
        try:
            while True:
                token = await run_in_threadpool(_next_or_end, iterator)
                if token is _END:
                    break
                if not isinstance(token, str) or token == "":
                    continue
                yield token
        finally:
            close = getattr(iterator, "close", None)
            if callable(close):
                try:
                    await run_in_threadpool(close)
                except Exception:
                    pass

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
        sources = state.get("context_sources", [])
        return [source for source in sources if isinstance(source, ContextSource)]

    @staticmethod
    def _context_chunk_ids(state: AgentState) -> list[str]:
        values = state.get("context_chunk_ids", [])
        return [value for value in values if isinstance(value, str)]

    def _start_trace(self, request_id: str) -> TracingStatus:
        try:
            return self.observer.start_request(request_id)
        except Exception:
            return self._trace_status(request_id)

    def _finish_trace(
        self,
        request_id: str,
        *,
        answer: str,
        outcome: str,
        stage: str,
    ) -> TracingStatus:
        try:
            return self.observer.finish_request(
                request_id,
                output={"answer": answer},
                metadata={"current_stage": stage},
                outcome=outcome,
            )
        except Exception:
            return self._trace_status(request_id)

    def _cancel_trace(self, request_id: str) -> TracingStatus:
        try:
            return self.observer.cancel_request(request_id)
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

    def _start_generation(
        self,
        request_id: str,
        name: str,
        question: str,
        context_chunk_ids: list[str],
    ) -> Any:
        try:
            return self.observer.start_observation(
                request_id=request_id,
                name=name,
                kind="generation",
                input={
                    "question": question,
                    "context_chunk_ids": context_chunk_ids,
                },
            )
        except Exception:
            return None

    def _finish_generation(
        self,
        token: Any,
        *,
        answer: str,
        sources: list[ContextSource],
        outcome: str = "success",
    ) -> None:
        if token is None:
            return
        try:
            self.observer.finish_observation(
                token,
                output={
                    "answer": answer,
                    "sources": [source.model_dump() for source in sources],
                },
                level="ERROR" if outcome == "failure" else "DEFAULT",
                status_message=None if outcome == "success" else outcome,
                outcome=outcome,
            )
        except Exception:
            return

    @staticmethod
    def _done_data(
        status: str,
        request_id: str,
        tracing: TracingStatus,
    ) -> DoneEventData:
        return DoneEventData(
            status=status,
            request_id=request_id,
            trace_id=tracing.trace_id,
            tracing_enabled=tracing.tracing_enabled,
            tracing_configured=tracing.tracing_configured,
            tracing_available=tracing.tracing_available,
            trace_exported=tracing.trace_exported,
            trace_error_code=tracing.trace_error_code,
        )

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
        code = failure.code or failure.error_type
        return cls(code, failure.safe_message, True)


class _SafeStreamFailure:
    def __init__(self, code: str, message: str, retryable: bool) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable


def _next_or_end(iterator: Iterator[str]) -> str | object:
    return next(iterator, _END)


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _string_list(value: object) -> list[str]:
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    return []
