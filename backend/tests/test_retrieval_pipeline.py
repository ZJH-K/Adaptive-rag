"""Unit tests for dense-only and hybrid retrieval orchestration."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from src.config import Settings
from src.rag.embeddings.exceptions import EmbeddingRequestError
from src.rag.retrieval import (
    BM25Index,
    BM25Retriever,
    DenseRetriever,
    HybridRetrievalPipeline,
    RetrievalPipelineConfigurationError,
    RetrievalPipelineInputError,
    reciprocal_rank_fusion,
)
from src.rag.schemas import Chunk, SearchHit
from src.rag.vectorstore import ChromaVectorStore
from src.rag.vectorstore import VectorStoreResponseError
from tests.fakes import FakeEmbeddingClient


class FakeRetriever:
    """Return configured hits or raise one configured exception."""

    def __init__(
        self,
        hits: list[SearchHit] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.hits = hits or []
        self.error = error
        self.queries: list[str] = []

    def retrieve(self, query: str) -> list[SearchHit]:
        """Record a query before returning or raising."""
        self.queries.append(query)
        if self.error is not None:
            raise self.error
        return list(self.hits)


class RecordingFusion:
    """Record RRF arguments before using the production implementation."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        dense_hits: Sequence[SearchHit],
        bm25_hits: Sequence[SearchHit],
        *,
        k: int,
        top_n: int | None,
    ) -> list[SearchHit]:
        """Record bounded candidates and delegate to RRF."""
        self.calls.append(
            {
                "dense_ids": [hit.chunk_id for hit in dense_hits],
                "bm25_ids": [hit.chunk_id for hit in bm25_hits],
                "k": k,
                "top_n": top_n,
            }
        )
        return reciprocal_rank_fusion(
            dense_hits, bm25_hits, k=k, top_n=top_n
        )


def _hit(
    chunk_id: str,
    *,
    dense_score: float | None = None,
    bm25_score: float | None = None,
) -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        text=f"Text for {chunk_id}",
        metadata={
            "source": f"{chunk_id}.md",
            "source_type": "markdown",
            "section": "Retrieval",
            "content_hash": f"hash-{chunk_id}",
        },
        dense_score=dense_score,
        bm25_score=bm25_score,
    )


def _settings() -> Settings:
    return Settings(_env_file=None)


def _chunk(chunk_id: str, text: str, index: int) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id="doc-actual",
        text=text,
        chunk_index=index,
        source="actual.md",
        source_type="markdown",
        section="Retrieval",
        heading_path=["Guide", "Retrieval"],
        chunk_strategy="recursive",
        content_hash=f"hash-{chunk_id}",
    )


def test_dense_only_skips_bm25_and_fusion() -> None:
    dense = FakeRetriever([_hit("a", dense_score=0.9)])
    bm25 = FakeRetriever(error=AssertionError("BM25 must not run"))

    pipeline = HybridRetrievalPipeline(
        dense,
        bm25,
        settings=_settings(),
        hybrid_enabled=False,
        fusion=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("fusion must not run")
        ),
    )
    hits = pipeline.retrieve("  rewritten query  ")

    assert hits == dense.hits
    assert dense.queries == ["rewritten query"]
    assert bm25.queries == []
    assert hits[0].dense_score == 0.9
    assert hits[0].fused_score is None
    assert pipeline.last_diagnostics is not None
    assert pipeline.last_diagnostics.mode == "dense"


def test_hybrid_calls_both_paths_and_preserves_all_scores() -> None:
    dense_hit = _hit("shared", dense_score=0.91)
    bm25_hit = _hit("shared", bm25_score=5.2)
    dense = FakeRetriever([dense_hit])
    bm25 = FakeRetriever([bm25_hit])

    hits = HybridRetrievalPipeline(
        dense, bm25, settings=_settings()
    ).retrieve("query")

    assert dense.queries == ["query"]
    assert bm25.queries == ["query"]
    assert len(hits) == 1
    assert hits[0].dense_score == 0.91
    assert hits[0].bm25_score == 5.2
    assert hits[0].fused_score == pytest.approx(2 / 61)
    assert hits[0].rerank_score is None


def test_actual_dense_and_bm25_outputs_fuse_without_metadata_drift(
    tmp_path: Path,
) -> None:
    chunks = [
        _chunk("thread", "thread_id checkpoint configuration", 0),
        _chunk("dense", "semantic vector retrieval", 1),
        _chunk("other", "unrelated documentation", 2),
    ]
    embedder = FakeEmbeddingClient(
        vectors_by_token={"thread_id": [1.0, 0.0]},
        default_vector=[0.0, 1.0],
    )
    with ChromaVectorStore(
        persist_dir=tmp_path / "chroma",
        collection_name="hybrid_actual",
    ) as store:
        store.upsert_chunks(
            chunks,
            [[1.0, 0.0], [0.0, 1.0], [0.2, 0.8]],
        )
        index = BM25Index.from_chunks(store.get_all_chunks())
        pipeline = HybridRetrievalPipeline(
            DenseRetriever(embedder, store),
            BM25Retriever(index),
            settings=_settings(),
        )

        hits = pipeline.retrieve("thread_id")

    shared = next(hit for hit in hits if hit.chunk_id == "thread")
    assert shared.dense_score is not None
    assert shared.bm25_score is not None
    assert shared.fused_score is not None
    assert shared.metadata["source"] == "actual.md"
    assert shared.metadata["section"] == "Retrieval"
    assert shared.metadata["heading_path"] == ["Guide", "Retrieval"]


