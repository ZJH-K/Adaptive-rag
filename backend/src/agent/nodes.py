"""Node functions for the lightweight adaptive RAG workflow."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from time import perf_counter
from typing import Any, Protocol, TypeVar
from uuid import uuid4

from pydantic import BaseModel

from src.agent.failures import (
    WorkflowFailure,
    WorkflowStage,
    classify_llm_failure,
)
from src.agent.prompts import (
    DIRECT_ANSWER_PROMPT,
    format_query_rewrite_prompt,
    format_router_prompt,
)
from src.agent.state import AgentState, RewriteResult, RouteDecision
from src.llm.client import ChatMessage
from src.llm.exceptions import LLMError
from src.observability.tracing import TraceObserver
from src.rag.context_builder import ContextBuilder, ContextBuilderError
from src.rag.retrieval.exceptions import RetrievalUnavailableError
from src.rag.service import (
    NO_EVIDENCE_ANSWER,
    ContextConstructor,
    Retriever,
    build_rag_messages,
    execute_retrieval,
)


ROUTER_PARSE_FAILURE_REASON = "router_output_parse_failed"
CHAT_HISTORY_MAX_MESSAGES = 6
CHAT_HISTORY_MAX_CHARS = 4000
REWRITE_HISTORY_LIMIT = CHAT_HISTORY_MAX_MESSAGES
SAFE_WORKFLOW_ERROR_ANSWER = "系统暂时无法完成本次回答，请稍后重试。"
StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)


class TextGenerator(Protocol):
    """Minimal language-model capability required by Agent nodes."""

    def generate(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
    ) -> str:
        """Return assistant text for ordered messages."""
        ...

    def generate_structured(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
        response_model: type[StructuredOutputT],
    ) -> StructuredOutputT:
        """Return one provider-assisted, validated structured response."""
        ...


def route_query(
    state: AgentState,
    llm_client: TextGenerator,
    observer: TraceObserver | None = None,
) -> AgentState:
    """Classify a question and return only the routing state fields."""

    question = _require_question(state)
    request_id = _request_id(state, observer)
    history = bounded_chat_history(state.get("chat_history"))
    prompt = format_router_prompt(question, history)
    started = perf_counter()
    observation = _begin(
        observer, request_id, "router", "generation",
        input={"question": question, "history_messages": len(history)},
    )
    try:
        decision = llm_client.generate_structured(
            [ChatMessage(role="user", content=prompt)],
            RouteDecision,
        )
    except LLMError as exc:
        error_type, code = classify_llm_failure(exc)
        result: AgentState = {
            "need_retrieval": True,
            "route_reason": (
                ROUTER_PARSE_FAILURE_REASON
                if error_type == "invalid_response"
                else "router_call_failed"
            ),
            "current_stage": "router",
            "answer_available": False,
            "request_id": request_id,
            **_tracing_fields(observer, request_id),
            "degradation_events": [
                _failure(
                    stage="router",
                    error_type=error_type,
                    safe_message="Router failed; retrieval fallback was selected.",
                    degraded=True,
                    fatal=False,
                    fallback="retrieve",
                    duration_ms=_elapsed_ms(started),
                    provider="llm",
                    code=code,
                )
            ],
        }
        _record(
            observer,
            token=observation,
            request_id=request_id,
            name="router",
            kind="generation",
            input={"question": question, "history_messages": len(history)},
            output={
                "need_retrieval": True,
                "route_reason": result["route_reason"],
            },
            metadata={
                "duration_ms": result["degradation_events"][0].duration_ms,
                "degraded": True,
                "fallback": "retrieve",
                "error_type": error_type,
            },
            level="WARNING",
            status_message="router_fallback",
        )
        return result

    result = {
        "need_retrieval": decision.need_retrieval,
        "route_reason": decision.reason,
        "current_stage": "router",
        "answer_available": False,
        "request_id": request_id,
        **_tracing_fields(observer, request_id),
    }
    _record(
        observer,
        token=observation,
        request_id=request_id,
        name="router",
        kind="generation",
        input={"question": question, "history_messages": len(history)},
        output={
            "need_retrieval": decision.need_retrieval,
            "route_reason": decision.reason,
        },
        metadata={"duration_ms": _elapsed_ms(started), "degraded": False},
    )
    return result


def direct_answer(
    state: AgentState,
    llm_client: TextGenerator,
    observer: TraceObserver | None = None,
) -> AgentState:
    """Answer a general question without accessing retrieval context."""

    question = _require_question(state)
    request_id = _request_id(state, observer)
    history = bounded_chat_history(state.get("chat_history"))
    messages = build_direct_answer_messages(question, history)
    started = perf_counter()
    observation = _begin(
        observer, request_id, "direct_answer", "generation",
        input={"question": question, "history_messages": len(history)},
    )
    try:
        answer = llm_client.generate(messages)
    except LLMError as exc:
        error_type, code = classify_llm_failure(exc)
        failure = _failure(
            stage="direct_answer",
            error_type=error_type,
            safe_message="Direct answer generation failed.",
            degraded=False,
            fatal=True,
            fallback="safe_error_answer",
            duration_ms=_elapsed_ms(started),
            provider="llm",
            code=code,
        )
        result: AgentState = {
            "answer": SAFE_WORKFLOW_ERROR_ANSWER,
            "current_stage": "direct_answer",
            "fatal_error": failure,
            "answer_available": True,
            "request_id": request_id,
        }
        _record_terminal_answer(
            observer,
            request_id,
            "direct_answer",
            question,
            SAFE_WORKFLOW_ERROR_ANSWER,
            len(history),
            failure,
            observation=observation,
        )
        return result
    result = {
        "answer": answer,
        "current_stage": "direct_answer",
        "answer_available": True,
        "request_id": request_id,
    }
    _record(
        observer,
        token=observation,
        request_id=request_id,
        name="direct_answer",
        kind="generation",
        input={"question": question, "history_messages": len(history)},
        output={"answer": answer},
        metadata={"duration_ms": _elapsed_ms(started), "degraded": False},
    )
    _finish(observer, request_id, result)
    return result


def rewrite_query(
    state: AgentState,
    llm_client: TextGenerator,
    observer: TraceObserver | None = None,
) -> AgentState:
    """Rewrite a contextual question as one standalone retrieval query."""

    question = _require_question(state)
    request_id = _request_id(state, observer)
    history = bounded_chat_history(state.get("chat_history"))
    prompt = format_query_rewrite_prompt(question, history)
    started = perf_counter()
    observation = _begin(
        observer, request_id, "query_rewrite", "generation",
        input={"question": question, "history_messages": len(history)},
    )
    try:
        result = llm_client.generate_structured(
            [ChatMessage(role="user", content=prompt)],
            RewriteResult,
        )
    except LLMError as exc:
        error_type, code = classify_llm_failure(exc)
        result: AgentState = {
            "rewritten_query": question,
            "current_stage": "rewrite",
            "answer_available": False,
            "request_id": request_id,
            "degradation_events": [
                _failure(
                    stage="rewrite",
                    error_type=error_type,
                    safe_message="Query rewrite failed; original question was used.",
                    degraded=True,
                    fatal=False,
                    fallback="original_question",
                    duration_ms=_elapsed_ms(started),
                    provider="llm",
                    code=code,
                )
            ],
        }
        _record(
            observer,
            token=observation,
            request_id=request_id,
            name="query_rewrite",
            kind="generation",
            input={"question": question, "history_messages": len(history)},
            output={"rewritten_query": question},
            metadata={
                "duration_ms": result["degradation_events"][0].duration_ms,
                "degraded": True,
                "fallback": "original_question",
                "error_type": error_type,
            },
            level="WARNING",
            status_message="rewrite_fallback",
        )
        return result

    result = {
        "rewritten_query": result.rewritten_query,
        "current_stage": "rewrite",
        "answer_available": False,
        "request_id": request_id,
    }
    _record(
        observer,
        token=observation,
        request_id=request_id,
        name="query_rewrite",
        kind="generation",
        input={"question": question, "history_messages": len(history)},
        output={"rewritten_query": result["rewritten_query"]},
        metadata={"duration_ms": _elapsed_ms(started), "degraded": False},
    )
    return result


def retrieve(
    state: AgentState,
    retriever: Retriever,
    context_builder: ContextConstructor | None = None,
    observer: TraceObserver | None = None,
    finalize_request: bool = True,
) -> AgentState:
    """Retrieve dense hits and build bounded citation-aware context."""

    question = _require_question(state)
    request_id = _request_id(state, observer)
    rewritten_query = state.get("rewritten_query")
    query = (
        rewritten_query.strip()
        if isinstance(rewritten_query, str) and rewritten_query.strip()
        else question
    )

    retrieval_started = perf_counter()
    retrieval_observations = _begin_retrieval_observations(
        observer, request_id, query, retriever
    )
    try:
        hits, retrieval_diagnostics = execute_retrieval(retriever, query)
    except RetrievalUnavailableError as exc:
        for stage_observation in retrieval_observations.values():
            if stage_observation is not None and observer is not None:
                try:
                    observer.finish_observation(
                        stage_observation,
                        level="ERROR",
                        status_message=exc.code,
                        outcome="failure",
                    )
                except Exception:
                    pass
        failure = _failure(
            stage="retrieval",
            error_type=exc.code,
            safe_message=exc.safe_message,
            degraded=False,
            fatal=True,
            fallback="safe_error_answer",
            duration_ms=_elapsed_ms(retrieval_started),
            provider="retrieval",
            code=exc.code,
        )
        result: AgentState = {
            "retrieved_documents": [],
            "context": "",
            "context_sources": [],
            "context_chunk_ids": [],
            "answer": SAFE_WORKFLOW_ERROR_ANSWER,
            "current_stage": "retrieval",
            "fatal_error": failure,
            "answer_available": True,
            "request_id": request_id,
        }
        _record(
            observer,
            request_id=request_id,
            name="retrieval",
            kind="span",
            input={"query": query},
            output={"retrieved_chunk_ids": []},
            metadata={
                "duration_ms": failure.duration_ms,
                "fatal": True,
                "error_type": failure.error_type,
            },
            level="ERROR",
            status_message=exc.code,
        )
        if finalize_request:
            _finish(observer, request_id, result)
        return result
    degradation_events = _retrieval_failures(retrieval_diagnostics)
    _record_retrieval_observations(
        observer,
        request_id,
        query,
        hits,
        retrieval_diagnostics,
        degradation_events,
        retrieval_observations,
    )
    context_started = perf_counter()
    context_observation = _begin(
        observer, request_id, "context_build", "span",
        input={"retrieved_chunk_ids": [hit.chunk_id for hit in hits]},
    )
    try:
        context_result = (context_builder or ContextBuilder()).build(hits)
    except ContextBuilderError:
        failure = _failure(
            stage="context",
            error_type="context_build_failed",
            safe_message="Retrieved documents could not be converted to context.",
            degraded=False,
            fatal=True,
            fallback="safe_error_answer",
            duration_ms=_elapsed_ms(context_started),
            provider="context_builder",
            code="context_build_failed",
        )
        result: AgentState = {
            "retrieved_documents": hits,
            "context": "",
            "context_sources": [],
            "context_chunk_ids": [],
            "answer": SAFE_WORKFLOW_ERROR_ANSWER,
            "current_stage": "context",
            "fatal_error": failure,
            "answer_available": True,
            "request_id": request_id,
        }
        if degradation_events:
            result["degradation_events"] = degradation_events
        if retrieval_diagnostics is not None:
            result["retrieval_diagnostics"] = retrieval_diagnostics
        _record(
            observer,
            token=context_observation,
            request_id=request_id,
            name="context_build",
            kind="span",
            input={"retrieved_chunk_ids": [hit.chunk_id for hit in hits]},
            output={"context_chunk_ids": [], "sources": []},
            metadata={
                "duration_ms": failure.duration_ms,
                "fatal": True,
                "error_type": failure.error_type,
                "fallback": failure.fallback,
            },
            level="ERROR",
            status_message="context_build_failed",
        )
        if finalize_request:
            _finish(observer, request_id, result)
        return result

    result: AgentState = {
        "retrieved_documents": hits,
        "context": context_result.context,
        "context_sources": context_result.sources,
        "context_chunk_ids": context_result.used_chunk_ids,
        "current_stage": "context",
        "answer_available": False,
        "request_id": request_id,
    }
    if degradation_events:
        result["degradation_events"] = degradation_events
    if retrieval_diagnostics is not None:
        result["retrieval_diagnostics"] = retrieval_diagnostics
    _record(
        observer,
        token=context_observation,
        request_id=request_id,
        name="context_build",
        kind="span",
        input={"retrieved_chunk_ids": [hit.chunk_id for hit in hits]},
        output={
            "context_chunk_ids": context_result.used_chunk_ids,
            "sources": [source.model_dump() for source in context_result.sources],
        },
        metadata={"duration_ms": _elapsed_ms(context_started), "fatal": False},
    )
    return result


def generate_answer(
    state: AgentState,
    llm_client: TextGenerator,
    observer: TraceObserver | None = None,
) -> AgentState:
    """Generate one grounded answer without performing another retrieval."""

    question = _require_question(state)
    request_id = _request_id(state, observer)
    context = state.get("context")
    retrieved_documents = state.get("retrieved_documents", [])
    if (
        not isinstance(context, str)
        or not context.strip()
        or not retrieved_documents
    ):
        result: AgentState = {
            "answer": NO_EVIDENCE_ANSWER,
            "current_stage": "generation",
            "answer_available": True,
            "request_id": request_id,
        }
        _record(
            observer,
            request_id=request_id,
            name="final_answer",
            kind="generation",
            input={
                "question": question,
                "context_chunk_ids": state.get("context_chunk_ids", []),
            },
            output={"answer": NO_EVIDENCE_ANSWER, "sources": []},
            metadata={"skipped": True, "reason": "no_evidence"},
        )
        _finish(observer, request_id, result)
        return result

    started = perf_counter()
    observation = _begin(
        observer, request_id, "final_answer", "generation",
        input={
            "question": question,
            "context_chunk_ids": state.get("context_chunk_ids", []),
        },
    )
    try:
        answer = llm_client.generate(build_rag_messages(question, context))
    except LLMError as exc:
        error_type, code = classify_llm_failure(exc)
        failure = _failure(
            stage="generation",
            error_type=error_type,
            safe_message="Grounded answer generation failed.",
            degraded=False,
            fatal=True,
            fallback="safe_error_answer",
            duration_ms=_elapsed_ms(started),
            provider="llm",
            code=code,
        )
        result: AgentState = {
            "answer": SAFE_WORKFLOW_ERROR_ANSWER,
            "current_stage": "generation",
            "fatal_error": failure,
            "answer_available": True,
            "request_id": request_id,
        }
        _record_terminal_answer(
            observer,
            request_id,
            "final_answer",
            question,
            SAFE_WORKFLOW_ERROR_ANSWER,
            None,
            failure,
            observation=observation,
            context_chunk_ids=state.get("context_chunk_ids", []),
            sources=state.get("context_sources", []),
        )
        return result
    result = {
        "answer": answer,
        "current_stage": "generation",
        "answer_available": True,
        "request_id": request_id,
    }
    _record(
        observer,
        token=observation,
        request_id=request_id,
        name="final_answer",
        kind="generation",
        input={
            "question": question,
            "context_chunk_ids": state.get("context_chunk_ids", []),
        },
        output={
            "answer": answer,
            "sources": _source_payload(state.get("context_sources", [])),
        },
        metadata={"duration_ms": _elapsed_ms(started), "fatal": False},
    )
    _finish(observer, request_id, result)
    return result


def bounded_chat_history(history: object) -> list[dict[str, str]]:
    """Return the newest valid chat messages within shared count/char limits."""

    if not isinstance(history, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in history:
        if not isinstance(item, Mapping):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            continue
        content = content.strip()
        if content:
            normalized.append({"role": role, "content": content})

    selected: list[dict[str, str]] = []
    remaining = CHAT_HISTORY_MAX_CHARS
    for item in reversed(normalized[-CHAT_HISTORY_MAX_MESSAGES:]):
        if remaining <= 0:
            break
        content = item["content"][:remaining]
        selected.append({"role": item["role"], "content": content})
        remaining -= len(content)
    selected.reverse()
    return selected


def build_direct_answer_messages(
    question: str,
    history: list[dict[str, str]],
) -> list[ChatMessage]:
    """Build the shared direct-answer messages for sync and stream runners."""
    messages = [ChatMessage(role="system", content=DIRECT_ANSWER_PROMPT)]
    messages.extend(
        ChatMessage(role=item["role"], content=item["content"])
        for item in history
    )
    messages.append(ChatMessage(role="user", content=question))
    return messages


def _record_retrieval_observations(
    observer: TraceObserver | None,
    request_id: str,
    query: str,
    hits: list[Any],
    diagnostics: object,
    failures: list[WorkflowFailure],
    observations: dict[str, Any],
) -> None:
    """Emit ordered retrieval observations from this request's result only."""

    retrieval_failures = {
        failure.provider: failure
        for failure in failures
        if failure.stage == "retrieval"
    }
    failure_by_stage = {failure.stage: failure for failure in failures}
    dense_hits = [hit for hit in hits if hit.dense_score is not None]
    bm25_hits = [hit for hit in hits if hit.bm25_score is not None]
    dense_results = (
        list(diagnostics.dense_results)
        if diagnostics is not None
        else dense_hits
    )
    bm25_results = (
        list(diagnostics.bm25_results)
        if diagnostics is not None
        else bm25_hits
    )
    fused_results = (
        list(diagnostics.fused_results) if diagnostics is not None else hits
    )
    rerank_results = (
        list(diagnostics.rerank_results) if diagnostics is not None else hits
    )
    dense_count = (
        diagnostics.dense_count if diagnostics is not None else len(dense_hits)
    )
    bm25_count = diagnostics.bm25_count if diagnostics is not None else 0
    fused_count = diagnostics.fused_count if diagnostics is not None else 0
    rerank_input_count = (
        diagnostics.rerank_input_count if diagnostics is not None else 0
    )
    rerank_output_count = (
        diagnostics.rerank_output_count if diagnostics is not None else 0
    )
    reranker_enabled = (
        diagnostics.reranker_enabled if diagnostics is not None else False
    )
    timings = {
        "dense_retrieval": (
            diagnostics.dense_latency_ms if diagnostics is not None else 0.0
        ),
        "bm25_retrieval": (
            diagnostics.bm25_latency_ms if diagnostics is not None else 0.0
        ),
        "rrf_fusion": (
            diagnostics.fusion_latency_ms if diagnostics is not None else 0.0
        ),
        "rerank": (
            diagnostics.rerank_latency_ms if diagnostics is not None else 0.0
        ),
    }
    rerank_failure = failure_by_stage.get("rerank")
    stages = [
        (
            "dense_retrieval",
            dense_results,
            dense_count,
            retrieval_failures.get("dense"),
            False,
        ),
        (
            "bm25_retrieval",
            bm25_results,
            bm25_count,
            retrieval_failures.get("bm25"),
            diagnostics is not None and diagnostics.mode == "dense",
        ),
        (
            "rrf_fusion",
            fused_results,
            fused_count,
            None,
            diagnostics is not None and diagnostics.mode == "dense",
        ),
        (
            "rerank",
            rerank_results,
            rerank_output_count,
            rerank_failure,
            not reranker_enabled,
        ),
    ]
    for name, stage_hits, count, failure, skipped in stages:
        if (
            name == "rerank"
            and (
                not reranker_enabled
                or (diagnostics is not None and not diagnostics.rerank_entered)
            )
        ):
            continue
        if (
            name == "rrf_fusion"
            and diagnostics is not None
            and not diagnostics.rrf_entered
        ):
            continue
        metadata: dict[str, Any] = {
            "count": count,
            "duration_ms": timings[name],
            "degraded": failure is not None,
            "skipped": skipped,
        }
        if name == "rerank":
            metadata.update(
                {
                    "enabled": reranker_enabled,
                    "input_count": rerank_input_count,
                    "output_count": rerank_output_count,
                }
            )
        if failure is not None:
            metadata.update(
                {
                    "error_type": failure.error_type,
                    "fallback": failure.fallback,
                }
            )
        _record(
            observer,
            token=observations.get(name),
            request_id=request_id,
            name=name,
            kind="span" if name != "rerank" else "generation",
            input={"query": query},
            output={
                "retrieved_chunk_ids": [hit.chunk_id for hit in stage_hits],
                "hits": [_hit_payload(hit) for hit in stage_hits],
            },
            metadata=metadata,
            level="WARNING" if failure is not None else "DEFAULT",
            status_message="degraded" if failure is not None else None,
        )


