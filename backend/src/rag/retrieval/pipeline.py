"""Unified dense, hybrid, and second-stage rerank orchestration."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from time import perf_counter
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from src.config import Settings
from src.rag.retrieval.exceptions import (
    RetrievalPathUnavailableError,
    RetrievalUnavailableError,
)
from src.rag.retrieval.fusion import reciprocal_rank_fusion
from src.rag.retrieval.reranker import (
    Reranker,
    RerankerConfigurationError,
    RerankerError,
    RerankerInputError,
    RerankerRequestError,
    RerankerResponseError,
)
from src.rag.schemas import SearchHit


class RankedRetriever(Protocol):
    """Synchronous ranked retrieval capability used by the pipeline."""

    def retrieve(
        self,
        query: str,
        *,
        top_n: int | None = None,
    ) -> list[SearchHit]:
        """Return ranked SearchHits with an optional candidate limit."""
        ...


RetrievalSource = Literal["dense", "bm25"]


class FusionFunction(Protocol):
    """Rank fusion capability injected for deterministic pipeline tests."""

    def __call__(
        self,
        dense_hits: Sequence[SearchHit],
        bm25_hits: Sequence[SearchHit],
        *,
        k: int,
        top_n: int | None,
    ) -> list[SearchHit]:
        """Fuse two bounded rankings into unified SearchHits."""
        ...


class RetrievalPipelineConfigurationError(ValueError):
    """Raised when retrieval pipeline dependencies or options are invalid."""


class RetrievalPipelineInputError(ValueError):
    """Raised when a pipeline query is blank or invalid."""


class RetrievalHitDiagnostic(BaseModel):
    """Text-free score snapshot for one hit at one retrieval stage."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str
    dense_score: float | None = None
    bm25_score: float | None = None
    fused_score: float | None = None
    rerank_score: float | None = None


class RetrievalDiagnostics(BaseModel):
    """Request-local counts, degradation state, and stage timings."""

    model_config = ConfigDict(frozen=True)

    mode: Literal["dense", "bm25", "hybrid"]
    requested_mode: Literal["dense", "hybrid"]
    rrf_entered: bool
    rerank_entered: bool
    final_count: int
    dense_count: int
    bm25_count: int
    fused_count: int
    rerank_input_count: int
    rerank_output_count: int
    reranker_enabled: bool
    reranker_degraded: bool = False
    degraded_reason: str | None = None
    degradation_codes: tuple[str, ...] = ()
    degraded_sources: tuple[RetrievalSource, ...] = ()
    dense_results: tuple[RetrievalHitDiagnostic, ...] = ()
    bm25_results: tuple[RetrievalHitDiagnostic, ...] = ()
    fused_results: tuple[RetrievalHitDiagnostic, ...] = ()
    rerank_results: tuple[RetrievalHitDiagnostic, ...] = ()
    dense_latency_ms: float = Field(ge=0.0)
    bm25_latency_ms: float = Field(ge=0.0)
    fusion_latency_ms: float = Field(ge=0.0)
    rerank_latency_ms: float = Field(ge=0.0)
    total_latency_ms: float = Field(ge=0.0)


class RetrievalResult(BaseModel):
    """Request-local retrieval hits and their matching diagnostics."""

    model_config = ConfigDict(frozen=True)

    hits: list[SearchHit] = Field(default_factory=list)
    diagnostics: RetrievalDiagnostics


