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
    RerankerConfigurationError,
    RerankerError,
    RerankerInputError,
    RerankerRequestError,
    RerankerResponseError,
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
        self.limits: list[int | None] = []

    def retrieve(
        self,
        query: str,
        *,
        top_n: int | None = None,
    ) -> list[SearchHit]:
        """Record a query before returning or raising."""
        self.queries.append(query)
        self.limits.append(top_n)
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


class RecordingReranker:
    """Rerank by configured chunk scores and record candidate order."""

    def __init__(
        self,
        scores: dict[str, float] | None = None,
        *,
        error: RerankerError | None = None,
    ) -> None:
        self.scores = scores or {}
        self.error = error
        self.calls: list[tuple[str, list[str]]] = []

    def rerank(self, query: str, hits: list[SearchHit]) -> list[SearchHit]:
        """Record candidates, raise, or return independently scored copies."""
        self.calls.append((query, [hit.chunk_id for hit in hits]))
        if self.error is not None:
            raise self.error
        scored = [
            hit.model_copy(
                update={"rerank_score": self.scores[hit.chunk_id]},
                deep=True,
            )
            for hit in hits
        ]
        return sorted(
            scored,
            key=lambda hit: -float(hit.rerank_score),
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
    return Settings(_env_file=None, reranker_enabled=False)


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
    result = pipeline.retrieve_with_diagnostics("  rewritten query  ")
    hits = result.hits

    assert hits == dense.hits
    assert dense.queries == ["rewritten query"]
    assert bm25.queries == []
    assert hits[0].dense_score == 0.9
    assert hits[0].fused_score is None
    assert result.diagnostics.mode == "dense"


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

    result = pipeline.retrieve_with_diagnostics("query")
    hits = result.hits

    assert [hit.chunk_id for hit in hits] == ["keyword"]
    assert result.diagnostics.degraded_sources == ("dense",)
    assert result.diagnostics.dense_count == 0
    assert result.diagnostics.bm25_count == 1


def test_known_bm25_failure_degrades_to_dense_and_is_observable() -> None:
    dense = FakeRetriever([_hit("semantic", dense_score=0.8)])
    bm25 = FakeRetriever(error=EmbeddingRequestError("synthetic known error"))
    pipeline = HybridRetrievalPipeline(dense, bm25, settings=_settings())

    result = pipeline.retrieve_with_diagnostics("query")
    hits = result.hits

    assert [hit.chunk_id for hit in hits] == ["semantic"]
    assert result.diagnostics.degraded_sources == ("bm25",)


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

    result = pipeline.retrieve_with_diagnostics("query")
    assert result.hits == []
    assert result.diagnostics.dense_count == 0
    assert result.diagnostics.bm25_count == 0


def test_candidate_limits_and_rrf_parameters_are_forwarded() -> None:
    dense = FakeRetriever([_hit(f"d{i}") for i in range(4)])
    bm25 = FakeRetriever([_hit(f"b{i}") for i in range(4)])
    fusion = RecordingFusion()
    pipeline = HybridRetrievalPipeline(
        dense,
        bm25,
        settings=_settings(),
        dense_top_n=4,
        bm25_top_n=4,
        retrieve_top_n=4,
        rrf_k=42,
        fusion=fusion,
    )

    hits = pipeline.retrieve("query")

    assert fusion.calls == [
        {
            "dense_ids": ["d0", "d1", "d2", "d3"],
            "bm25_ids": ["b0", "b1", "b2", "b3"],
            "k": 42,
            "top_n": 4,
        }
    ]
    assert dense.limits == [4]
    assert bm25.limits == [4]
    assert len(hits) == 4


def test_interleaved_request_diagnostics_remain_bound_to_each_result() -> None:
    dense = FakeRetriever([_hit("dense", dense_score=0.8)])
    bm25 = FakeRetriever([_hit("keyword", bm25_score=2.0)])
    pipeline = HybridRetrievalPipeline(dense, bm25, settings=_settings())

    first = pipeline.retrieve_with_diagnostics("first")
    dense.hits = []
    bm25.hits = []
    second = pipeline.retrieve_with_diagnostics("second")

    assert first.diagnostics.dense_count == 1
    assert first.diagnostics.bm25_count == 1
    assert second.diagnostics.dense_count == 0
    assert second.diagnostics.bm25_count == 0
    assert not hasattr(pipeline, "last_diagnostics")


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
        ({"retrieve_top_n": 1.5}, "retrieve_top_n"),
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


def test_hybrid_reranks_fused_candidates_before_final_top_k() -> None:
    dense = FakeRetriever(
        [_hit("a", dense_score=0.9), _hit("b", dense_score=0.8)]
    )
    bm25 = FakeRetriever(
        [_hit("b", bm25_score=4.0), _hit("c", bm25_score=3.0)]
    )
    reranker = RecordingReranker({"a": 0.7, "b": 0.2, "c": 0.95})
    pipeline = HybridRetrievalPipeline(
        dense,
        bm25,
        reranker=reranker,
        settings=_settings(),
        reranker_enabled=True,
        dense_top_n=3,
        bm25_top_n=3,
        retrieve_top_n=3,
        rerank_top_k=2,
    )

    result = pipeline.retrieve_with_diagnostics("query")

    assert reranker.calls == [("query", ["b", "a", "c"])]
    assert [hit.chunk_id for hit in result.hits] == ["c", "a"]
    assert [hit.rerank_score for hit in result.hits] == [0.95, 0.7]
    assert result.diagnostics.fused_count == 3
    assert result.diagnostics.rerank_input_count == 3
    assert result.diagnostics.rerank_output_count == 2
    assert result.diagnostics.reranker_degraded is False


def test_dense_only_candidates_can_be_reranked() -> None:
    dense = FakeRetriever(
        [_hit("first", dense_score=0.9), _hit("second", dense_score=0.8)]
    )
    reranker = RecordingReranker({"first": 0.1, "second": 0.9})
    pipeline = HybridRetrievalPipeline(
        dense,
        reranker=reranker,
        settings=_settings(),
        hybrid_enabled=False,
        reranker_enabled=True,
        dense_top_n=2,
        retrieve_top_n=2,
        rerank_top_k=2,
    )

    result = pipeline.retrieve_with_diagnostics("query")

    assert [hit.chunk_id for hit in result.hits] == ["second", "first"]
    assert result.diagnostics.mode == "dense"
    assert result.diagnostics.fused_count == 0
    assert result.diagnostics.rerank_input_count == 2


def test_disabled_reranker_preserves_candidate_order_and_applies_top_k() -> None:
    dense = FakeRetriever([_hit(f"d{i}", dense_score=1 - i / 10) for i in range(4)])
    reranker = RecordingReranker(error=AssertionError("must not run"))  # type: ignore[arg-type]
    pipeline = HybridRetrievalPipeline(
        dense,
        reranker=reranker,
        settings=_settings(),
        hybrid_enabled=False,
        reranker_enabled=False,
        dense_top_n=4,
        retrieve_top_n=4,
        rerank_top_k=2,
    )

    result = pipeline.retrieve_with_diagnostics("query")

    assert [hit.chunk_id for hit in result.hits] == ["d0", "d1"]
    assert reranker.calls == []
    assert result.diagnostics.rerank_input_count == 0
    assert result.diagnostics.rerank_output_count == 0


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (RerankerRequestError("timeout secret"), "reranker_request_failed"),
        (RerankerResponseError("bad response secret"), "reranker_response_invalid"),
        (
            RerankerConfigurationError("bad key secret"),
            "reranker_configuration_invalid",
        ),
        (RerankerInputError("bad input secret"), "reranker_input_invalid"),
    ],
)
def test_reranker_failures_fall_back_without_fabricating_scores(
    error: RerankerError,
    reason: str,
) -> None:
    dense = FakeRetriever(
        [_hit("a", dense_score=0.9), _hit("b", dense_score=0.8)]
    )
    reranker = RecordingReranker(error=error)
    pipeline = HybridRetrievalPipeline(
        dense,
        reranker=reranker,
        settings=_settings(),
        hybrid_enabled=False,
        reranker_enabled=True,
        dense_top_n=2,
        retrieve_top_n=2,
        rerank_top_k=2,
    )

    result = pipeline.retrieve_with_diagnostics("query")

    assert [hit.chunk_id for hit in result.hits] == ["a", "b"]
    assert all(hit.rerank_score is None for hit in result.hits)
    assert result.diagnostics.reranker_degraded is True
    assert result.diagnostics.degraded_reason == reason
    assert "secret" not in result.diagnostics.degraded_reason
    assert result.diagnostics.rerank_input_count == 2
    assert result.diagnostics.rerank_output_count == 0


