"""Pure, deterministic metrics for retrieval and answer evaluation."""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Iterable, Sequence
from statistics import fmean

from pydantic import BaseModel, Field


class UndefinedMetricError(ValueError):
    """Raised when a scalar metric has no mathematically valid denominator."""


class RetrievalMetrics(BaseModel):
    """Retrieval metrics for one sample across one or more cutoff values."""

    valid: bool
    skipped_reason: str | None = None
    hit_rate_at_k: dict[int, float] = Field(default_factory=dict)
    recall_at_k: dict[int, float] = Field(default_factory=dict)
    reciprocal_rank: float | None = Field(default=None, ge=0.0, le=1.0)
    first_relevant_rank: int | None = Field(default=None, ge=1)
    retrieved_count: int = Field(ge=0)
    relevant_count: int = Field(ge=0)


class AnswerMetrics(BaseModel):
    """Deterministic keyword matching results for one generated answer."""

    valid: bool
    skipped_reason: str | None = None
    keyword_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    all_keywords_matched: bool | None = None
    passed: bool | None = None
    required_coverage: float = Field(ge=0.0, le=1.0)
    matched_keywords: list[str] = Field(default_factory=list)
    missing_keywords: list[str] = Field(default_factory=list)


class SampleEvaluationResult(BaseModel):
    """Serializable metrics and optional timing data for one dataset sample."""

    sample_id: str = Field(min_length=1)
    retrieval: RetrievalMetrics
    answer: AnswerMetrics | None = None
    latency_ms: float | None = Field(default=None, ge=0.0)
    rerank_gain: float | None = None


class AggregateEvaluationResult(BaseModel):
    """Serializable macro averages across sample evaluation results."""

    sample_count: int = Field(ge=0)
    valid_sample_count: int = Field(ge=0)
    skipped_sample_count: int = Field(ge=0)
    mean_hit_rate_at_k: dict[int, float | None] = Field(default_factory=dict)
    mean_recall_at_k: dict[int, float | None] = Field(default_factory=dict)
    mrr: float | None = Field(default=None, ge=0.0, le=1.0)
    answer_sample_count: int = Field(ge=0)
    skipped_answer_sample_count: int = Field(ge=0)
    mean_keyword_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    keyword_pass_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    average_latency_ms: float | None = Field(default=None, ge=0.0)
    mean_rerank_gain: float | None = None


def _unique_ids(chunk_ids: Iterable[str], *, name: str) -> list[str]:
    """Return IDs in first-seen order after trimming and deduplication."""
    if isinstance(chunk_ids, (str, bytes)):
        raise TypeError(f"{name} must be an iterable of chunk IDs, not a string")
    unique: list[str] = []
    seen: set[str] = set()
    for chunk_id in chunk_ids:
        if not isinstance(chunk_id, str):
            raise TypeError(f"{name} must contain only strings")
        normalized = chunk_id.strip()
        if not normalized:
            raise ValueError(f"{name} must not contain blank chunk IDs")
        if normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return unique


def _positive_k(k: int) -> int:
    if not isinstance(k, int) or isinstance(k, bool) or k <= 0:
        raise ValueError("k must be a positive integer")
    return k


def _cutoffs(ks: Iterable[int]) -> tuple[int, ...]:
    if isinstance(ks, (str, bytes)):
        raise TypeError("ks must be an iterable of positive integers")
    cutoffs = tuple(dict.fromkeys(_positive_k(k) for k in ks))
    if not cutoffs:
        raise ValueError("at least one cutoff k is required")
    return cutoffs


def _prepared_rankings(
    retrieved_ids: Iterable[str], relevant_ids: Iterable[str]
) -> tuple[list[str], set[str]]:
    retrieved = _unique_ids(retrieved_ids, name="retrieved_ids")
    relevant = set(_unique_ids(relevant_ids, name="relevant_ids"))
    if not relevant:
        raise UndefinedMetricError("retrieval metrics require at least one relevant ID")
    return retrieved, relevant