def _hit_payload(hit: Any) -> dict[str, Any]:
    return {
        "chunk_id": hit.chunk_id,
        "dense_score": hit.dense_score,
        "bm25_score": hit.bm25_score,
        "fused_score": hit.fused_score,
        "rerank_score": hit.rerank_score,
    }


def _source_payload(sources: object) -> list[dict[str, Any]]:
    if not isinstance(sources, list):
        return []
    return [
        source.model_dump()
        for source in sources
        if hasattr(source, "model_dump")
    ]


def _record_terminal_answer(
    observer: TraceObserver | None,
    request_id: str,
    name: str,
    question: str,
    answer: str,
    history_messages: int | None,
    failure: WorkflowFailure,
    *,
    observation: Any = None,
    context_chunk_ids: object = None,
    sources: object = None,
) -> None:
    input_payload: dict[str, Any] = {"question": question}
    if history_messages is not None:
        input_payload["history_messages"] = history_messages
    if isinstance(context_chunk_ids, list):
        input_payload["context_chunk_ids"] = context_chunk_ids
    result = {
        "answer": answer,
        "current_stage": failure.stage,
        "fatal_error": failure,
        "answer_available": True,
        "request_id": request_id,
    }
    _record(
        observer,
        token=observation,
        request_id=request_id,
        name=name,
        kind="generation",
        input=input_payload,
        output={"answer": answer, "sources": _source_payload(sources)},
        metadata={
            "duration_ms": failure.duration_ms,
            "fatal": True,
            "error_type": failure.error_type,
            "fallback": failure.fallback,
        },
        level="ERROR",
        status_message="fatal",
    )
    _finish(observer, request_id, result)


