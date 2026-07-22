"""Deterministic integration tests for the compiled adaptive RAG graph."""

from collections.abc import Mapping, Sequence
from typing import TypeVar

import pytest
from pydantic import BaseModel

from src.agent.graph import build_graph
from src.agent.nodes import ROUTER_PARSE_FAILURE_REASON
from src.llm.client import ChatMessage, parse_structured_output
from src.rag.schemas import SearchHit
from src.rag.service import NO_EVIDENCE_ANSWER


StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)


class WorkflowLLM:
    """Emulate each LLM stage and append its observable workflow event."""

    def __init__(
        self,
        events: list[str],
        *,
        invalid_router: bool = False,
        invalid_rewrite: bool = False,
    ) -> None:
        self.events = events
        self.invalid_router = invalid_router
        self.invalid_rewrite = invalid_rewrite
        self.calls: list[list[ChatMessage | Mapping[str, object]]] = []

    def generate(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
    ) -> str:
        copied = list(messages)
        self.calls.append(copied)
        text = _message_text(copied)

        if "检索路由器" in text:
            self.events.append("route")
            if self.invalid_router:
                return "invalid router output"
            needs_retrieval = any(
                f"当前问题：\n{marker}" in text
                for marker in ("我上传的", "上面提到的")
            )
            reason = "依赖当前文档或上下文" if needs_retrieval else "通用知识问题"
            boolean = "true" if needs_retrieval else "false"
            return (
                f'{{"need_retrieval": {boolean}, '
                f'"reason": "{reason}"}}'
            )

        if "检索查询改写器" in text:
            self.events.append("rewrite")
            if self.invalid_rewrite:
                return '{"rewritten_query": "   "}'
            if "上面提到的状态保存机制" in text:
                query = "LangGraph checkpoint 状态保存机制有哪些限制？"
            else:
                query = "LangGraph 文档中如何配置 checkpoint？"
            return f'{{"rewritten_query": "{query}"}}'

        if "通用问答助手" in text:
            self.events.append("direct")
            return "这是无需检索的通用回答。"

        if "严谨的技术文档问答助手" in text:
            self.events.append("generate")
            return "根据文档，checkpoint 保存图状态 [S1]。"

        raise AssertionError("Unexpected LLM prompt")

    def generate_structured(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
        response_model: type[StructuredOutputT],
    ) -> StructuredOutputT:
        """Run workflow text through the production structured parser."""
        return parse_structured_output(self.generate(messages), response_model)


class WorkflowRetriever:
    """Return fixed dense hits while recording query and workflow order."""

    def __init__(self, events: list[str], hits: list[SearchHit]) -> None:
        self.events = events
        self.hits = hits
        self.queries: list[str] = []

    def retrieve(self, query: str) -> list[SearchHit]:
        self.events.append("retrieve")
        self.queries.append(query)
        return list(self.hits)


def _hit() -> SearchHit:
    return SearchHit(
        chunk_id="checkpoint-1",
        text="LangGraph checkpoint 按 thread 保存图状态。",
        metadata={
            "source": "langgraph_checkpoint.md",
            "source_type": "markdown",
            "section": "Checkpoint",
            "heading_path": ["Persistence", "Checkpoint"],
        },
        dense_score=0.94,
    )


