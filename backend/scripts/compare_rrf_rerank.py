"""Run the engineered Day5 RRF-versus-rerank acceptance sample."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.rag.retrieval import (  # noqa: E402
    RerankScore,
    RerankerAdapter,
    reciprocal_rank_fusion,
)
from src.rag.schemas import SearchHit  # noqa: E402


DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "day5_rerank_cases.json"
)


class FixtureScoringClient:
    """Return fixture scores through the production RerankerAdapter contract."""

    def __init__(self, scores_by_text: dict[str, float]) -> None:
        self.scores_by_text = scores_by_text

    def score(self, query: str, documents: list[str]) -> list[RerankScore]:
        """Map every candidate document to one deterministic fixture score."""
        return [
            RerankScore(index=index, score=self.scores_by_text[document])
            for index, document in enumerate(documents)
        ]


def run_cases(fixture_path: Path = DEFAULT_FIXTURE) -> list[dict[str, Any]]:
    """Return per-case RRF and rerank positions using production algorithms."""
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    results: list[dict[str, Any]] = []
    for case in payload["cases"]:
        texts: dict[str, str] = case["texts"]
        dense = [_hit(chunk_id, texts[chunk_id], dense=1.0) for chunk_id in case["dense_order"]]
        bm25 = [_hit(chunk_id, texts[chunk_id], bm25=1.0) for chunk_id in case["bm25_order"]]
        fused = reciprocal_rank_fusion(dense, bm25, k=60, top_n=5)
        scores = {
            texts[chunk_id]: float(score)
            for chunk_id, score in case["scores"].items()
        }
        reranked = RerankerAdapter(
            FixtureScoringClient(scores),
            top_k=5,
        ).rerank(case["query"], fused)
        relevant = case["relevant_chunk_id"]
        rrf_rank = _rank(fused, relevant)
        rerank_rank = _rank(reranked, relevant)
        results.append(
            {
                "id": case["id"],
                "query": case["query"],
                "relevant_chunk_id": relevant,
                "rrf_rank": rrf_rank,
                "rerank_rank": rerank_rank,
                "delta": rrf_rank - rerank_rank,
                "rrf_order": [hit.chunk_id for hit in fused],
                "rerank_order": [hit.chunk_id for hit in reranked],
            }
        )
    return results


def summarize(results: list[dict[str, Any]]) -> dict[str, float | int]:
    """Aggregate descriptive metrics for this small engineered sample only."""
    total = len(results)
    return {
        "cases": total,
        "improved_cases": sum(item["delta"] > 0 for item in results),
        "unchanged_cases": sum(item["delta"] == 0 for item in results),
        "rrf_mrr_at_5": sum(1 / item["rrf_rank"] for item in results) / total,
        "rerank_mrr_at_5": sum(1 / item["rerank_rank"] for item in results) / total,
        "rrf_hit_at_1": sum(item["rrf_rank"] == 1 for item in results),
        "rerank_hit_at_1": sum(item["rerank_rank"] == 1 for item in results),
    }


def _hit(
    chunk_id: str,
    text: str,
    *,
    dense: float | None = None,
    bm25: float | None = None,
) -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        text=text,
        metadata={"source": "day5_acceptance.md"},
        dense_score=dense,
        bm25_score=bm25,
    )


def _rank(hits: list[SearchHit], chunk_id: str) -> int:
    return next(index for index, hit in enumerate(hits, start=1) if hit.chunk_id == chunk_id)


def main() -> None:
    """Print a reproducible table and descriptive sample metrics."""
    results = run_cases()
    print("case\trrf_rank\trerank_rank\tdelta")
    for item in results:
        print(
            f"{item['id']}\t{item['rrf_rank']}\t"
            f"{item['rerank_rank']}\t{item['delta']}"
        )
    print(json.dumps(summarize(results), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
