"""Offline tests for the basic retrieval-augmented answer service."""

from collections.abc import Mapping, Sequence

import pytest

from src.llm import ChatMessage, LLMRequestError
from src.rag.context_builder import ContextBuildResult, ContextBuilder
from src.rag.schemas import SearchHit
from src.rag.service import (
    NO_EVIDENCE_ANSWER,
    BasicRAGService,
    RAGGenerationError,
    RAGInputError,
)


class FakeRetriever:
    def __init__(self, hits: list[SearchHit]) -> None:
        self.hits = hits
        self.queries: list[str] = []

    def retrieve(self, query: str) -> list[SearchHit]:
        self.queries.append(query)
        return list(self.hits)


class RecordingContextBuilder:
    def __init__(self, builder: ContextBuilder | None = None) -> None:
        self.builder = builder or ContextBuilder()
        self.calls: list[list[SearchHit]] = []

    def build(self, hits: list[SearchHit]) -> ContextBuildResult:
        self.calls.append(list(hits))
        return self.builder.build(hits)


class FakeLLM:
    def __init__(
        self,
        *,
        answer: str = "Checkpoint state is persisted [S1].",
        error: LLMRequestError | None = None,
    ) -> None:
        self.answer = answer
        self.error = error
        self.calls: list[Sequence[ChatMessage | Mapping[str, object]]] = []

    def generate(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
    ) -> str:
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        return self.answer


def _hit(
    chunk_id: str,
    text: str,
    *,
    source: str,
    source_type: str,
    page: int | None = None,
    section: str | None = None,
    heading_path: list[str] | None = None,
) -> SearchHit:
    metadata: dict[str, object] = {
        "source": source,
        "source_type": source_type,
        "content_hash": f"hash-{chunk_id}",
    }
    if page is not None:
        metadata["page"] = page
    if section is not None:
        metadata["section"] = section
    if heading_path is not None:
        metadata["heading_path"] = heading_path
    return SearchHit(chunk_id=chunk_id, text=text, metadata=metadata)


def _mixed_hits() -> list[SearchHit]:
    return [
        _hit(
            "md-1",
            "A checkpointer saves graph state by thread.",
            source="langgraph.md",
            source_type="markdown",
            section="Checkpoint",
            heading_path=["Persistence", "Checkpoint"],
        ),
        _hit(
            "pdf-1",
            "The persistence guide describes stored metadata.",
            source="manual.pdf",
            source_type="pdf",
            page=4,
        ),
    ]


def test_service_calls_retriever_context_builder_and_llm() -> None:
    retriever = FakeRetriever(_mixed_hits())
    context_builder = RecordingContextBuilder()
    llm = FakeLLM()
    service = BasicRAGService(
        retriever,
        llm,
        context_builder=context_builder,
    )

    result = service.answer(" How is checkpoint state saved? ")

    assert retriever.queries == ["How is checkpoint state saved?"]
    assert [hit.chunk_id for hit in context_builder.calls[0]] == [
        "md-1",
        "pdf-1",
    ]
    assert len(llm.calls) == 1
    assert result.answer == "Checkpoint state is persisted [S1]."
    assert result.retrieved_chunk_ids == ["md-1", "pdf-1"]


def test_prompt_separates_question_context_and_citation_rules() -> None:
    llm = FakeLLM()
    service = BasicRAGService(FakeRetriever(_mixed_hits()), llm)

    service.answer("How is checkpoint state saved?")

    messages = llm.calls[0]
    assert isinstance(messages[0], ChatMessage)
    assert isinstance(messages[1], ChatMessage)
    system_prompt = messages[0].content
    user_prompt = messages[1].content
    assert "只依据" in system_prompt
    assert "不得伪造" in system_prompt
    assert "[S1]" in system_prompt
    assert "--- 检索上下文开始 ---" in user_prompt
    assert "[S1] langgraph.md | section Checkpoint" in user_prompt
    assert "[S2] manual.pdf | page 4" in user_prompt
    assert "--- 用户问题开始 ---" in user_prompt
    assert "How is checkpoint state saved?" in user_prompt


def test_response_preserves_markdown_and_pdf_source_locations() -> None:
    result = BasicRAGService(
        FakeRetriever(_mixed_hits()),
        FakeLLM(),
    ).answer("question")

    markdown, pdf = result.sources
    assert markdown.chunk_id == "md-1"
    assert markdown.source == "langgraph.md"
    assert markdown.section == "Checkpoint"
    assert markdown.heading_path == ["Persistence", "Checkpoint"]
    assert pdf.chunk_id == "pdf-1"
    assert pdf.source == "manual.pdf"
    assert pdf.page == 4


def test_no_retrieval_results_return_fixed_answer_without_llm() -> None:
    context_builder = RecordingContextBuilder()
    llm = FakeLLM()
    result = BasicRAGService(
        FakeRetriever([]),
        llm,
        context_builder=context_builder,
    ).answer("unknown question")

    assert result.answer == NO_EVIDENCE_ANSWER
    assert result.sources == []
    assert result.retrieved_chunk_ids == []
    assert context_builder.calls == [[]]
    assert llm.calls == []


def test_unusable_context_returns_no_evidence_without_llm() -> None:
    llm = FakeLLM()
    result = BasicRAGService(
        FakeRetriever(
            [
                _hit(
                    "blank",
                    "   ",
                    source="blank.md",
                    source_type="markdown",
                )
            ]
        ),
        llm,
    ).answer("question")

    assert result.answer == NO_EVIDENCE_ANSWER
    assert llm.calls == []


def test_top_k_limits_candidates_before_context_construction() -> None:
    context_builder = RecordingContextBuilder()
    result = BasicRAGService(
        FakeRetriever(_mixed_hits()),
        FakeLLM(),
        context_builder=context_builder,
    ).answer("question", top_k=1)

    assert [hit.chunk_id for hit in context_builder.calls[0]] == ["md-1"]
    assert result.retrieved_chunk_ids == ["md-1"]
    assert [source.citation_id for source in result.sources] == ["S1"]


def test_llm_failure_is_wrapped_and_retains_root_cause() -> None:
    root_error = LLMRequestError("synthetic upstream failure")
    service = BasicRAGService(
        FakeRetriever(_mixed_hits()),
        FakeLLM(error=root_error),
    )

    with pytest.raises(RAGGenerationError, match="Unable to generate") as error:
        service.answer("question")

    assert error.value.__cause__ is root_error


@pytest.mark.parametrize("question", ["", "   ", "\n\t"])
def test_blank_question_is_rejected_before_dependencies(question: str) -> None:
    retriever = FakeRetriever(_mixed_hits())
    llm = FakeLLM()
    service = BasicRAGService(retriever, llm)

    with pytest.raises(RAGInputError, match="Question"):
        service.answer(question)

    assert retriever.queries == []
    assert llm.calls == []


@pytest.mark.parametrize("top_k", [0, -1, 1.5, True])
def test_invalid_top_k_is_rejected_before_retrieval(top_k: int) -> None:
    retriever = FakeRetriever(_mixed_hits())
    service = BasicRAGService(retriever, FakeLLM())

    with pytest.raises(RAGInputError, match="top_k"):
        service.answer("question", top_k=top_k)  # type: ignore[arg-type]

    assert retriever.queries == []