def hit_rate_at_k(
    retrieved_ids: Iterable[str], relevant_ids: Iterable[str], k: int
) -> float:
    """Return 1.0 when any relevant ID occurs in the deduplicated top-k."""
    cutoff = _positive_k(k)
    retrieved, relevant = _prepared_rankings(retrieved_ids, relevant_ids)
    return float(any(chunk_id in relevant for chunk_id in retrieved[:cutoff]))


def recall_at_k(
    retrieved_ids: Iterable[str], relevant_ids: Iterable[str], k: int
) -> float:
    """Return the fraction of unique relevant IDs found in deduplicated top-k."""
    cutoff = _positive_k(k)
    retrieved, relevant = _prepared_rankings(retrieved_ids, relevant_ids)
    hits = relevant.intersection(retrieved[:cutoff])
    return len(hits) / len(relevant)


def reciprocal_rank(
    retrieved_ids: Iterable[str], relevant_ids: Iterable[str]
) -> float:
    """Return 1/rank for the first relevant ID, or 0.0 when none is retrieved."""
    retrieved, relevant = _prepared_rankings(retrieved_ids, relevant_ids)
    for rank, chunk_id in enumerate(retrieved, start=1):
        if chunk_id in relevant:
            return 1.0 / rank
    return 0.0


def _first_relevant_rank(
    retrieved_ids: Iterable[str], relevant_ids: Iterable[str]
) -> int | None:
    retrieved, relevant = _prepared_rankings(retrieved_ids, relevant_ids)
    return next(
        (rank for rank, chunk_id in enumerate(retrieved, start=1) if chunk_id in relevant),
        None,
    )


def evaluate_retrieval(
    retrieved_ids: Iterable[str],
    relevant_ids: Iterable[str],
    *,
    ks: Iterable[int] = (1, 3, 5, 10),
) -> RetrievalMetrics:
    """Compute all retrieval metrics or explicitly mark an empty-label sample skipped."""
    cutoffs = _cutoffs(ks)
    retrieved = _unique_ids(retrieved_ids, name="retrieved_ids")
    relevant = _unique_ids(relevant_ids, name="relevant_ids")
    if not relevant:
        return RetrievalMetrics(
            valid=False,
            skipped_reason="no relevant chunk IDs",
            retrieved_count=len(retrieved),
            relevant_count=0,
        )
    return RetrievalMetrics(
        valid=True,
        hit_rate_at_k={
            k: hit_rate_at_k(retrieved, relevant, k) for k in cutoffs
        },
        recall_at_k={k: recall_at_k(retrieved, relevant, k) for k in cutoffs},
        reciprocal_rank=reciprocal_rank(retrieved, relevant),
        first_relevant_rank=_first_relevant_rank(retrieved, relevant),
        retrieved_count=len(retrieved),
        relevant_count=len(relevant),
    )