def test_one_empty_retrieval_path_still_reranks_candidates() -> None:
    reranker = RecordingReranker({"keyword": 0.8})
    pipeline = HybridRetrievalPipeline(
        FakeRetriever([]),
        FakeRetriever([_hit("keyword", bm25_score=2.0)]),
        reranker=reranker,
        settings=_settings(),
        reranker_enabled=True,
    )

    result = pipeline.retrieve_with_diagnostics("query")

    assert [hit.chunk_id for hit in result.hits] == ["keyword"]
    assert reranker.calls == [("query", ["keyword"])]


def test_no_candidates_skip_enabled_reranker() -> None:
    reranker = RecordingReranker(error=AssertionError("must not run"))  # type: ignore[arg-type]
    pipeline = HybridRetrievalPipeline(
        FakeRetriever([]),
        FakeRetriever([]),
        reranker=reranker,
        settings=_settings(),
        reranker_enabled=True,
    )

    result = pipeline.retrieve_with_diagnostics("query")

    assert result.hits == []
    assert reranker.calls == []
    assert result.diagnostics.rerank_input_count == 0


def test_retrieve_and_rerank_limits_have_distinct_real_semantics() -> None:
    dense = FakeRetriever([_hit(f"d{i}", dense_score=1 - i / 10) for i in range(5)])
    bm25 = FakeRetriever([_hit(f"b{i}", bm25_score=5 - i) for i in range(5)])
    reranker = RecordingReranker(
        {
            **{f"d{i}": float(i) for i in range(5)},
            **{f"b{i}": float(i + 10) for i in range(5)},
        }
    )
    pipeline = HybridRetrievalPipeline(
        dense,
        bm25,
        reranker=reranker,
        settings=_settings(),
        reranker_enabled=True,
        dense_top_n=5,
        bm25_top_n=5,
        retrieve_top_n=4,
        rerank_top_k=2,
    )

    result = pipeline.retrieve_with_diagnostics("query")

    assert dense.limits == [5]
    assert bm25.limits == [5]
    assert len(reranker.calls[0][1]) == 4
    assert len(result.hits) == 2
    assert result.diagnostics.rerank_input_count == 4
    assert result.diagnostics.rerank_output_count == 2


