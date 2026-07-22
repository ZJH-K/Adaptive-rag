"""Unified dense-only and hybrid retrieval orchestration."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from src.config import Settings
from src.rag.embeddings.exceptions import EmbeddingRequestError
from src.rag.retrieval.fusion import reciprocal_rank_fusion
from src.rag.schemas import SearchHit


class RankedRetriever(Protocol):
    """Synchronous ranked retrieval capability used by the pipeline."""

    def retrieve(self, query: str) -> list[SearchHit]:
        """Return ranked SearchHits for one normalized query."""
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


@dataclass(frozen=True, slots=True)
class RetrievalDiagnostics:
    """Observable summary of one completed retrieval attempt."""

    mode: Literal["dense", "hybrid"]
    dense_count: int
    bm25_count: int
    degraded_sources: tuple[RetrievalSource, ...] = ()


class HybridRetrievalPipeline:
    """Expose one Retriever interface over dense retrieval and optional RRF."""

    def __init__(
        self,
        dense_retriever: RankedRetriever,
        bm25_retriever: RankedRetriever | None = None,
        *,
        settings: Settings | None = None,
        hybrid_enabled: bool | None = None,
        dense_top_n: int | None = None,
        bm25_top_n: int | None = None,
        fusion_top_n: int | None = None,
        rrf_k: int | None = None,
        fusion: FusionFunction = reciprocal_rank_fusion,
    ) -> None:
        """Configure retrieval modes and independently bounded candidate lists."""
        configured = settings or Settings()
        self.hybrid_enabled = (
            configured.hybrid_retrieval_enabled
            if hybrid_enabled is None
            else hybrid_enabled
        )
        self.dense_top_n = (
            configured.dense_top_n if dense_top_n is None else dense_top_n
        )
        self.bm25_top_n = (
            configured.bm25_top_n if bm25_top_n is None else bm25_top_n
        )
        self.fusion_top_n = (
            configured.fusion_top_n if fusion_top_n is None else fusion_top_n
        )
        self.rrf_k = configured.rrf_k if rrf_k is None else rrf_k
        self._validate_configuration(bm25_retriever)

        self.dense_retriever = dense_retriever
        self.bm25_retriever = bm25_retriever
        self.fusion = fusion
        self.last_diagnostics: RetrievalDiagnostics | None = None

    def retrieve(self, query: str) -> list[SearchHit]:
        """Retrieve one query, degrading only known external retrieval errors."""
        self.last_diagnostics = None
        if not isinstance(query, str) or not query.strip():
            raise RetrievalPipelineInputError(
                "Retrieval query must be a non-empty string"
            )
        normalized_query = query.strip()
        degraded: list[RetrievalSource] = []

        dense_hits = self._retrieve_path(
            self.dense_retriever,
            normalized_query,
            "dense",
            degraded,
        )[: self.dense_top_n]
        if not self.hybrid_enabled:
            self.last_diagnostics = RetrievalDiagnostics(
                mode="dense",
                dense_count=len(dense_hits),
                bm25_count=0,
                degraded_sources=tuple(degraded),
            )
            return dense_hits

        if self.bm25_retriever is None:
            raise RetrievalPipelineConfigurationError(
                "Hybrid retrieval requires a BM25 retriever"
            )
        bm25_hits = self._retrieve_path(
            self.bm25_retriever,
            normalized_query,
            "bm25",
            degraded,
        )[: self.bm25_top_n]
        fused = self.fusion(
            dense_hits,
            bm25_hits,
            k=self.rrf_k,
            top_n=self.fusion_top_n,
        )
        self.last_diagnostics = RetrievalDiagnostics(
            mode="hybrid",
            dense_count=len(dense_hits),
            bm25_count=len(bm25_hits),
            degraded_sources=tuple(degraded),
        )
        return fused

    @staticmethod
    def _retrieve_path(
        retriever: RankedRetriever,
        query: str,
        source: RetrievalSource,
        degraded: list[RetrievalSource],
    ) -> list[SearchHit]:
        """Return one path or record a recognized external-service failure."""
        try:
            return list(retriever.retrieve(query))
        except EmbeddingRequestError:
            degraded.append(source)
            return []

    def _validate_configuration(
        self,
        bm25_retriever: RankedRetriever | None,
    ) -> None:
        """Validate mode and positive integer retrieval parameters."""
        if not isinstance(self.hybrid_enabled, bool):
            raise RetrievalPipelineConfigurationError(
                "hybrid_enabled must be a boolean"
            )
        for name, value in (
            ("dense_top_n", self.dense_top_n),
            ("bm25_top_n", self.bm25_top_n),
            ("fusion_top_n", self.fusion_top_n),
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
        if self.hybrid_enabled and bm25_retriever is None:
            raise RetrievalPipelineConfigurationError(
                "Hybrid retrieval requires a BM25 retriever"
            )