def _message_text(
    messages: list[ChatMessage | Mapping[str, object]],
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


@pytest.mark.parametrize(
    "question",
    [
        "什么是 RAG？",
        "请解释 Python list 和 tuple 的区别。",
    ],
)
def test_direct_questions_never_enter_rewrite_or_retrieval(question: str) -> None:
    events: list[str] = []
    llm = WorkflowLLM(events)
    retriever = WorkflowRetriever(events, [_hit()])
    graph = build_graph(llm, retriever)

    result = graph.invoke({"question": question, "chat_history": []})

    assert result["need_retrieval"] is False
    assert result["route_reason"] == "通用知识问题"
    assert result["answer"] == "这是无需检索的通用回答。"
    assert "rewritten_query" not in result
    assert "retrieved_documents" not in result
    assert retriever.queries == []
    assert events == ["route", "direct"]


@pytest.mark.parametrize(
    ("question", "history", "expected_query"),
    [
        (
            "我上传的 LangGraph 文档中如何配置 checkpoint？",
            [],
            "LangGraph 文档中如何配置 checkpoint？",
        ),
        (
            "上面提到的状态保存机制有什么限制？",
            [
                {
                    "role": "user",
                    "content": "LangGraph checkpoint 如何保存状态？",
                }
            ],
            "LangGraph checkpoint 状态保存机制有哪些限制？",
        ),
    ],
)
def test_document_questions_follow_ordered_rag_branch(
    question: str,
    history: list[dict[str, str]],
    expected_query: str,
) -> None:
    events: list[str] = []
    llm = WorkflowLLM(events)
    retriever = WorkflowRetriever(events, [_hit()])
    graph = build_graph(llm, retriever)

    result = graph.invoke({"question": question, "chat_history": history})

    assert result["need_retrieval"] is True
    assert result["route_reason"] == "依赖当前文档或上下文"
    assert result["rewritten_query"] == expected_query
    assert retriever.queries == [expected_query]
    assert [hit.chunk_id for hit in result["retrieved_documents"]] == [
        "checkpoint-1"
    ]
    assert result["context_chunk_ids"] == ["checkpoint-1"]
    assert [source.model_dump() for source in result["context_sources"]] == [
        {
            "citation_id": "S1",
            "citation": "langgraph_checkpoint.md | section Checkpoint",
            "chunk_id": "checkpoint-1",
            "source": "langgraph_checkpoint.md",
            "source_type": "markdown",
            "page": None,
            "section": "Checkpoint",
            "heading_path": ["Persistence", "Checkpoint"],
        }
    ]
    assert "[S1] langgraph_checkpoint.md | section Checkpoint" in result["context"]
    assert result["answer"] == "根据文档，checkpoint 保存图状态 [S1]。"
    assert events == ["route", "rewrite", "retrieve", "generate"]


def test_invalid_router_output_conservatively_enters_rag_branch() -> None:
    events: list[str] = []
    llm = WorkflowLLM(events, invalid_router=True)
    retriever = WorkflowRetriever(events, [_hit()])
    graph = build_graph(llm, retriever)

    result = graph.invoke({"question": "无法分类的问题"})

    assert result["need_retrieval"] is True
    assert result["route_reason"] == ROUTER_PARSE_FAILURE_REASON
    assert events == ["route", "rewrite", "retrieve", "generate"]


def test_invalid_rewrite_output_falls_back_to_original_question() -> None:
    events: list[str] = []
    question = "我上传的文档中 checkpoint 有什么限制？"
    llm = WorkflowLLM(events, invalid_rewrite=True)
    retriever = WorkflowRetriever(events, [_hit()])
    graph = build_graph(llm, retriever)

    result = graph.invoke({"question": question})

    assert result["rewritten_query"] == question
    assert retriever.queries == [question]
    assert events == ["route", "rewrite", "retrieve", "generate"]


def test_empty_retrieval_returns_no_evidence_without_generation() -> None:
    events: list[str] = []
    llm = WorkflowLLM(events)
    retriever = WorkflowRetriever(events, [])
    graph = build_graph(llm, retriever)

    result = graph.invoke(
        {"question": "我上传的 LangGraph 文档中如何配置 checkpoint？"}
    )

    assert result["need_retrieval"] is True
    assert result["retrieved_documents"] == []
    assert result["context"] == ""
    assert result["context_sources"] == []
    assert result["context_chunk_ids"] == []
    assert result["answer"] == NO_EVIDENCE_ANSWER
    assert events == ["route", "rewrite", "retrieve"]
