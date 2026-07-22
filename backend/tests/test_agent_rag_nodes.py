"""Offline tests for dense retrieval and grounded answer Agent nodes."""

from collections.abc import Mapping, Sequence

from src.agent.nodes import generate_answer, retrieve
from src.llm.client import ChatMessage
from src.rag.context_builder import ContextBuildResult, ContextBuilder
from src.rag.schemas import SearchHit
from src.rag.service import NO_EVIDENCE_ANSWER


class FakeRetriever:
    """Return configured search hits and record retrieval queries."""

    def __init__(self, hits: list[SearchHit]) -> None:
        self.hits = hits
        self.queries: list[str] = []

    def retrieve(self, query: str) -> list[SearchHit]:
        self.queries.append(query)
        return list(self.hits)


class RecordingContextBuilder:
    """Record hits before delegating to the existing ContextBuilder."""

    def __init__(self) -> None:
        self.calls: list[list[SearchHit]] = []
        self.builder = ContextBuilder()

    def build(self, hits: list[SearchHit]) -> ContextBuildResult:
        self.calls.append(list(hits))
        return self.builder.build(hits)


class FakeLLM:
    """Return a fixed answer and record messages without external calls."""

    def __init__(self, answer: str = "状态由 checkpointer 保存 [S1]。") -> None:
        self.answer = answer
        self.calls: list[list[ChatMessage | Mapping[str, object]]] = []

    def generate(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
    ) -> str:
        self.calls.append(list(messages))
        return self.answer


def _hits() -> list[SearchHit]:
    return [
        SearchHit(
            chunk_id="md-2",
            text="Checkpoint 按 thread 保存图状态。",
            metadata={
                "source": "langgraph.md",
                "source_type": "markdown",
                "section": "Checkpoint",
                "heading_path": ["Persistence", "Checkpoint"],
            },
            dense_score=0.92,
        ),
        SearchHit(
            chunk_id="pdf-1",
            text="持久化配置记录在手册第四页。",
            metadata={
                "source": "manual.pdf",
                "source_type": "pdf",
                "page": 4,
            },
            dense_score=0.81,
        ),
    ]


def _message_text(messages: list[ChatMessage | Mapping[str, object]]) -> str:
    parts: list[str] = []
    for message in messages:
        if isinstance(message, ChatMessage):
            parts.append(message.content)
        else:
            content = message.get("content")
            if isinstance(content, str):
                parts.append(content)
    return "\n".join(parts)


def test_retrieve_uses_rewritten_query_and_preserves_ranked_hits() -> None:
    hits = _hits()
    retriever = FakeRetriever(hits)
    context_builder = RecordingContextBuilder()

    result = retrieve(
        {
            "question": "它如何保存状态？",
            "rewritten_query": "  LangGraph checkpoint 如何保存状态？  ",
        },
        retriever,
        context_builder,
    )

    assert retriever.queries == ["LangGraph checkpoint 如何保存状态？"]
    assert context_builder.calls == [hits]
    assert result["retrieved_documents"] == hits
    assert [
        hit.chunk_id for hit in result["retrieved_documents"]
    ] == ["md-2", "pdf-1"]
    assert result["retrieved_documents"][0].metadata == hits[0].metadata
    assert result["retrieved_documents"][1].metadata["page"] == 4
    assert "[S1] langgraph.md | section Checkpoint" in result["context"]
    assert "[S2] manual.pdf | page 4" in result["context"]
    assert set(result) == {"retrieved_documents", "context"}


def test_retrieve_falls_back_to_original_question_without_valid_rewrite() -> None:
    retriever = FakeRetriever(_hits())

    retrieve({"question": "  原始用户问题  "}, retriever)
    retrieve(
        {"question": "  原始用户问题  ", "rewritten_query": "   "},
        retriever,
    )

    assert retriever.queries == ["原始用户问题", "原始用户问题"]


def test_generate_answer_uses_original_question_and_built_context() -> None:
    retrieval_state = retrieve(
        {
            "question": "原始问题：它如何保存状态？",
            "rewritten_query": "LangGraph checkpoint 如何保存状态？",
        },
        FakeRetriever(_hits()),
    )
    llm = FakeLLM()

    result = generate_answer(
        {
            "question": "原始问题：它如何保存状态？",
            **retrieval_state,
        },
        llm,
    )

    assert result == {"answer": "状态由 checkpointer 保存 [S1]。"}
    assert len(llm.calls) == 1
    sent_text = _message_text(llm.calls[0])
    assert "原始问题：它如何保存状态？" in sent_text
    assert "LangGraph checkpoint 如何保存状态？" not in sent_text
    assert "Checkpoint 按 thread 保存图状态。" in sent_text
    assert "[S1]" in sent_text
    assert set(result) == {"answer"}


def test_empty_retrieval_is_stable_and_does_not_call_llm() -> None:
    retriever = FakeRetriever([])
    context_builder = RecordingContextBuilder()
    retrieval_state = retrieve(
        {"question": "没有相关资料的问题"},
        retriever,
        context_builder,
    )
    llm = FakeLLM()

    answer_state = generate_answer(
        {"question": "没有相关资料的问题", **retrieval_state},
        llm,
    )

    assert retrieval_state == {"retrieved_documents": [], "context": ""}
    assert context_builder.calls == [[]]
    assert answer_state == {"answer": NO_EVIDENCE_ANSWER}
    assert llm.calls == []


def test_generate_answer_does_not_mutate_retrieved_documents() -> None:
    hits = _hits()
    llm = FakeLLM()
    state = {
        "question": "如何保存状态？",
        "context": ContextBuilder().build(hits).context,
        "retrieved_documents": hits,
    }

    generate_answer(state, llm)

    assert state["retrieved_documents"] == hits
    assert [hit.metadata for hit in state["retrieved_documents"]] == [
        hit.metadata for hit in hits
    ]