def _request_id(state: AgentState, observer: TraceObserver | None) -> str:
    """Return the local correlation ID, starting one root request if needed."""
    existing = state.get("request_id")
    if isinstance(existing, str) and existing.strip():
        return existing
    if observer is not None:
        try:
            status = observer.start_request()
            if status.request_id is not None:
                return status.request_id
        except Exception:
            pass
    return uuid4().hex


def _tracing_fields(
    observer: TraceObserver | None,
    request_id: str,
) -> dict[str, Any]:
    """Return provider identity separately from the local request ID."""
    if observer is None:
        return {}
    try:
        status = observer.get_status(request_id)
    except Exception:
        return {}
    fields: dict[str, Any] = {"tracing_status": status}
    if status.trace_id is not None:
        fields["trace_id"] = status.trace_id
    return fields


def _record(
    observer: TraceObserver | None,
    **kwargs: Any,
) -> None:
    if observer is None:
        return
    try:
        token = kwargs.pop("token", None)
        if token is None:
            observer.record(**kwargs)
            return
        kwargs.pop("request_id", None)
        kwargs.pop("name", None)
        kwargs.pop("kind", None)
        kwargs.pop("input", None)
        if kwargs.get("level") == "ERROR" and "outcome" not in kwargs:
            kwargs["outcome"] = "failure"
        observer.finish_observation(token, **kwargs)
    except Exception:
        return


