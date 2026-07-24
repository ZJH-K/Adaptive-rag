"""Unit tests for deterministic RAG evaluation metrics."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation.metrics import (
    UndefinedMetricError,
    aggregate_results,
    average_latency_ms,
    evaluate_answer,
    evaluate_retrieval,
    evaluate_sample,
    hit_rate_at_k,
    keyword_coverage,
    recall_at_k,
    reciprocal_rank,
    rerank_gain,
)


def test_hit_rate_at_k_covers_hit_and_miss() -> None:
    assert hit_rate_at_k(["a", "b", "c"], ["b"], 2) == 1.0
    assert hit_rate_at_k(["a", "b", "c"], ["c"], 2) == 0.0


@pytest.mark.parametrize("k", [0, -1, True, 1.5])
def test_k_must_be_a_positive_integer(k: object) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        hit_rate_at_k(["a"], ["a"], k)  # type: ignore[arg-type]


def test_recall_at_k_handles_partial_and_full_recall() -> None:
    retrieved = ["a", "x", "b", "c"]
    relevant = ["a", "b", "c"]

    assert recall_at_k(retrieved, relevant, 2) == pytest.approx(1 / 3)
    assert recall_at_k(retrieved, relevant, 3) == pytest.approx(2 / 3)
    assert recall_at_k(retrieved, relevant, 10) == 1.0


def test_relevant_duplicates_do_not_change_recall_denominator() -> None:
    assert recall_at_k(["a"], ["a", "a", "b"], 1) == 0.5


def test_retrieved_duplicates_use_first_seen_rank() -> None:
    retrieved = ["noise", "noise", "relevant"]

    assert reciprocal_rank(retrieved, ["relevant"]) == 0.5
    assert hit_rate_at_k(retrieved, ["relevant"], 2) == 1.0


def test_reciprocal_rank_first_third_and_missing() -> None:
    assert reciprocal_rank(["r", "a", "b"], ["r"]) == 1.0
    assert reciprocal_rank(["a", "b", "r"], ["r"]) == pytest.approx(1 / 3)
    assert reciprocal_rank(["a", "b"], ["r"]) == 0.0


def test_empty_retrieved_is_valid_zero_score() -> None:
    metrics = evaluate_retrieval([], ["relevant"], ks=(1, 3))

    assert metrics.valid is True
    assert metrics.hit_rate_at_k == {1: 0.0, 3: 0.0}
    assert metrics.recall_at_k == {1: 0.0, 3: 0.0}
    assert metrics.reciprocal_rank == 0.0
    assert metrics.first_relevant_rank is None


def test_empty_relevant_is_explicitly_undefined_or_skipped() -> None:
    with pytest.raises(UndefinedMetricError, match="at least one relevant"):
        recall_at_k(["a"], [], 1)

    metrics = evaluate_retrieval(["a"], [], ks=(1, 3))
    assert metrics.valid is False
    assert metrics.skipped_reason == "no relevant chunk IDs"
    assert metrics.hit_rate_at_k == {}


def test_multiple_k_values_are_computed_in_one_result() -> None:
    metrics = evaluate_retrieval(
        ["a", "b", "c", "d"], ["b", "d"], ks=(1, 3, 5, 10)
    )

    assert metrics.hit_rate_at_k == {1: 0.0, 3: 1.0, 5: 1.0, 10: 1.0}
    assert metrics.recall_at_k == {1: 0.0, 3: 0.5, 5: 1.0, 10: 1.0}


def test_chinese_keyword_matching_normalizes_case_whitespace_and_punctuation() -> None:
    answer = "系统会先执行查询，改写；\u3000然后进行 混合检索。"
    metrics = evaluate_answer(answer, ["查询改写", "然后进行混合检索"])

    assert metrics.keyword_coverage == 1.0
    assert metrics.all_keywords_matched is True
    assert metrics.passed is True


def test_technical_identifiers_remain_matchable() -> None:
    answer = (
        "Use THREAD_ID with similarity_search and "
        "BAAI/bge-reranker-v2-m3 in production."
    )
    keywords = ["thread_id", "similarity_search", "BAAI/bge-reranker-v2-m3"]

    assert keyword_coverage(answer, keywords) == 1.0


def test_empty_answer_and_empty_keywords_have_distinct_semantics() -> None:
    empty_answer = evaluate_answer("", ["thread_id"])
    empty_keywords = evaluate_answer("some answer", [])

    assert empty_answer.valid is True
    assert empty_answer.keyword_coverage == 0.0
    assert empty_answer.passed is False
    assert empty_keywords.valid is False
    assert empty_keywords.skipped_reason == "no expected keywords"
    with pytest.raises(UndefinedMetricError, match="requires expected keywords"):
        keyword_coverage("some answer", [])


def test_keyword_threshold_can_allow_partial_coverage() -> None:
    metrics = evaluate_answer(
        "包含 alpha 和 beta", ["alpha", "beta", "gamma"],
        require_all=False, minimum_coverage=2 / 3,
    )

    assert metrics.keyword_coverage == pytest.approx(2 / 3)
    assert metrics.all_keywords_matched is False
    assert metrics.passed is True
    assert metrics.required_coverage == pytest.approx(2 / 3)


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        (["a", "b", "r"], ["r", "a", "b"], 2.0),
        (["r", "a", "b"], ["a", "b", "r"], -2.0),
        (["a", "r", "b"], ["b", "r", "a"], 0.0),
    ],
)
def test_rerank_gain_positive_negative_and_unchanged(
    before: list[str], after: list[str], expected: float
) -> None:
    assert rerank_gain(before, after, ["r"]) == expected


def test_rerank_gain_is_undefined_without_hits_on_both_sides() -> None:
    with pytest.raises(UndefinedMetricError, match="both rankings"):
        rerank_gain(["a", "b"], ["r"], ["r"])


def test_average_latency_validates_and_averages() -> None:
    assert average_latency_ms([10, 20.0, 30]) == 20.0
    with pytest.raises(UndefinedMetricError):
        average_latency_ms([])
    with pytest.raises(ValueError, match="non-negative"):
        average_latency_ms([1.0, -1.0])


def test_aggregate_results_uses_macro_average_and_tracks_skips() -> None:
    first = evaluate_sample(
        "q001", ["r", "x"], ["r"], ks=(1, 3),
        answer="alpha beta", expected_keywords=["alpha", "beta"],
        latency_ms=10.0,
    )
    second = evaluate_sample(
        "q002", ["x", "r"], ["r", "missing"], ks=(1, 3),
        answer="alpha", expected_keywords=["alpha", "beta"],
        require_all_keywords=False, minimum_keyword_coverage=0.5,
        latency_ms=30.0,
        before_rerank_ids=["r", "x"],
    )
    skipped = evaluate_sample("q003", ["x"], [], ks=(1, 3))

    aggregate = aggregate_results([first, second, skipped], ks=(1, 3))

    assert aggregate.sample_count == 3
    assert aggregate.valid_sample_count == 2
    assert aggregate.skipped_sample_count == 1
    assert aggregate.mean_hit_rate_at_k == {1: 0.5, 3: 1.0}
    assert aggregate.mean_recall_at_k == {1: 0.5, 3: 0.75}
    assert aggregate.mrr == 0.75
    assert aggregate.mean_keyword_coverage == 0.75
    assert aggregate.keyword_pass_rate == 1.0
    assert aggregate.average_latency_ms == 20.0
    assert aggregate.mean_rerank_gain == -1.0


def test_result_json_has_stable_report_fields() -> None:
    result = evaluate_sample(
        "q-json", ["a", "r"], ["r"], ks=(1, 3),
        answer="THREAD_ID", expected_keywords=["thread_id"],
        latency_ms=12.5,
    )
    payload = json.loads(result.model_dump_json())

    assert list(payload) == [
        "sample_id", "retrieval", "answer", "latency_ms", "rerank_gain"
    ]
    assert list(payload["retrieval"]) == [
        "valid", "skipped_reason", "hit_rate_at_k", "recall_at_k",
        "reciprocal_rank", "first_relevant_rank", "retrieved_count",
        "relevant_count",
    ]
    assert payload["retrieval"]["hit_rate_at_k"] == {"1": 0.0, "3": 1.0}
    assert payload["answer"]["matched_keywords"] == ["thread_id"]
