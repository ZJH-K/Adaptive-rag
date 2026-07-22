"""Unit tests for deterministic reciprocal-rank fusion."""

from __future__ import annotations

import pytest

from src.rag.retrieval import (
    RRFFusionConfigurationError,
    RRFFusionConflictError,
    RRFFusionDuplicateError,
    reciprocal_rank_fusion,
)
from src.rag.schemas import SearchHit


def _hit(
    chunk_id: str,
    *,
    dense_score: float | None = None,
    bm25_score: float | None = None,
    text: str | None = None,
    source: str | None = None,
) -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        text=text or f"Text for {chunk_id}",
        metadata={
            "source": source or f"{chunk_id}.md",
            "source_type": "markdown",
            "section": "RRF",
            "content_hash": f"hash-{chunk_id}",
        },
        dense_score=dense_score,
        bm25_score=bm25_score,
    )


def test_formula_and_intersection_order_match_specification() -> None:
    dense = [
        _hit("A", dense_score=0.9),
        _hit("B", dense_score=0.8),
        _hit("C", dense_score=0.7),
    ]
    bm25 = [
        _hit("B", bm25_score=12.0),
        _hit("D", bm25_score=8.0),
        _hit("A", bm25_score=5.0),
    ]

    fused = reciprocal_rank_fusion(dense, bm25)
    by_id = {hit.chunk_id: hit for hit in fused}

    assert [hit.chunk_id for hit in fused] == ["B", "A", "D", "C"]
    assert by_id["A"].fused_score == pytest.approx(
        1 / (60 + 1) + 1 / (60 + 3)
    )
    assert by_id["B"].fused_score == pytest.approx(
        1 / (60 + 2) + 1 / (60 + 1)
    )
    assert by_id["C"].fused_score == pytest.approx(1 / (60 + 3))
    assert by_id["D"].fused_score == pytest.approx(1 / (60 + 2))


def test_intersection_preserves_both_raw_scores_without_rerank_score() -> None:
    fused = reciprocal_rank_fusion(
        [_hit("shared", dense_score=0.91)],
        [_hit("shared", bm25_score=-0.25)],
    )

    assert len(fused) == 1
    assert fused[0].dense_score == 0.91
    assert fused[0].bm25_score == -0.25
    assert fused[0].fused_score == pytest.approx(2 / 61)
    assert fused[0].rerank_score is None


def test_disjoint_rankings_keep_every_chunk_and_source_score() -> None:
    fused = reciprocal_rank_fusion(
        [_hit("dense", dense_score=0.7)],
        [_hit("bm25", bm25_score=3.5)],
    )

    assert [hit.chunk_id for hit in fused] == ["bm25", "dense"]
    assert fused[0].dense_score is None
    assert fused[0].bm25_score == 3.5
    assert fused[1].dense_score == 0.7
    assert fused[1].bm25_score is None


def test_dense_only_ranking_is_returned_in_dense_order() -> None:
    dense = [_hit("a", dense_score=0.9), _hit("b", dense_score=0.8)]

    fused = reciprocal_rank_fusion(dense, [])

    assert [hit.chunk_id for hit in fused] == ["a", "b"]
    assert [hit.fused_score for hit in fused] == pytest.approx([1 / 61, 1 / 62])


def test_bm25_only_ranking_is_returned_in_bm25_order() -> None:
    bm25 = [_hit("a", bm25_score=4.0), _hit("b", bm25_score=2.0)]

    fused = reciprocal_rank_fusion([], bm25)

    assert [hit.chunk_id for hit in fused] == ["a", "b"]
    assert [hit.fused_score for hit in fused] == pytest.approx([1 / 61, 1 / 62])


def test_two_empty_rankings_return_empty() -> None:
    assert reciprocal_rank_fusion([], []) == []


def test_ties_use_best_rank_then_chunk_id() -> None:
    dense = [_hit("a"), _hit("b")]
    bm25 = [_hit("c"), _hit("d")]

    fused = reciprocal_rank_fusion(dense, bm25)

    assert [hit.chunk_id for hit in fused] == ["a", "c", "b", "d"]


def test_top_n_truncates_after_fusion() -> None:
    fused = reciprocal_rank_fusion(
        [_hit("a"), _hit("b"), _hit("c")],
        [_hit("b"), _hit("d"), _hit("a")],
        top_n=2,
    )

    assert [hit.chunk_id for hit in fused] == ["b", "a"]


def test_custom_k_changes_formula_without_using_raw_scores() -> None:
    high_raw_score = _hit("a", dense_score=1000.0)
    low_raw_score = _hit("b", dense_score=-1000.0)

    fused = reciprocal_rank_fusion(
        [high_raw_score, low_raw_score], [], k=10
    )

    assert fused[0].fused_score == pytest.approx(1 / 11)
    assert fused[1].fused_score == pytest.approx(1 / 12)


def test_inputs_and_nested_metadata_are_not_mutated() -> None:
    dense_hit = _hit("shared", dense_score=0.9)
    dense_hit.metadata["heading_path"] = ["Guide", "Fusion"]
    bm25_hit = _hit("shared", bm25_score=4.0)
    bm25_hit.metadata["heading_path"] = ["Guide", "Fusion"]
    dense = [dense_hit]
    bm25 = [bm25_hit]
    before_dense = dense_hit.model_dump()
    before_bm25 = bm25_hit.model_dump()

    fused = reciprocal_rank_fusion(dense, bm25)
    fused[0].metadata["heading_path"].append("Changed")

    assert dense_hit.model_dump() == before_dense
    assert bm25_hit.model_dump() == before_bm25
    assert dense == [dense_hit]
    assert bm25 == [bm25_hit]


@pytest.mark.parametrize(
    ("dense", "bm25", "message"),
    [
        (
            [_hit("same", text="dense text")],
            [_hit("same", text="BM25 text")],
            "text",
        ),
        (
            [_hit("same", source="dense.md")],
            [_hit("same", source="bm25.md")],
            "metadata",
        ),
    ],
)
def test_conflicting_shared_chunks_are_rejected(
    dense: list[SearchHit],
    bm25: list[SearchHit],
    message: str,
) -> None:
    with pytest.raises(RRFFusionConflictError, match=message):
        reciprocal_rank_fusion(dense, bm25)


@pytest.mark.parametrize("source", ["dense", "bm25"])
def test_duplicate_chunk_within_one_ranking_is_rejected(source: str) -> None:
    duplicated = [_hit("same"), _hit("same")]
    dense = duplicated if source == "dense" else []
    bm25 = duplicated if source == "bm25" else []

    with pytest.raises(RRFFusionDuplicateError, match="Duplicate chunk_id"):
        reciprocal_rank_fusion(dense, bm25)


@pytest.mark.parametrize("k", [0, -1, 1.5, True])
def test_invalid_k_is_rejected(k: int) -> None:
    with pytest.raises(RRFFusionConfigurationError, match="k"):
        reciprocal_rank_fusion([], [], k=k)  # type: ignore[arg-type]


@pytest.mark.parametrize("top_n", [0, -1, 1.5, True])
def test_invalid_top_n_is_rejected(top_n: int) -> None:
    with pytest.raises(RRFFusionConfigurationError, match="top_n"):
        reciprocal_rank_fusion([], [], top_n=top_n)  # type: ignore[arg-type]