@pytest.mark.parametrize(
    ("dense_hits", "bm25_hits", "expected_id"),
    [
        ([], [_hit("bm25", bm25_score=3.0)], "bm25"),
        ([_hit("dense", dense_score=0.8)], [], "dense"),
    ],
)
def test_one_empty_path_continues_with_the_other(
    dense_hits: list[SearchHit],
    bm25_hits: list[SearchHit],
    expected_id: str,
) -> None:
    hits = HybridRetrievalPipeline(
        FakeRetriever(dense_hits),
        FakeRetriever(bm25_hits),
        settings=_settings(),
    ).retrieve("query")

    assert [hit.chunk_id for hit in hits] == [expected_id]
    assert hits[0].fused_score == pytest.approx(1 / 61)


def test_known_dense_failure_degrades_to_bm25_and_is_observable() -> None:
    dense = FakeRetriever(error=EmbeddingRequestError("offline"))
    bm25 = FakeRetriever([_hit("keyword", bm25_score=2.0)])
    pipeline = HybridRetrievalPipeline(dense, bm25, settings=_settings())

    hits = pipeline.retrieve("query")

    assert [hit.chunk_id for hit in hits] == ["keyword"]
    assert pipeline.last_diagnostics is not None
    assert pipeline.last_diagnostics.degraded_sources == ("dense",)
    assert pipeline.last_diagnostics.dense_count == 0
    assert pipeline.last_diagnostics.bm25_count == 1


def test_known_bm25_failure_degrades_to_dense_and_is_observable() -> None:
    dense = FakeRetriever([_hit("semantic", dense_score=0.8)])
    bm25 = FakeRetriever(error=EmbeddingRequestError("synthetic known error"))
    pipeline = HybridRetrievalPipeline(dense, bm25, settings=_settings())

    hits = pipeline.retrieve("query")

    assert [hit.chunk_id for hit in hits] == ["semantic"]
    assert pipeline.last_diagnostics is not None
    assert pipeline.last_diagnostics.degraded_sources == ("bm25",)


def test_programming_errors_are_not_swallowed() -> None:
    pipeline = HybridRetrievalPipeline(
        FakeRetriever(error=RuntimeError("bug")),
        FakeRetriever([]),
        settings=_settings(),
    )

    with pytest.raises(RuntimeError, match="bug"):
        pipeline.retrieve("query")


def test_data_contract_errors_are_not_swallowed() -> None:
    pipeline = HybridRetrievalPipeline(
        FakeRetriever(error=VectorStoreResponseError("corrupt result")),
        FakeRetriever([]),
        settings=_settings(),
    )

    with pytest.raises(VectorStoreResponseError, match="corrupt"):
        pipeline.retrieve("query")


def test_two_empty_paths_return_empty() -> None:
    pipeline = HybridRetrievalPipeline(
        FakeRetriever([]), FakeRetriever([]), settings=_settings()
    )

    assert pipeline.retrieve("query") == []
    assert pipeline.last_diagnostics is not None
    assert pipeline.last_diagnostics.dense_count == 0
    assert pipeline.last_diagnostics.bm25_count == 0


def test_candidate_limits_and_rrf_parameters_are_forwarded() -> None:
    dense = FakeRetriever([_hit(f"d{i}") for i in range(4)])
    bm25 = FakeRetriever([_hit(f"b{i}") for i in range(4)])
    fusion = RecordingFusion()
    pipeline = HybridRetrievalPipeline(
        dense,
        bm25,
        settings=_settings(),
        dense_top_n=2,
        bm25_top_n=3,
        fusion_top_n=4,
        rrf_k=42,
        fusion=fusion,
    )

    hits = pipeline.retrieve("query")

    assert fusion.calls == [
        {
            "dense_ids": ["d0", "d1"],
            "bm25_ids": ["b0", "b1", "b2"],
            "k": 42,
            "top_n": 4,
        }
    ]
    assert len(hits) == 4


@pytest.mark.parametrize("query", ["", "   ", None])
def test_invalid_query_is_rejected_before_retrieval(query: str) -> None:
    dense = FakeRetriever([])
    bm25 = FakeRetriever([])
    pipeline = HybridRetrievalPipeline(dense, bm25, settings=_settings())

    with pytest.raises(RetrievalPipelineInputError, match="non-empty"):
        pipeline.retrieve(query)  # type: ignore[arg-type]

    assert dense.queries == []
    assert bm25.queries == []


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"hybrid_enabled": "yes"}, "hybrid_enabled"),
        ({"dense_top_n": 0}, "dense_top_n"),
        ({"bm25_top_n": -1}, "bm25_top_n"),
        ({"fusion_top_n": 1.5}, "fusion_top_n"),
        ({"rrf_k": True}, "rrf_k"),
    ],
)
def test_invalid_pipeline_configuration_is_rejected(
    overrides: dict[str, Any],
    message: str,
) -> None:
    with pytest.raises(RetrievalPipelineConfigurationError, match=message):
        HybridRetrievalPipeline(
            FakeRetriever([]),
            FakeRetriever([]),
            settings=_settings(),
            **overrides,
        )


def test_hybrid_requires_bm25_but_dense_only_does_not() -> None:
    with pytest.raises(RetrievalPipelineConfigurationError, match="BM25"):
        HybridRetrievalPipeline(
            FakeRetriever([]), settings=_settings(), hybrid_enabled=True
        )

    pipeline = HybridRetrievalPipeline(
        FakeRetriever([]), settings=_settings(), hybrid_enabled=False
    )
    assert pipeline.retrieve("query") == []
