"""Failure-matrix tests for the observable Agent workflow contract."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TypeVar

import pytest
from pydantic import BaseModel

from src.agent.graph import build_graph
from src.agent.nodes import (
    CHAT_HISTORY_MAX_CHARS,
    CHAT_HISTORY_MAX_MESSAGES,
    SAFE_WORKFLOW_ERROR_ANSWER,
    bounded_chat_history,
    direct_answer,
    rewrite_query,
    route_query,
)
from src.agent.state import RewriteResult, RouteDecision
from src.llm.client import ChatMessage
from src.llm.exceptions import LLMResponseError, LLMTimeoutError
from src.rag.context_builder import ContextBuildError
from src.rag.embeddings.exceptions import EmbeddingRequestError
from src.rag.retrieval import HybridRetrievalPipeline, RerankerRequestError
from src.rag.schemas import SearchHit
from src.rag.service import NO_EVIDENCE_ANSWER


StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)
SECRET = "sk-private-must-never-appear"


class FailureLLM:
    """Provide deterministic stage outputs or recognized LLM failures."""

    def __init__(self, failures: set[str] | None = None) -> None:
        self.failures = failures or set()
        self.generated_stages: list[str] = []
        self.messages: list[list[ChatMessage | Mapping[str, object]]] = []

    def generate_structured(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
        response_model: type[StructuredOutputT],
    ) -> StructuredOutputT:
        self.messages.append(list(messages))
        if response_model is RouteDecision:
            self.generated_stages.append("router")
            if "router" in self.failures:
                raise LLMTimeoutError(f"timeout {SECRET}")
            return response_model.model_validate(
                {"need_retrieval": True, "reason": "document question"}
            )
        self.generated_stages.append("rewrite")
        if "rewrite" in self.failures:
            raise LLMTimeoutError(f"timeout {SECRET}")
        return response_model.model_validate({"rewritten_query": "standalone query"})

    def generate(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
    ) -> str:
        copied = list(messages)
        self.messages.append(copied)
        text = "\n".join(_content(message) for message in copied)
        stage = "direct" if "通用问答助手" in text else "generation"
        self.generated_stages.append(stage)
        if stage in self.failures:
            raise LLMTimeoutError(f"timeout {SECRET}")
        return "safe answer [S1]" if stage == "generation" else "direct answer"


class PathRetriever:
    """Return one path result or emulate a recognized external request failure."""

    def __init__(self, hits: list[SearchHit], *, fail: bool = False) -> None:
        self.hits = hits
        self.fail = fail

    def retrieve(self, query: str, *, top_n: int | None = None) -> list[SearchHit]:
        if self.fail:
            raise EmbeddingRequestError(f"provider failure {SECRET}")
        return list(self.hits if top_n is None else self.hits[:top_n])


class FailedReranker:
    """Emulate a reranker request failure without exposing its detail."""

    def rerank(self, query: str, hits: Sequence[SearchHit]) -> list[SearchHit]:
        raise RerankerRequestError(f"rerank timeout {SECRET}")


class FailedContextBuilder:
    """Emulate a recognized context construction failure."""

    def build(self, hits: list[SearchHit]):
        raise ContextBuildError(f"document content {SECRET}")


def _hit(chunk_id: str, *, source: str) -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        text=f"full private document text for {chunk_id}",
        metadata={"source": source},
        dense_score=0.9 if source == "dense" else None,
        bm25_score=3.0 if source == "bm25" else None,
    )


def _pipeline(
    *,
    dense_fail: bool = False,
    bm25_fail: bool = False,
    reranker_fail: bool = False,
) -> HybridRetrievalPipeline:
    return HybridRetrievalPipeline(
        PathRetriever([_hit("dense", source="dense")], fail=dense_fail),
        PathRetriever([_hit("bm25", source="bm25")], fail=bm25_fail),
        reranker=FailedReranker() if reranker_fail else None,
        hybrid_enabled=True,
        reranker_enabled=reranker_fail,
        dense_top_n=2,
        bm25_top_n=2,
        retrieve_top_n=2,
        rerank_top_k=2,
    )


@pytest.mark.parametrize("stage", ["router", "rewrite"])
def test_llm_timeout_fallbacks_are_safe_and_continue(stage: str) -> None:
    llm = FailureLLM({stage})
    result = build_graph(llm, _pipeline()).invoke({"question": "document?"})

    assert result["answer"] == "safe answer [S1]"
    event = result["degradation_events"][0]
    assert event.stage == stage
    assert event.error_type == "timeout"
    assert event.degraded is True
    assert event.fatal is False
    assert event.fallback_used is True
    assert SECRET not in event.model_dump_json()


@pytest.mark.parametrize(
    ("dense_fail", "bm25_fail", "failed_source", "remaining_id"),
    [
        (True, False, "dense", "bm25"),
        (False, True, "bm25", "dense"),
    ],
)
def test_single_retrieval_path_failure_uses_the_remaining_path(
    dense_fail: bool,
    bm25_fail: bool,
    failed_source: str,
    remaining_id: str,
) -> None:
    result = build_graph(
        FailureLLM(),
        _pipeline(dense_fail=dense_fail, bm25_fail=bm25_fail),
    ).invoke({"question": "document?"})

    assert [hit.chunk_id for hit in result["retrieved_documents"]] == [remaining_id]
    event = result["degradation_events"][0]
    assert event.error_type == f"{failed_source}_retrieval_failed"
    assert event.fallback == "remaining_retrieval_path"
    assert result["answer_available"] is True


def test_both_retrieval_paths_fail_without_context_or_generation() -> None:
    llm = FailureLLM()
    result = build_graph(
        llm,
        _pipeline(dense_fail=True, bm25_fail=True),
    ).invoke({"question": "document?"})

    assert result["retrieved_documents"] == []
    assert result["context"] == ""
    assert result["context_sources"] == []
    assert result["answer"] == NO_EVIDENCE_ANSWER
    assert "generation" not in llm.generated_stages
    assert [event.stage for event in result["degradation_events"]] == [
        "retrieval",
        "retrieval",
    ]


def test_reranker_failure_preserves_fused_order_and_records_event() -> None:
    expected_ids = [
        hit.chunk_id for hit in _pipeline().retrieve("standalone query")
    ]
    result = build_graph(
        FailureLLM(),
        _pipeline(reranker_fail=True),
    ).invoke({"question": "document?"})

    ids = [hit.chunk_id for hit in result["retrieved_documents"]]
    assert ids == expected_ids
    assert all(hit.rerank_score is None for hit in result["retrieved_documents"])
    event = result["degradation_events"][0]
    assert event.stage == "rerank"
    assert event.fallback == "candidate_order"
    assert SECRET not in event.model_dump_json()


def test_context_failure_is_fatal_and_stops_generation() -> None:
    llm = FailureLLM()
    result = build_graph(
        llm,
        _pipeline(),
        FailedContextBuilder(),
    ).invoke({"question": "document?"})

    assert "generation" not in llm.generated_stages
    assert result["answer"] == SAFE_WORKFLOW_ERROR_ANSWER
    assert result["context"] == ""
    assert result["context_sources"] == []
    assert result["fatal_error"].stage == "context"
    assert result["fatal_error"].fatal is True
    assert SECRET not in result["fatal_error"].model_dump_json()


def test_generation_timeout_returns_safe_fatal_result() -> None:
    llm = FailureLLM({"generation"})
    result = build_graph(llm, _pipeline()).invoke({"question": "document?"})

    assert result["answer"] == SAFE_WORKFLOW_ERROR_ANSWER
    assert result["answer_available"] is True
    assert result["fatal_error"].stage == "generation"
    assert result["fatal_error"].error_type == "timeout"
    serialized = result["fatal_error"].model_dump_json()
    assert SECRET not in serialized
    assert "full private document text" not in serialized


def test_degradation_events_keep_workflow_order() -> None:
    llm = FailureLLM({"router", "rewrite"})
    result = build_graph(
        llm,
        _pipeline(dense_fail=True, reranker_fail=True),
    ).invoke({"question": "document?"})

    assert [event.stage for event in result["degradation_events"]] == [
        "router",
        "rewrite",
        "retrieval",
        "rerank",
    ]


def test_all_conversational_nodes_share_the_bounded_history_window() -> None:
    history = [
        {"role": "user", "content": f"history-{index}-" + "x" * 900}
        for index in range(CHAT_HISTORY_MAX_MESSAGES + 3)
    ]
    expected = bounded_chat_history(history)
    assert len(expected) <= CHAT_HISTORY_MAX_MESSAGES
    assert sum(len(item["content"]) for item in expected) <= CHAT_HISTORY_MAX_CHARS

    router_llm = FailureLLM()
    route_query({"question": "q", "chat_history": history}, router_llm)
    rewrite_llm = FailureLLM()
    rewrite_query({"question": "q", "chat_history": history}, rewrite_llm)
    direct_llm = FailureLLM()
    direct_answer({"question": "q", "chat_history": history}, direct_llm)

    router_text = _content(router_llm.messages[0][0])
    rewrite_text = _content(rewrite_llm.messages[0][0])
    for item in expected:
        assert item["content"] in router_text
        assert item["content"] in rewrite_text
    direct_history = direct_llm.messages[0][1:-1]
    assert [
        {"role": message.role, "content": message.content}
        for message in direct_history
        if isinstance(message, ChatMessage)
    ] == expected
    assert "history-0-" not in router_text
    assert "history-0-" not in rewrite_text


def test_invalid_json_failures_are_classified_as_invalid_response() -> None:
    class InvalidStructuredLLM(FailureLLM):
        def generate_structured(self, messages, response_model):
            raise LLMResponseError(f"invalid JSON {SECRET}")

    router = route_query({"question": "q"}, InvalidStructuredLLM())
    rewrite = rewrite_query({"question": "q"}, InvalidStructuredLLM())

    assert router["degradation_events"][0].error_type == "invalid_response"
    assert rewrite["degradation_events"][0].error_type == "invalid_response"
    assert router["need_retrieval"] is True
    assert rewrite["rewritten_query"] == "q"


def _content(message: ChatMessage | Mapping[str, object]) -> str:
    if isinstance(message, ChatMessage):
        return message.content
    content = message.get("content")
    return content if isinstance(content, str) else ""
