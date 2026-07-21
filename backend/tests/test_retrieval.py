"""Integration tests for dense vector retrieval and SearchHit mapping."""

from pathlib import Path

import pytest

from src.rag.retrieval import (
    DenseRetrievalConfigurationError,
    DenseRetrievalInputError,
    DenseRetriever,
)
from src.rag.schemas import Chunk, SearchHit
from src.rag.vectorstore import ChromaVectorStore
from tests.fakes import FakeEmbeddingClient


def _chunk(
    index: int,
    text: str,
    *,
    page: int | None = None,
) -> Chunk:
    return Chunk(
        chunk_id=f"chunk-{index}",
        document_id="retrieval-doc",
        text=text,
        chunk_index=index,
        source="manual.pdf" if page is not None else "guide.md",
        source_type="pdf" if page is not None else "markdown",
        page=page,
        section=None,
        heading_path=[],
        chunk_strategy="recursive",
        content_hash=f"hash-{index}",
    )


def _store(path: Path) -> ChromaVectorStore:
    return ChromaVectorStore(
        persist_dir=path,
        collection_name="retrieval_tests",
    )


def _embedder() -> FakeEmbeddingClient:
    return FakeEmbeddingClient(
        vectors_by_token={
            "dense": [1.0, 0.0, 0.0],
            "pdf": [0.0, 1.0, 0.0],
        },
        default_vector=[0.0, 0.0, 1.0],
    )


def test_dense_retrieval_returns_ordered_search_hits(tmp_path: Path) -> None:
    embedder = _embedder()
    with _store(tmp_path / "chroma") as store:
        store.upsert_chunks(
            [
                _chunk(0, "Dense vector retrieval"),
                _chunk(1, "A partly related result"),
                _chunk(2, "PDF parsing"),
            ],
            [[1.0, 0.0, 0.0], [0.8, 0.2, 0.0], [0.0, 1.0, 0.0]],
        )
        hits = DenseRetriever(embedder, store, top_k=3).retrieve(
            "How does dense search work?"
        )

        assert all(isinstance(hit, SearchHit) for hit in hits)
        assert [hit.chunk_id for hit in hits] == ["chunk-0", "chunk-1", "chunk-2"]
        assert [hit.dense_score for hit in hits] == sorted(
            [hit.dense_score for hit in hits], reverse=True
        )
        assert hits[0].dense_score == pytest.approx(1.0)
        assert embedder.query_calls == ["How does dense search work?"]


def test_top_k_limits_results(tmp_path: Path) -> None:
    with _store(tmp_path / "chroma") as store:
        store.upsert_chunks(
            [_chunk(0, "Dense"), _chunk(1, "Related"), _chunk(2, "Other")],
            [[1.0, 0.0, 0.0], [0.8, 0.2, 0.0], [0.0, 0.0, 1.0]],
        )

        hits = DenseRetriever(_embedder(), store, top_k=2).retrieve("dense")

        assert len(hits) == 2


def test_search_hit_metadata_contains_source_and_pdf_page(tmp_path: Path) -> None:
    with _store(tmp_path / "chroma") as store:
        store.upsert_chunks(
            [_chunk(0, "PDF checkpoint documentation", page=4)],
            [[0.0, 1.0, 0.0]],
        )

        hit = DenseRetriever(_embedder(), store, top_k=1).retrieve("PDF")[0]

        assert hit.metadata["source"] == "manual.pdf"
        assert hit.metadata["source_type"] == "pdf"
        assert hit.metadata["page"] == 4


def test_empty_collection_returns_no_hits(tmp_path: Path) -> None:
    embedder = _embedder()
    with _store(tmp_path / "chroma") as store:
        hits = DenseRetriever(embedder, store, top_k=5).retrieve("dense")

        assert hits == []
        assert embedder.query_calls == ["dense"]


@pytest.mark.parametrize("top_k", [0, -1, 1.5, True])
def test_invalid_top_k_is_rejected(tmp_path: Path, top_k: int) -> None:
    with _store(tmp_path / "chroma") as store:
        with pytest.raises(DenseRetrievalConfigurationError, match="top_k"):
            DenseRetriever(  # type: ignore[arg-type]
                _embedder(), store, top_k=top_k
            )


@pytest.mark.parametrize("query", ["", "   ", "\n\t"])
def test_blank_query_is_rejected_without_embedding(
    tmp_path: Path,
    query: str,
) -> None:
    embedder = _embedder()
    with _store(tmp_path / "chroma") as store:
        retriever = DenseRetriever(embedder, store)

        with pytest.raises(DenseRetrievalInputError, match="non-empty"):
            retriever.retrieve(query)

        assert embedder.query_calls == []

