"""Deterministic checks for the Day5 engineered rerank sample."""

from scripts.compare_rrf_rerank import run_cases, summarize


def test_engineered_sample_is_reproducible_and_improves_top_five_ranks() -> None:
    results = run_cases()
    summary = summarize(results)

    assert len(results) == 6
    assert summary["improved_cases"] == 5
    assert summary["unchanged_cases"] == 1
    assert summary["rrf_hit_at_1"] == 1
    assert summary["rerank_hit_at_1"] == 6
    assert summary["rerank_mrr_at_5"] > summary["rrf_mrr_at_5"]
    assert all(item["rerank_rank"] <= item["rrf_rank"] for item in results)
