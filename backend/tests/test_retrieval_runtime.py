"""Integration tests for restart-safe retrieval runtime composition."""

from __future__ import annotations

from pathlib import Path

from src.config import Settings
from src.rag.runtime import build_retrieval_runtime
from src.rag.schemas import Chunk, SearchHit
from src.rag.vectorstore import ChromaVectorStore
from tests.fakes import FakeEmbeddingClient


class PassThroughReranker:
    """Offline reranker used to prove runtime composition."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def rerank(self, query: str, hits: list[SearchHit]) -> list[SearchHit]:
        """Preserve order while adding deterministic scores."""
        self.calls.append([hit.chunk_id for hit in hits])
        return [
            hit.model_copy(
                update={"rerank_score": 1.0 - index / 10},
                deep=True,
            )
            for index, hit in enumerate(hits)
        ]


def _chunk(chunk_id: str, text: str, index: int) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id="runtime-doc",
        text=text,
        chunk_index=index,
        source="runtime.md",
        source_type="markdown",
        section="Runtime",
        heading_path=["Runtime"],
        chunk_strategy="recursive",
        content_hash=f"hash-{chunk_id}",
    )


def test_persisted_chunks_restore_bm25_before_first_hybrid_query(
    tmp_path: Path,
) -> None:
    persist_dir = tmp_path / "chroma"
    collection_name = "runtime_restart"
    chunks = [
        _chunk("keyword", "thread_id checkpoint configuration", 0),
        _chunk("dense", "semantic vector search", 1),
        _chunk("other", "unrelated parser guide", 2),
    ]
    with ChromaVectorStore(
        persist_dir=persist_dir,
        collection_name=collection_name,
    ) as first_store:
        first_store.upsert_chunks(
            chunks,
            [[1.0, 0.0], [0.0, 1.0], [0.2, 0.8]],
        )

    settings = Settings(
        _env_file=None,
        chroma_persist_dir=persist_dir,
        chroma_collection=collection_name,
        dense_top_n=2,
        bm25_top_n=3,
        retrieve_top_n=2,
        reranker_enabled=True,
        rerank_top_k=2,
    )
    embedder = FakeEmbeddingClient(
        vectors_by_token={"thread_id": [1.0, 0.0]},
        default_vector=[0.0, 1.0],
    )

    reranker = PassThroughReranker()
    with build_retrieval_runtime(
        embedder,
        settings=settings,
        reranker=reranker,
    ) as runtime:
        result = runtime.retriever.retrieve_with_diagnostics("thread_id")

        assert runtime.bm25_index.is_built is True
        assert len(runtime.bm25_index) == 3
        assert result.diagnostics.mode == "hybrid"
        assert result.diagnostics.bm25_count == 1
        keyword = next(hit for hit in result.hits if hit.chunk_id == "keyword")
        assert keyword.bm25_score is not None
        assert keyword.rerank_score is not None
        assert runtime.reranker is reranker
        assert reranker.calls


def test_runtime_uses_settings_as_authoritative_candidate_limits(
    tmp_path: Path,
) -> None:
    settings = Settings(
        _env_file=None,
        dense_top_n=7,
        bm25_top_n=8,
        retrieve_top_n=4,
        reranker_enabled=False,
        chroma_persist_dir=tmp_path / "chroma",
        chroma_collection="runtime_limits",
    )

    with build_retrieval_runtime(
        FakeEmbeddingClient(),
        settings=settings,
    ) as runtime:
        assert runtime.dense_retriever.top_k == 7
        assert runtime.bm25_retriever.top_n == 8
        assert runtime.retriever.dense_top_n == 7
        assert runtime.retriever.bm25_top_n == 8
        assert runtime.retriever.retrieve_top_n == 4