def _begin(
    observer: TraceObserver | None,
    request_id: str,
    name: str,
    kind: str,
    *,
    input: dict[str, Any] | None = None,
) -> Any:
    if observer is None:
        return None
    try:
        return observer.start_observation(
            request_id=request_id,
            name=name,
            kind=kind,
            input=input,
        )
    except Exception:
        return None


def _begin_retrieval_observations(
    observer: TraceObserver | None,
    request_id: str,
    query: str,
    retriever: object,
) -> dict[str, Any]:
    """Open configured retrieval stages before the retrieval call starts."""
    names = ["dense_retrieval"]
    if getattr(retriever, "hybrid_enabled", True):
        names.extend(["bm25_retrieval", "rrf_fusion"])
    return {
        name: _begin(
            observer,
            request_id,
            name,
            "generation" if name == "rerank" else "span",
            input={"query": query},
        )
        for name in names
    }


def _finish(
    observer: TraceObserver | None,
    request_id: str,
    state: AgentState,
) -> None:
    if observer is None:
        return
    fatal_error = state.get("fatal_error")
    try:
        status = observer.finish_request(
            request_id,
            output={
                "answer": state.get("answer"),
                "answer_available": state.get("answer_available", False),
            },
            metadata={
                "fatal": fatal_error is not None,
                "current_stage": state.get("current_stage"),
            },
            outcome="failure" if fatal_error is not None else "success",
        )
        state["tracing_status"] = status
        if status.trace_id is not None:
            state["trace_id"] = status.trace_id
    except Exception:
        return