def normalize_keyword_text(text: str) -> str:
    """Normalize NFKC, case, Unicode whitespace, and non-technical punctuation.

    Underscore, hyphen, and dot are retained so identifiers such as
    ``thread_id`` and ``bge-reranker-v2-m3`` remain directly matchable. Other
    Unicode punctuation is converted to a single word boundary.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    normalized = unicodedata.normalize("NFKC", text).casefold()
    characters = [
        " "
        if character.isspace()
        or (
            unicodedata.category(character).startswith("P")
            and character not in {"_", "-", "."}
        )
        else character
        for character in normalized
    ]
    return " ".join("".join(characters).split())


def _prepared_keywords(expected_keywords: Iterable[str]) -> list[tuple[str, str]]:
    if isinstance(expected_keywords, (str, bytes)):
        raise TypeError("expected_keywords must be an iterable of strings")
    prepared: list[tuple[str, str]] = []
    seen: set[str] = set()
    for keyword in expected_keywords:
        if not isinstance(keyword, str):
            raise TypeError("expected_keywords must contain only strings")
        display = keyword.strip()
        normalized = normalize_keyword_text(display)
        if not normalized:
            raise ValueError("expected_keywords must not contain blanks")
        if normalized not in seen:
            seen.add(normalized)
            prepared.append((display, normalized))
    return prepared


def _keyword_present(normalized_answer: str, normalized_keyword: str) -> bool:
    """Match canonical text, allowing Chinese separators to be insignificant."""
    if normalized_keyword in normalized_answer:
        return True
    contains_cjk = any("\u3400" <= character <= "\u9fff" for character in normalized_keyword)
    return contains_cjk and normalized_keyword.replace(" ", "") in normalized_answer.replace(
        " ", ""
    )


def keyword_coverage(answer: str, expected_keywords: Iterable[str]) -> float:
    """Return matched unique keywords divided by expected unique keywords."""
    prepared = _prepared_keywords(expected_keywords)
    if not prepared:
        raise UndefinedMetricError("keyword coverage requires expected keywords")
    normalized_answer = normalize_keyword_text(answer)
    matches = sum(
        _keyword_present(normalized_answer, keyword) for _, keyword in prepared
    )
    return matches / len(prepared)


def evaluate_answer(
    answer: str,
    expected_keywords: Iterable[str],
    *,
    require_all: bool = True,
    minimum_coverage: float = 0.5,
) -> AnswerMetrics:
    """Evaluate normalized keyword coverage using all-or-threshold pass policy."""
    if not isinstance(require_all, bool):
        raise TypeError("require_all must be a boolean")
    if (
        not isinstance(minimum_coverage, (int, float))
        or isinstance(minimum_coverage, bool)
        or not math.isfinite(float(minimum_coverage))
        or not 0.0 <= float(minimum_coverage) <= 1.0
    ):
        raise ValueError("minimum_coverage must be a finite value between 0 and 1")
    required_coverage = 1.0 if require_all else float(minimum_coverage)
    prepared = _prepared_keywords(expected_keywords)
    if not prepared:
        return AnswerMetrics(
            valid=False,
            skipped_reason="no expected keywords",
            required_coverage=required_coverage,
        )

    normalized_answer = normalize_keyword_text(answer)
    matched = [
        display
        for display, keyword in prepared
        if _keyword_present(normalized_answer, keyword)
    ]
    missing = [
        display
        for display, keyword in prepared
        if not _keyword_present(normalized_answer, keyword)
    ]
    coverage = len(matched) / len(prepared)
    all_matched = not missing
    return AnswerMetrics(
        valid=True,
        keyword_coverage=coverage,
        all_keywords_matched=all_matched,
        passed=all_matched if require_all else coverage >= required_coverage,
        required_coverage=required_coverage,
        matched_keywords=matched,
        missing_keywords=missing,
    )


def average_latency_ms(latencies_ms: Iterable[float]) -> float:
    """Return arithmetic mean latency after finite, non-negative validation."""
    values = list(latencies_ms)
    if not values:
        raise UndefinedMetricError("average latency requires at least one value")
    for value in values:
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
            or value < 0
        ):
            raise ValueError("latencies must be finite, non-negative numbers")
    return fmean(float(value) for value in values)


def rerank_gain(
    before_ids: Iterable[str],
    after_ids: Iterable[str],
    relevant_ids: Iterable[str],
) -> float:
    """Return first-relevant rank before minus rank after; positive is better."""
    before_rank = _first_relevant_rank(before_ids, relevant_ids)
    after_rank = _first_relevant_rank(after_ids, relevant_ids)
    if before_rank is None or after_rank is None:
        raise UndefinedMetricError(
            "rerank gain requires a relevant result in both rankings"
        )
    return float(before_rank - after_rank)


def evaluate_sample(
    sample_id: str,
    retrieved_ids: Iterable[str],
    relevant_ids: Iterable[str],
    *,
    ks: Iterable[int] = (1, 3, 5, 10),
    answer: str | None = None,
    expected_keywords: Iterable[str] | None = None,
    require_all_keywords: bool = True,
    minimum_keyword_coverage: float = 0.5,
    latency_ms: float | None = None,
    before_rerank_ids: Iterable[str] | None = None,
) -> SampleEvaluationResult:
    """Build the stable single-sample result consumed by the experiment runner."""
    if (answer is None) != (expected_keywords is None):
        raise ValueError("answer and expected_keywords must be provided together")
    retrieved = _unique_ids(retrieved_ids, name="retrieved_ids")
    relevant = _unique_ids(relevant_ids, name="relevant_ids")
    answer_metrics = (
        evaluate_answer(
            answer,
            expected_keywords,
            require_all=require_all_keywords,
            minimum_coverage=minimum_keyword_coverage,
        )
        if answer is not None and expected_keywords is not None
        else None
    )
    gain = None
    if before_rerank_ids is not None and relevant:
        gain = rerank_gain(before_rerank_ids, retrieved, relevant)
    return SampleEvaluationResult(
        sample_id=sample_id,
        retrieval=evaluate_retrieval(retrieved, relevant, ks=ks),
        answer=answer_metrics,
        latency_ms=latency_ms,
        rerank_gain=gain,
    )


def aggregate_results(
    results: Sequence[SampleEvaluationResult],
    *,
    ks: Iterable[int] = (1, 3, 5, 10),
) -> AggregateEvaluationResult:
    """Compute macro averages while retaining invalid/skipped sample counts."""
    cutoffs = _cutoffs(ks)
    sample_ids = [result.sample_id for result in results]
    if len(sample_ids) != len(set(sample_ids)):
        raise ValueError("sample_id values must be unique during aggregation")

    valid = [result for result in results if result.retrieval.valid]
    skipped = len(results) - len(valid)
    for result in valid:
        missing = [
            k
            for k in cutoffs
            if k not in result.retrieval.hit_rate_at_k
            or k not in result.retrieval.recall_at_k
        ]
        if missing:
            raise ValueError(
                f"sample '{result.sample_id}' is missing cutoff metrics: {missing}"
            )

    hit_rates = {
        k: fmean(result.retrieval.hit_rate_at_k[k] for result in valid)
        if valid
        else None
        for k in cutoffs
    }
    recalls = {
        k: fmean(result.retrieval.recall_at_k[k] for result in valid)
        if valid
        else None
        for k in cutoffs
    }
    reciprocal_ranks = [
        result.retrieval.reciprocal_rank
        for result in valid
        if result.retrieval.reciprocal_rank is not None
    ]
    answers = [result.answer for result in results if result.answer is not None]
    valid_answers = [answer for answer in answers if answer.valid]
    latencies = [result.latency_ms for result in results if result.latency_ms is not None]
    gains = [result.rerank_gain for result in results if result.rerank_gain is not None]

    return AggregateEvaluationResult(
        sample_count=len(results),
        valid_sample_count=len(valid),
        skipped_sample_count=skipped,
        mean_hit_rate_at_k=hit_rates,
        mean_recall_at_k=recalls,
        mrr=fmean(reciprocal_ranks) if reciprocal_ranks else None,
        answer_sample_count=len(valid_answers),
        skipped_answer_sample_count=len(answers) - len(valid_answers),
        mean_keyword_coverage=fmean(
            answer.keyword_coverage
            for answer in valid_answers
            if answer.keyword_coverage is not None
        )
        if valid_answers
        else None,
        keyword_pass_rate=fmean(
            float(answer.passed) for answer in valid_answers
        )
        if valid_answers
        else None,
        average_latency_ms=average_latency_ms(latencies) if latencies else None,
        mean_rerank_gain=fmean(gains) if gains else None,
    )