class HybridRetrievalPipeline:
    """Retrieve candidates, optionally fuse them, then rerank final hits."""

    def __init__(
        self,
        dense_retriever: RankedRetriever,
        bm25_retriever: RankedRetriever | None = None,
        *,
        reranker: Reranker | None = None,
        settings: Settings | None = None,
        hybrid_enabled: bool | None = None,
        reranker_enabled: bool | None = None,
        dense_top_n: int | None = None,
        bm25_top_n: int | None = None,
        retrieve_top_n: int | None = None,
        rerank_top_k: int | None = None,
        rrf_k: int | None = None,
        fusion: FusionFunction = reciprocal_rank_fusion,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        """Configure candidate recall, fusion, rerank, and timing boundaries."""
        configured = settings or Settings()
        self.hybrid_enabled = (
            configured.hybrid_retrieval_enabled
            if hybrid_enabled is None
            else hybrid_enabled
        )
        self.reranker_enabled = (
            configured.reranker_enabled
            if reranker_enabled is None
            else reranker_enabled
        )
        self.dense_top_n = (
            configured.dense_top_n if dense_top_n is None else dense_top_n
        )
        self.bm25_top_n = (
            configured.bm25_top_n if bm25_top_n is None else bm25_top_n
        )
        self.retrieve_top_n = (
            configured.retrieve_top_n
            if retrieve_top_n is None
            else retrieve_top_n
        )
        self.rerank_top_k = (
            configured.rerank_top_k if rerank_top_k is None else rerank_top_k
        )
        self.rrf_k = configured.rrf_k if rrf_k is None else rrf_k
        self._validate_configuration(bm25_retriever, reranker)

        self.dense_retriever = dense_retriever
        self.bm25_retriever = bm25_retriever
        self.reranker = reranker
        self.fusion = fusion
        self.clock = clock

    def retrieve(self, query: str) -> list[SearchHit]:
        """Preserve the Agent Retriever contract by returning final hits only."""
        return self.retrieve_with_diagnostics(query).hits

    def retrieve_with_diagnostics(self, query: str) -> RetrievalResult:
        """Return final hits and diagnostics bound to this request only."""
        if not isinstance(query, str) or not query.strip():
            raise RetrievalPipelineInputError(
                "Retrieval query must be a non-empty string"
            )
        normalized_query = query.strip()
        total_started = self.clock()
        degraded_sources: list[RetrievalSource] = []
        path_failure_codes: dict[RetrievalSource, str] = {}

        dense_started = self.clock()
        dense_hits = self._retrieve_path(
            self.dense_retriever,
            normalized_query,
            "dense",
            degraded_sources,
            path_failure_codes,
            top_n=self.dense_top_n,
        )[: self.dense_top_n]
        dense_latency_ms = self._elapsed_ms(dense_started)

        bm25_hits: list[SearchHit] = []
        bm25_latency_ms = 0.0
        fusion_latency_ms = 0.0
        if self.hybrid_enabled:
            if self.bm25_retriever is None:
                raise RetrievalPipelineConfigurationError(
                    "Hybrid retrieval requires a BM25 retriever"
                )
            bm25_started = self.clock()
            bm25_hits = self._retrieve_path(
                self.bm25_retriever,
                normalized_query,
                "bm25",
                degraded_sources,
                path_failure_codes,
                top_n=self.bm25_top_n,
            )[: self.bm25_top_n]
            bm25_latency_ms = self._elapsed_ms(bm25_started)

            if len(degraded_sources) == 2:
                raise RetrievalUnavailableError()
            fusion_started = self.clock()
            candidates = self.fusion(
                dense_hits,
                bm25_hits,
                k=self.rrf_k,
                top_n=self.retrieve_top_n,
            )
            fusion_latency_ms = self._elapsed_ms(fusion_started)
            fused_count = len(candidates)
            mode: Literal["dense", "bm25", "hybrid"] = (
                "bm25" if degraded_sources == ["dense"] else
                "dense" if degraded_sources == ["bm25"] else
                "hybrid"
            )
        else:
            if degraded_sources:
                raise RetrievalUnavailableError()
            candidates = dense_hits[: self.retrieve_top_n]
            fused_count = 0
            mode = "dense"

        rerank_input_count = 0
        rerank_output_count = 0
        rerank_latency_ms = 0.0
        reranker_degraded = False
        degradation_codes = [path_failure_codes[source] for source in degraded_sources]
        final_hits = candidates[: self.rerank_top_k]

        if self.reranker_enabled and candidates:
            if self.reranker is None:
                raise RetrievalPipelineConfigurationError(
                    "Enabled reranking requires a Reranker"
                )
            rerank_input_count = len(candidates)
            rerank_started = self.clock()
            try:
                final_hits = self.reranker.rerank(normalized_query, candidates)
                final_hits = final_hits[: self.rerank_top_k]
                rerank_output_count = len(final_hits)
            except RerankerError as exc:
                reranker_degraded = True
                degradation_codes.append(self._reranker_failure_code(exc))
                final_hits = candidates[: self.rerank_top_k]
            rerank_latency_ms = self._elapsed_ms(rerank_started)

        diagnostics = RetrievalDiagnostics(
            mode=mode,
            requested_mode="hybrid" if self.hybrid_enabled else "dense",
            rrf_entered=self.hybrid_enabled,
            rerank_entered=self.reranker_enabled and bool(candidates),
            final_count=len(final_hits),
            dense_count=len(dense_hits),
            bm25_count=len(bm25_hits),
            fused_count=fused_count,
            rerank_input_count=rerank_input_count,
            rerank_output_count=rerank_output_count,
            reranker_enabled=self.reranker_enabled,
            reranker_degraded=reranker_degraded,
            degraded_reason=(
                ",".join(degradation_codes) if degradation_codes else None
            ),
            degradation_codes=tuple(degradation_codes),
            degraded_sources=tuple(degraded_sources),
            dense_results=self._diagnostic_hits(dense_hits),
            bm25_results=self._diagnostic_hits(bm25_hits),
            fused_results=self._diagnostic_hits(candidates),
            rerank_results=self._diagnostic_hits(final_hits),
            dense_latency_ms=dense_latency_ms,
            bm25_latency_ms=bm25_latency_ms,
            fusion_latency_ms=fusion_latency_ms,
            rerank_latency_ms=rerank_latency_ms,
            total_latency_ms=self._elapsed_ms(total_started),
        )
        return RetrievalResult(hits=final_hits, diagnostics=diagnostics)

    def _elapsed_ms(self, started: float) -> float:
        """Return a non-negative elapsed duration from the injected clock."""
        return max(0.0, (self.clock() - started) * 1000.0)

    @staticmethod
    def _diagnostic_hits(
        hits: Sequence[SearchHit],
    ) -> tuple[RetrievalHitDiagnostic, ...]:
        """Strip document text and metadata from an ordered stage snapshot."""
        return tuple(
            RetrievalHitDiagnostic(
                chunk_id=hit.chunk_id,
                dense_score=hit.dense_score,
                bm25_score=hit.bm25_score,
                fused_score=hit.fused_score,
                rerank_score=hit.rerank_score,
            )
            for hit in hits
        )

    @staticmethod
    def _retrieve_path(
        retriever: RankedRetriever,
        query: str,
        source: RetrievalSource,
        degraded: list[RetrievalSource],
        failure_codes: dict[RetrievalSource, str],
        *,
        top_n: int,
    ) -> list[SearchHit]:
        """Return one path or record a recognized external-service failure."""
        try:
            return list(retriever.retrieve(query, top_n=top_n))
        except RetrievalPathUnavailableError as exc:
            if source == "bm25" and exc.path != "bm25":
                raise
            if source == "dense" and exc.path not in {"dense", "vector_store"}:
                raise
            degraded.append(source)
            failure_codes[source] = exc.code
            return []

    @staticmethod
    def _reranker_failure_code(exc: Exception) -> str:
        """Map an internal reranker exception to a safe diagnostic code."""
        if isinstance(exc, RerankerRequestError):
            return "reranker_request_failed"
        if isinstance(exc, RerankerResponseError):
            return "reranker_response_invalid"
        if isinstance(exc, RerankerConfigurationError):
            return "reranker_configuration_invalid"
        if isinstance(exc, RerankerInputError):
            return "reranker_input_invalid"
        return "reranker_failed"

    def _validate_configuration(
        self,
        bm25_retriever: RankedRetriever | None,
        reranker: Reranker | None,
    ) -> None:
        """Validate modes, dependencies, and candidate-limit semantics."""
        if not isinstance(self.hybrid_enabled, bool):
            raise RetrievalPipelineConfigurationError(
                "hybrid_enabled must be a boolean"
            )
        if not isinstance(self.reranker_enabled, bool):
            raise RetrievalPipelineConfigurationError(
                "reranker_enabled must be a boolean"
            )
        for name, value in (
            ("dense_top_n", self.dense_top_n),
            ("bm25_top_n", self.bm25_top_n),
            ("retrieve_top_n", self.retrieve_top_n),
            ("rerank_top_k", self.rerank_top_k),
            ("rrf_k", self.rrf_k),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
            ):
                raise RetrievalPipelineConfigurationError(
                    f"{name} must be a positive integer"
                )
        if self.dense_top_n < self.retrieve_top_n:
            raise RetrievalPipelineConfigurationError(
                "dense_top_n must be at least retrieve_top_n"
            )
        if self.hybrid_enabled and self.bm25_top_n < self.retrieve_top_n:
            raise RetrievalPipelineConfigurationError(
                "bm25_top_n must be at least retrieve_top_n"
            )
        if self.hybrid_enabled and bm25_retriever is None:
            raise RetrievalPipelineConfigurationError(
                "Hybrid retrieval requires a BM25 retriever"
            )
        if self.reranker_enabled and reranker is None:
            raise RetrievalPipelineConfigurationError(
                "Enabled reranking requires a Reranker"
            )
