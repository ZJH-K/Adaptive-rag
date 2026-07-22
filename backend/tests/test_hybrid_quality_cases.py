"""Acceptance tests for the checked-in Day 4 quality comparison fixture."""

from scripts.compare_dense_hybrid import run_experiment


def test_quality_fixture_contains_required_query_variety() -> None:
    result = run_experiment()
    queries = [case["query"] for case in result["cases"]]

    assert result["case_count"] >= 5
    assert any("similarity_search" in query for query in queries)
    assert any("thread_id" in query for query in queries)
    assert any("BAAI/bge-reranker-v2-m3" in query for query in queries)
    assert any("RRF" in query for query in queries)
    assert any("持久化图状态" in query for query in queries)


def test_hybrid_improves_at_least_three_concrete_cases() -> None:
    result = run_experiment()
    improved = [case for case in result["cases"] if case["improved"]]

    assert result["improved_case_count"] >= 3
    assert {case["id"] for case in improved}.issuperset(
        {"thread-id", "similarity-search", "reranker-model"}
    )
    ranks = {
        case["id"]: (case["dense_first_rank"], case["hybrid_first_rank"])
        for case in improved
    }
    assert ranks["thread-id"] == (5, 1)
    assert ranks["similarity-search"] == (5, 1)
    assert ranks["reranker-model"] == (5, 3)


def test_hybrid_hit_at_k_is_better_than_dense_on_fixture() -> None:
    result = run_experiment()

    assert result["hybrid_hit_at_k"] > result["dense_hit_at_k"]
    assert result["hybrid_hit_at_k"] == result["case_count"]


def test_semantic_control_case_does_not_claim_false_improvement() -> None:
    result = run_experiment()
    control = next(
        case for case in result["cases"] if case["id"] == "semantic-checkpoint"
    )

    assert control["dense_first_rank"] == 1
    assert control["hybrid_first_rank"] == 1
    assert control["rank_gain"] == 0
    assert control["improved"] is False


def test_experiment_is_deterministic() -> None:
    assert run_experiment() == run_experiment()
