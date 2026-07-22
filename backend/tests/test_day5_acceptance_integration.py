"""Complete offline Day5 restart-to-answer acceptance integration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from src.agent.graph import build_graph
from src.agent.state import RewriteResult, RouteDecision
from src.config import Settings
from src.llm.client import ChatMessage
from src.observability import FakeTraceObserver, TracingPolicy
from src.rag.runtime import build_retrieval_runtime
from src.rag.schemas import Chunk, SearchHit
from src.rag.vectorstore import ChromaVectorStore
from tests.fakes import FakeEmbeddingClient


StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)


class AcceptanceLLM:
    """Drive the RAG branch and return one citation-aware answer offline."""

    def generate_structured(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
        response_model: type[StructuredOutputT],
    ) -> StructuredOutputT:
        if response_model is RouteDecision:
            return response_model.model_validate(
                {"need_retrieval": True, "reason": "document-specific question"}
            )
        return response_model.model_validate(
            {"rewritten_query": "LangGraph thread_id checkpoint"}
        )

    def generate(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
    ) -> str:
        return "thread_id 用于隔离每条线程的 checkpoint 状态 [S1]。"


class KeywordPromotingReranker:
    """Promote the exact technical identifier through the real pipeline hook."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def rerank(self, query: str, hits: list[SearchHit]) -> list[SearchHit]:
        self.calls.append([hit.chunk_id for hit in hits])
        ranked = sorted(
            hits,
            key=lambda hit: ("thread_id" not in hit.text, hit.chunk_id),
        )
        return [
            hit.model_copy(
                update={"rerank_score": 0.99 - index * 0.1},
                deep=True,
            )
            for index, hit in enumerate(ranked)
        ]


def _chunk(chunk_id: str, text: str, index: int, section: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id="day5-acceptance",
        text=text,
        chunk_index=index,
        source="langgraph_acceptance.md",
        source_type="markdown",
        section=section,
        heading_path=["Persistence", section],
        chunk_strategy="markdown_heading",
        content_hash=f"hash-{chunk_id}",
    )


def test_restart_hybrid_rerank_graph_trace_and_sources(tmp_path: Path) -> None:
    persist_dir = tmp_path / "persistent_chroma"
    collection = "day5_acceptance"
    chunks = [
        _chunk(
            "thread-id",
            "thread_id identifies the checkpoint namespace for graph state.",
            0,
            "Thread identity",
        ),
        _chunk(
            "semantic-distractor",
            "Checkpoint persistence stores state between graph executions.",
            1,
            "Persistence overview",
        ),
        _chunk(
            "thread-pool-distractor",
            "A thread pool schedules concurrent worker functions.",
            2,
            "Concurrency",
        ),
    ]
    with ChromaVectorStore(
        persist_dir=persist_dir,
        collection_name=collection,
    ) as initial_store:
        initial_store.upsert_chunks(
            chunks,
            [[1.0, 0.0], [0.0, 1.0], [0.2, 0.8]],
        )

    settings = Settings(
        _env_file=None,
        chroma_persist_dir=persist_dir,
        chroma_collection=collection,
        dense_top_n=3,
        bm25_top_n=3,
        retrieve_top_n=3,
        reranker_enabled=True,
        rerank_top_k=2,
    )
    embedder = FakeEmbeddingClient(
        vectors_by_token={"thread_id": [0.0, 1.0]},
        default_vector=[0.0, 1.0],
    )
    reranker = KeywordPromotingReranker()
    observer = FakeTraceObserver(
        TracingPolicy(capture_question=True, capture_answer=True)
    )

    with build_retrieval_runtime(
        embedder,
        settings=settings,
        reranker=reranker,
    ) as restarted_runtime:
        graph = build_graph(
            AcceptanceLLM(),
            restarted_runtime.retriever,
            observer=observer,
        )
        result = graph.invoke(
            {"question": "文档中 thread_id 如何隔离 checkpoint 状态？"}
        )

        assert restarted_runtime.bm25_index.is_built is True
        assert len(restarted_runtime.bm25_index) == 3
        assert result["retrieval_diagnostics"].mode == "hybrid"
        assert result["retrieval_diagnostics"].dense_count == 3
        assert result["retrieval_diagnostics"].bm25_count >= 1
        assert reranker.calls
        assert result["retrieved_documents"][0].chunk_id == "thread-id"
        assert result["retrieved_documents"][0].rerank_score == 0.99
        assert result["context_chunk_ids"][0] == "thread-id"
        assert result["context_sources"][0].chunk_id == "thread-id"
        assert result["context_sources"][0].citation_id == "S1"
        assert "[S1] langgraph_acceptance.md" in result["context"]
        assert result["answer"].endswith("[S1]。")
        assert [
            record.name for record in observer.records_for(result["trace_id"])
        ] == [
            "chat_request",
            "router",
            "query_rewrite",
            "dense_retrieval",
            "bm25_retrieval",
            "rrf_fusion",
            "rerank",
            "context_build",
            "final_answer",
        ]
        assert result["trace_id"] in observer.finished_trace_ids