def test_successful_rerank_preserves_scores_metadata_and_reports_timings() -> None:
    dense_hit = _hit("shared", dense_score=0.91)
    dense_hit.metadata["nested"] = {"value": 1}
    bm25_hit = _hit("shared", bm25_score=5.2)
    bm25_hit.metadata["nested"] = {"value": 1}
    reranker = RecordingReranker({"shared": 0.88})
    pipeline = HybridRetrievalPipeline(
        FakeRetriever([dense_hit]),
        FakeRetriever([bm25_hit]),
        reranker=reranker,
        settings=_settings(),
        reranker_enabled=True,
    )

    result = pipeline.retrieve_with_diagnostics("query")
    hit = result.hits[0]

    assert hit.dense_score == 0.91
    assert hit.bm25_score == 5.2
    assert hit.fused_score is not None
    assert hit.rerank_score == 0.88
    assert hit.metadata == dense_hit.metadata
    assert hit.metadata is not dense_hit.metadata
    diagnostics = result.diagnostics
    assert diagnostics.reranker_enabled is True
    assert diagnostics.degraded_reason is None
    assert diagnostics.dense_latency_ms >= 0
    assert diagnostics.bm25_latency_ms >= 0
    assert diagnostics.fusion_latency_ms >= 0
    assert diagnostics.rerank_latency_ms >= 0
    assert diagnostics.total_latency_ms >= 0


def test_candidate_recall_must_be_large_enough_for_rerank_pool() -> None:
    with pytest.raises(RetrievalPipelineConfigurationError, match="dense_top_n"):
        HybridRetrievalPipeline(
            FakeRetriever([]),
            settings=_settings(),
            hybrid_enabled=False,
            reranker_enabled=False,
            dense_top_n=2,
            retrieve_top_n=3,
        )


def test_unknown_reranker_programming_errors_are_not_swallowed() -> None:
    class BuggyReranker:
        def rerank(
            self,
            query: str,
            hits: list[SearchHit],
        ) -> list[SearchHit]:
            raise RuntimeError("reranker implementation bug")

    pipeline = HybridRetrievalPipeline(
        FakeRetriever([_hit("a", dense_score=0.9)]),
        reranker=BuggyReranker(),
        settings=_settings(),
        hybrid_enabled=False,
        reranker_enabled=True,
    )

    with pytest.raises(RuntimeError, match="implementation bug"):
        pipeline.retrieve("query")
