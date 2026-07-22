"""Integration tests for HybridRetrievalPipeline inside the Agent graph."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TypeVar

from pydantic import BaseModel

from src.agent.graph import build_graph
from src.agent.state import RewriteResult, RouteDecision
from src.config import Settings
from src.llm.client import ChatMessage
from src.rag.context_builder import ContextBuildResult, ContextBuilder
from src.rag.retrieval import HybridRetrievalPipeline, reciprocal_rank_fusion
from src.rag.schemas import SearchHit


StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)


class WorkflowLLM:
    """Emit deterministic structured workflow decisions and final answers."""

    def __init__(self, events: list[str]) -> None:
        self.events = events

    def generate_structured(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
        response_model: type[StructuredOutputT],
    ) -> StructuredOutputT:
        """Return validated Router or Rewrite output for the current prompt."""
        prompt = _message_text(messages)
        if response_model is RouteDecision:
            self.events.append("route")
            direct = "当前问题：\n这是一个通用问题" in prompt
            return response_model.model_validate(
                {
                    "need_retrieval": not direct,
                    "reason": "通用知识" if direct else "依赖技术文档",
                }
            )
        if response_model is RewriteResult:
            self.events.append("rewrite")
            return response_model.model_validate(
                {"rewritten_query": "LangGraph thread_id checkpoint"}
            )
        raise AssertionError("Unexpected structured response model")

    def generate(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
    ) -> str:
        """Return either a direct or grounded answer by prompt role."""
        prompt = _message_text(messages)
        if "通用问答助手" in prompt:
            self.events.append("direct")
            return "直接回答。"
        self.events.append("generate")
        return "checkpoint 使用 thread_id [S1]。"


class EventRetriever:
    """Record retrieval order and return one configured ranking."""

    def __init__(
        self,
        source: str,
        events: list[str],
        hits: list[SearchHit],
    ) -> None:
        self.source = source
        self.events = events
        self.hits = hits
        self.queries: list[str] = []

    def retrieve(self, query: str) -> list[SearchHit]:
        """Record the rewritten query and return configured hits."""
        self.events.append(self.source)
        self.queries.append(query)
        return list(self.hits)


class EventContextBuilder:
    """Record context construction before delegating to ContextBuilder."""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.delegate = ContextBuilder()

    def build(self, hits: list[SearchHit]) -> ContextBuildResult:
        """Record and construct citation-aware context."""
        self.events.append("context")
        return self.delegate.build(hits)


class EventFusion:
    """Record fusion between retrieval and context construction."""

    def __init__(self, events: list[str]) -> None:
        self.events = events

    def __call__(
        self,
        dense_hits: Sequence[SearchHit],
        bm25_hits: Sequence[SearchHit],
        *,
        k: int,
        top_n: int | None,
    ) -> list[SearchHit]:
        """Record and delegate to production RRF."""
        self.events.append("fusion")
        return reciprocal_rank_fusion(
            dense_hits, bm25_hits, k=k, top_n=top_n
        )


def _message_text(
    messages: Sequence[ChatMessage | Mapping[str, object]],
) -> str:
    parts: list[str] = []
    for message in messages:
        if isinstance(message, ChatMessage):
            parts.append(message.content)
        else:
            content = message.get("content")
            if isinstance(content, str):
                parts.append(content)
    return "\n".join(parts)


def _hit(
    *,
    dense_score: float | None = None,
    bm25_score: float | None = None,
) -> SearchHit:
    return SearchHit(
        chunk_id="checkpoint-1",
        text="LangGraph checkpoint 使用 thread_id 保存状态。",
        metadata={
            "source": "langgraph.md",
            "source_type": "markdown",
            "section": "Checkpoint",
            "heading_path": ["Persistence", "Checkpoint"],
            "content_hash": "checkpoint-hash",
        },
        dense_score=dense_score,
        bm25_score=bm25_score,
    )


def _pipeline(
    events: list[str],
) -> tuple[HybridRetrievalPipeline, EventRetriever, EventRetriever]:
    dense = EventRetriever("dense", events, [_hit(dense_score=0.91)])
    bm25 = EventRetriever("bm25", events, [_hit(bm25_score=4.2)])
    pipeline = HybridRetrievalPipeline(
        dense,
        bm25,
        settings=Settings(_env_file=None),
        fusion=EventFusion(events),
    )
    return pipeline, dense, bm25


def test_rag_branch_uses_rewritten_query_and_preserves_source_mapping() -> None:
    events: list[str] = []
    pipeline, dense, bm25 = _pipeline(events)
    graph = build_graph(
        WorkflowLLM(events),
        pipeline,
        EventContextBuilder(events),
    )

    result = graph.invoke({"question": "文档中的状态机制如何配置？"})

    expected_query = "LangGraph thread_id checkpoint"
    assert dense.queries == [expected_query]
    assert bm25.queries == [expected_query]
    assert events == [
        "route",
        "rewrite",
        "dense",
        "bm25",
        "fusion",
        "context",
        "generate",
    ]
    hit = result["retrieved_documents"][0]
    assert hit.dense_score == 0.91
    assert hit.bm25_score == 4.2
    assert hit.fused_score is not None
    assert result["context_chunk_ids"] == ["checkpoint-1"]
    assert result["context_sources"][0].chunk_id == "checkpoint-1"
    assert result["context_sources"][0].citation_id == "S1"
    assert "[S1] langgraph.md | section Checkpoint" in result["context"]


def test_direct_branch_does_not_call_pipeline_retrievers_or_fusion() -> None:
    events: list[str] = []
    pipeline, dense, bm25 = _pipeline(events)
    graph = build_graph(WorkflowLLM(events), pipeline)

    result = graph.invoke({"question": "这是一个通用问题"})

    assert result["answer"] == "直接回答。"
    assert dense.queries == []
    assert bm25.queries == []
    assert events == ["route", "direct"]