def _retrieval_failures(diagnostics: object) -> list[WorkflowFailure]:
    """Convert retrieval diagnostics into ordered workflow events."""

    if diagnostics is None:
        return []
    failures: list[WorkflowFailure] = []
    path_codes = [
        code
        for code in diagnostics.degradation_codes
        if not code.startswith("reranker_")
    ]
    for index, source in enumerate(diagnostics.degraded_sources):
        code = (
            path_codes[index]
            if index < len(path_codes)
            else f"{source}_retrieval_failed"
        )
        other_count = (
            diagnostics.bm25_count
            if source == "dense"
            else diagnostics.dense_count
        )
        fallback = "remaining_retrieval_path" if other_count else "empty_context"
        latency = (
            diagnostics.dense_latency_ms
            if source == "dense"
            else diagnostics.bm25_latency_ms
        )
        failures.append(
            _failure(
                stage="retrieval",
                error_type=code,
                safe_message=f"{source.upper()} retrieval path failed.",
                degraded=True,
                fatal=False,
                fallback=fallback,
                duration_ms=latency,
                provider=source,
                code=code,
            )
        )
    rerank_code = next(
        (
            code
            for code in diagnostics.degradation_codes
            if code.startswith("reranker_")
        ),
        None,
    )
    if diagnostics.reranker_degraded:
        failures.append(
            _failure(
                stage="rerank",
                error_type=rerank_code or "reranker_failed",
                safe_message="Reranking failed; candidate order was preserved.",
                degraded=True,
                fatal=False,
                fallback="candidate_order",
                duration_ms=diagnostics.rerank_latency_ms,
                provider="reranker",
                code=rerank_code or "reranker_failed",
            )
        )
    return failures


def _failure(
    *,
    stage: WorkflowStage,
    error_type: str,
    safe_message: str,
    degraded: bool,
    fatal: bool,
    fallback: str | None,
    duration_ms: float,
    provider: str | None,
    code: str | None,
) -> WorkflowFailure:
    return WorkflowFailure(
        stage=stage,
        error_type=error_type,
        safe_message=safe_message,
        degraded=degraded,
        fatal=fatal,
        fallback_used=fallback is not None,
        fallback=fallback,
        duration_ms=max(0.0, duration_ms),
        provider=provider,
        code=code,
    )


def _elapsed_ms(started: float) -> float:
    return max(0.0, (perf_counter() - started) * 1000.0)


def _require_question(state: AgentState) -> str:
    question = state.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("Agent state question must be a non-empty string")
    return question.strip()
