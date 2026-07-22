"""Deterministic reciprocal-rank fusion for unified retrieval hits."""

from __future__ import annotations

from collections.abc import Sequence

from src.rag.schemas import SearchHit


class RRFFusionConfigurationError(ValueError):
    """Raised when RRF parameters are invalid."""


class RRFFusionConflictError(ValueError):
    """Raised when one chunk ID maps to incompatible retrieval content."""


class RRFFusionDuplicateError(ValueError):
    """Raised when one input ranking repeats a chunk ID."""


def reciprocal_rank_fusion(
    dense_hits: Sequence[SearchHit],
    bm25_hits: Sequence[SearchHit],
    *,
    k: int = 60,
    top_n: int | None = None,
) -> list[SearchHit]:
    """Fuse rankings using sum(1 / (k + rank)), with rank starting at one."""
    _validate_parameters(k, top_n)
    _ensure_unique_ranking(dense_hits, "dense")
    _ensure_unique_ranking(bm25_hits, "BM25")

    hits_by_id: dict[str, SearchHit] = {}
    fused_scores: dict[str, float] = {}
    best_ranks: dict[str, int] = {}

    for source, hits in (("dense", dense_hits), ("bm25", bm25_hits)):
        for rank, hit in enumerate(hits, start=1):
            existing = hits_by_id.get(hit.chunk_id)
            if existing is None:
                merged = hit.model_copy(deep=True)
            else:
                _ensure_compatible(existing, hit)
                updates: dict[str, float | None] = {}
                if source == "dense":
                    updates["dense_score"] = hit.dense_score
                else:
                    updates["bm25_score"] = hit.bm25_score
                merged = existing.model_copy(update=updates, deep=True)
            hits_by_id[hit.chunk_id] = merged
            fused_scores[hit.chunk_id] = fused_scores.get(
                hit.chunk_id, 0.0
            ) + 1.0 / (k + rank)
            best_ranks[hit.chunk_id] = min(
                rank, best_ranks.get(hit.chunk_id, rank)
            )

    ordered_ids = sorted(
        hits_by_id,
        key=lambda chunk_id: (
            -fused_scores[chunk_id],
            best_ranks[chunk_id],
            chunk_id,
        ),
    )
    if top_n is not None:
        ordered_ids = ordered_ids[:top_n]

    return [
        hits_by_id[chunk_id].model_copy(
            update={
                "fused_score": fused_scores[chunk_id],
                "rerank_score": None,
            },
            deep=True,
        )
        for chunk_id in ordered_ids
    ]


def _validate_parameters(k: int, top_n: int | None) -> None:
    """Reject parameters that make ranking ambiguous or invalid."""
    if not isinstance(k, int) or isinstance(k, bool) or k <= 0:
        raise RRFFusionConfigurationError("RRF k must be a positive integer")
    if top_n is not None and (
        not isinstance(top_n, int) or isinstance(top_n, bool) or top_n <= 0
    ):
        raise RRFFusionConfigurationError(
            "RRF top_n must be a positive integer or None"
        )


def _ensure_unique_ranking(
    hits: Sequence[SearchHit],
    source: str,
) -> None:
    """Ensure each retriever contributes at most one rank per chunk."""
    seen: set[str] = set()
    for hit in hits:
        if hit.chunk_id in seen:
            raise RRFFusionDuplicateError(
                f"Duplicate chunk_id in {source} ranking: {hit.chunk_id}"
            )
        seen.add(hit.chunk_id)


def _ensure_compatible(left: SearchHit, right: SearchHit) -> None:
    """Require shared chunk IDs to identify identical text and metadata."""
    if left.text != right.text:
        raise RRFFusionConflictError(
            f"Conflicting text for chunk_id: {left.chunk_id}"
        )
    if left.metadata != right.metadata:
        raise RRFFusionConflictError(
            f"Conflicting metadata for chunk_id: {left.chunk_id}"
        )
