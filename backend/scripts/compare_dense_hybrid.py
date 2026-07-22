"""Run the deterministic Day 4 Dense/BM25/Hybrid comparison fixture."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.rag.retrieval import (  # noqa: E402
    BM25Index,
    BM25Retriever,
    reciprocal_rank_fusion,
)
from src.rag.schemas import Chunk, SearchHit  # noqa: E402


DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "day4_hybrid_cases.json"
)


def run_experiment(fixture_path: Path = DEFAULT_FIXTURE) -> dict[str, Any]:
    """Return structured rankings and lightweight metrics for every case."""
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    chunks = [Chunk.model_validate(item) for item in fixture["chunks"]]
    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    if len(chunks_by_id) != len(chunks):
        raise ValueError("Experiment fixture contains duplicate chunk IDs")

    top_k = fixture["top_k"]
    bm25 = BM25Retriever(
        BM25Index.from_chunks(chunks),
        top_n=len(chunks),
    )
    cases: list[dict[str, Any]] = []
    for case in fixture["cases"]:
        dense_hits = _dense_hits(case["dense_ranking"], chunks_by_id)
        bm25_hits = bm25.retrieve(case["query"])
        hybrid_hits = reciprocal_rank_fusion(
            dense_hits,
            bm25_hits,
            top_n=len(chunks),
        )
        relevant = set(case["relevant_chunk_ids"])
        dense_rank = _first_relevant_rank(dense_hits, relevant)
        bm25_rank = _first_relevant_rank(bm25_hits, relevant)
        hybrid_rank = _first_relevant_rank(hybrid_hits, relevant)
        cases.append(
            {
                "id": case["id"],
                "query": case["query"],
                "relevant_chunk_ids": case["relevant_chunk_ids"],
                "dense_top_k": _top_ids(dense_hits, top_k),
                "bm25_top_k": _top_ids(bm25_hits, top_k),
                "hybrid_top_k": _top_ids(hybrid_hits, top_k),
                "dense_first_rank": dense_rank,
                "bm25_first_rank": bm25_rank,
                "hybrid_first_rank": hybrid_rank,
                "dense_hit_at_k": _hit_at_k(dense_rank, top_k),
                "hybrid_hit_at_k": _hit_at_k(hybrid_rank, top_k),
                "rank_gain": _rank_gain(dense_rank, hybrid_rank),
                "improved": _is_improved(dense_rank, hybrid_rank),
                "reason": case["reason"],
            }
        )

    return {
        "fixture": str(fixture_path),
        "top_k": top_k,
        "case_count": len(cases),
        "improved_case_count": sum(case["improved"] for case in cases),
        "dense_hit_at_k": sum(case["dense_hit_at_k"] for case in cases),
        "hybrid_hit_at_k": sum(case["hybrid_hit_at_k"] for case in cases),
        "cases": cases,
    }


def _dense_hits(
    ranking: list[str],
    chunks_by_id: dict[str, Chunk],
) -> list[SearchHit]:
    """Map an explicit offline Dense ranking into shared SearchHits."""
    if len(set(ranking)) != len(ranking):
        raise ValueError("Dense fixture ranking contains duplicate chunk IDs")
    try:
        ranked_chunks = [chunks_by_id[chunk_id] for chunk_id in ranking]
    except KeyError as exc:
        raise ValueError(f"Dense fixture references unknown chunk: {exc.args[0]}") from exc
    return [
        SearchHit(
            chunk_id=chunk.chunk_id,
            text=chunk.text,
            metadata=chunk.model_dump(exclude={"chunk_id", "text"}),
            dense_score=1.0 - rank * 0.05,
        )
        for rank, chunk in enumerate(ranked_chunks, start=1)
    ]


def _first_relevant_rank(
    hits: list[SearchHit],
    relevant: set[str],
) -> int | None:
    """Return the first one-based relevant rank, or None when absent."""
    return next(
        (
            rank
            for rank, hit in enumerate(hits, start=1)
            if hit.chunk_id in relevant
        ),
        None,
    )


def _top_ids(hits: list[SearchHit], top_k: int) -> list[str]:
    return [hit.chunk_id for hit in hits[:top_k]]


def _hit_at_k(rank: int | None, top_k: int) -> bool:
    return rank is not None and rank <= top_k


def _rank_gain(dense_rank: int | None, hybrid_rank: int | None) -> int | None:
    if dense_rank is None or hybrid_rank is None:
        return None
    return dense_rank - hybrid_rank


def _is_improved(dense_rank: int | None, hybrid_rank: int | None) -> bool:
    return hybrid_rank is not None and (
        dense_rank is None or hybrid_rank < dense_rank
    )


def main() -> None:
    """Print reproducible structured results for the checked-in fixture."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    args = parser.parse_args()
    print(
        json.dumps(
            run_experiment(args.fixture),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
