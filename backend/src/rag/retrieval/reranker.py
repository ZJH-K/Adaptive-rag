"""Provider client and immutable adapter for second-stage reranking."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any, Protocol
from threading import Lock
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field

from src.config import Settings
from src.rag.schemas import SearchHit


class RerankerError(RuntimeError):
    """Base class for safe, public reranker failures."""


class RerankerConfigurationError(RerankerError):
    """Raised when the reranker service configuration is invalid."""


class RerankerInputError(ValueError, RerankerError):
    """Raised when a query or candidate list violates the input contract."""


class RerankerRequestError(RerankerError):
    """Raised when the external reranker request fails."""


class RerankerResponseError(RerankerError):
    """Raised when a provider response violates the rerank contract."""


class RerankScore(BaseModel):
    """Normalized provider score mapped to one input document index."""

    model_config = ConfigDict(frozen=True, strict=True)

    index: int = Field(ge=0)
    score: float = Field(allow_inf_nan=False)


class RerankerStatus(BaseModel):
    """Safe readiness state exposed to application health checks."""

    model_config = ConfigDict(frozen=True)

    enabled: bool
    configured: bool
    available: bool
    model: str
    last_error_code: str | None = None


class RerankTransport(Protocol):
    """Minimal injectable HTTP transport used by the provider client."""

    def post(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout: float,
    ) -> bytes | str | Mapping[str, Any]:
        """Submit one JSON request and return raw or decoded JSON data."""
        ...


class UrllibRerankTransport:
    """Small standard-library JSON transport for the SiliconFlow endpoint."""

    def post(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout: float,
    ) -> bytes:
        """POST a JSON payload and return the response body."""
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=dict(headers),
            method="POST",
        )
        with urlopen(request, timeout=timeout) as response:
            return response.read()


class RerankScoringClient(Protocol):
    """Provider-independent score capability consumed by the adapter."""

    def score(self, query: str, documents: list[str]) -> list[RerankScore]:
        """Return exactly one normalized score for every input document."""
        ...


class Reranker(Protocol):
    """Stable second-stage ranking contract used by retrieval orchestration."""

    def rerank(self, query: str, hits: list[SearchHit]) -> list[SearchHit]:
        """Return newly copied SearchHits in reranked order."""
        ...


class RerankerClient:
    """Call and strictly validate a SiliconFlow-compatible rerank service."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        transport: RerankTransport | None = None,
    ) -> None:
        """Initialize provider configuration without making a request."""
        configured = settings or Settings()
        self.base_url = (
            configured.reranker_base_url if base_url is None else base_url
        )
        self.api_key = (
            configured.reranker_api_key if api_key is None else api_key
        )
        self.model = configured.reranker_model if model is None else model
        self.timeout_seconds = (
            configured.reranker_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        self.transport = transport or UrllibRerankTransport()
        self._validate_configuration()

    def score(self, query: str, documents: list[str]) -> list[RerankScore]:
        """Submit all query-document pairs in one request and validate scores."""
        if not documents:
            return []
        self._validate_inputs(query, documents)
        if not isinstance(self.api_key, str) or not self.api_key.strip():
            raise RerankerConfigurationError("Reranker API key is required")

        payload: dict[str, Any] = {
            "model": self.model,
            "query": query,
            "documents": list(documents),
            "top_n": len(documents),
            "return_documents": False,
        }
        try:
            raw_response = self.transport.post(
                url=f"{self.base_url.rstrip('/')}/rerank",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                payload=payload,
                timeout=float(self.timeout_seconds),
            )
        except Exception as exc:
            raise RerankerRequestError(
                f"Reranker request failed ({type(exc).__name__})"
            ) from exc
        response = self._decode_response(raw_response)
        return self._parse_scores(response, expected_count=len(documents))

    def _validate_configuration(self) -> None:
        """Validate non-secret constructor configuration."""
        if not isinstance(self.base_url, str) or not self.base_url.strip():
            raise RerankerConfigurationError("Reranker base URL is required")
        if not isinstance(self.model, str) or not self.model.strip():
            raise RerankerConfigurationError("Reranker model is required")
        if (
            not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.timeout_seconds, bool)
            or not math.isfinite(float(self.timeout_seconds))
            or self.timeout_seconds <= 0
        ):
            raise RerankerConfigurationError(
                "Reranker timeout must be greater than zero"
            )

    @staticmethod
    def _validate_inputs(query: str, documents: list[str]) -> None:
        """Reject blank query or document values before external I/O."""
        if not isinstance(query, str) or not query.strip():
            raise RerankerInputError("Reranker query must be a non-empty string")
        for index, document in enumerate(documents):
            if not isinstance(document, str) or not document.strip():
                raise RerankerInputError(
                    f"Reranker document at index {index} must be non-empty"
                )

    @staticmethod
    def _decode_response(
        response: bytes | str | Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Decode JSON without exposing provider response content in errors."""
        if isinstance(response, Mapping):
            return response
        if isinstance(response, bytes):
            try:
                response = response.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise RerankerResponseError(
                    "Reranker response is not valid UTF-8"
                ) from exc
        if not isinstance(response, str) or not response.strip():
            raise RerankerResponseError("Reranker response is empty")
        try:
            decoded = json.loads(response)
        except json.JSONDecodeError as exc:
            raise RerankerResponseError(
                "Reranker response is not valid JSON"
            ) from exc
        if not isinstance(decoded, Mapping):
            raise RerankerResponseError("Reranker response must be a JSON object")
        return decoded

    @staticmethod
    def _parse_scores(
        response: Mapping[str, Any],
        *,
        expected_count: int,
    ) -> list[RerankScore]:
        """Validate indices and scores, then normalize provider field names."""
        results = response.get("results")
        if not isinstance(results, Sequence) or isinstance(results, (str, bytes)):
            raise RerankerResponseError(
                "Reranker response has no valid results list"
            )

        parsed: list[RerankScore] = []
        seen: set[int] = set()
        for item in results:
            if not isinstance(item, Mapping):
                raise RerankerResponseError("Reranker result item is invalid")
            index = item.get("index")
            if not isinstance(index, int) or isinstance(index, bool):
                raise RerankerResponseError("Reranker result index is invalid")
            if index < 0 or index >= expected_count:
                raise RerankerResponseError("Reranker result index is out of range")
            if index in seen:
                raise RerankerResponseError("Reranker result index is duplicated")

            has_relevance = "relevance_score" in item
            has_score = "score" in item
            if has_relevance == has_score:
                raise RerankerResponseError(
                    "Reranker result must contain exactly one score field"
                )
            score = item["relevance_score"] if has_relevance else item["score"]
            if (
                not isinstance(score, (int, float))
                or isinstance(score, bool)
                or not math.isfinite(float(score))
            ):
                raise RerankerResponseError("Reranker result score is invalid")
            parsed.append(RerankScore(index=index, score=float(score)))
            seen.add(index)

        expected_indices = set(range(expected_count))
        if seen != expected_indices:
            raise RerankerResponseError(
                "Reranker response is missing one or more document scores"
            )
        return parsed


class RerankerAdapter:
    """Map provider scores onto copies of unified SearchHit candidates."""

    def __init__(
        self,
        client: RerankScoringClient,
        *,
        top_k: int = 5,
        model: str = "configured-reranker",
    ) -> None:
        """Configure the scoring client and final result limit."""
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k <= 0:
            raise RerankerConfigurationError(
                "Reranker top_k must be a positive integer"
            )
        self.client = client
        self.top_k = top_k
        self.model = model
        self._last_error_code: str | None = None
        self._status_lock = Lock()

    def rerank(self, query: str, hits: list[SearchHit]) -> list[SearchHit]:
        """Return copied hits sorted by score and original-position tie-break."""
        if not hits:
            return []
        try:
            scores = self.client.score(query, [hit.text for hit in hits])
        except RerankerError as exc:
            with self._status_lock:
                self._last_error_code = _reranker_error_code(exc)
            raise
        with self._status_lock:
            self._last_error_code = None
        if len(scores) != len(hits):
            raise RerankerResponseError(
                "Reranker client returned an unexpected score count"
            )

        mapped: list[tuple[int, float, SearchHit]] = []
        seen: set[int] = set()
        for result in scores:
            if result.index < 0 or result.index >= len(hits):
                raise RerankerResponseError("Reranker score index is out of range")
            if result.index in seen:
                raise RerankerResponseError("Reranker score index is duplicated")
            seen.add(result.index)
            mapped.append(
                (
                    result.index,
                    result.score,
                    hits[result.index].model_copy(
                        update={"rerank_score": result.score},
                        deep=True,
                    ),
                )
            )
        if seen != set(range(len(hits))):
            raise RerankerResponseError(
                "Reranker client omitted one or more candidate scores"
            )
        mapped.sort(
            key=lambda item: (
                -item[1],
                item[0],
            )
        )
        return [hit for _, _, hit in mapped[: self.top_k]]

    def get_status(self) -> RerankerStatus:
        """Return current configured readiness and last safe runtime error."""
        with self._status_lock:
            error_code = self._last_error_code
        return RerankerStatus(
            enabled=True,
            configured=True,
            available=error_code is None,
            model=self.model,
            last_error_code=error_code,
        )


class NoOpReranker:
    """Disabled-mode implementation that performs no external work."""

    def rerank(self, query: str, hits: list[SearchHit]) -> list[SearchHit]:
        """Return independent copies while preserving the input ranking."""
        return [hit.model_copy(deep=True) for hit in hits]

    def __init__(self, model: str = "disabled") -> None:
        self.model = model

    def get_status(self) -> RerankerStatus:
        """Report the intentional disabled state."""
        return RerankerStatus(
            enabled=False,
            configured=False,
            available=False,
            model=self.model,
        )


def build_reranker(
    settings: Settings | None = None,
    *,
    client: RerankScoringClient | None = None,
    transport: RerankTransport | None = None,
) -> Reranker:
    """Build an enabled adapter or a disabled no-op implementation."""
    configured = settings or Settings()
    if not configured.reranker_enabled:
        return NoOpReranker(configured.reranker_model)
    if not configured.reranker_api_key and client is None:
        return UnavailableReranker(
            model=configured.reranker_model,
            error_code="reranker_not_configured",
        )
    scoring_client = client or RerankerClient(
        configured,
        transport=transport,
    )
    return RerankerAdapter(
        scoring_client,
        top_k=configured.rerank_top_k,
        model=configured.reranker_model,
    )


class UnavailableReranker:
    """Enabled but unavailable reranker with explicit health semantics."""

    def __init__(self, *, model: str, error_code: str) -> None:
        self.model = model
        self.error_code = error_code

    def rerank(self, query: str, hits: list[SearchHit]) -> list[SearchHit]:
        raise RerankerConfigurationError("Reranker is unavailable")

    def get_status(self) -> RerankerStatus:
        return RerankerStatus(
            enabled=True,
            configured=False,
            available=False,
            model=self.model,
            last_error_code=self.error_code,
        )


def get_reranker_status(reranker: Reranker) -> RerankerStatus:
    """Read readiness without coupling health checks to implementations."""
    getter = getattr(reranker, "get_status", None)
    if callable(getter):
        return getter()
    return RerankerStatus(
        enabled=True,
        configured=True,
        available=True,
        model="custom-reranker",
    )


def _reranker_error_code(exc: RerankerError) -> str:
    if isinstance(exc, RerankerRequestError):
        return "reranker_request_failed"
    if isinstance(exc, RerankerResponseError):
        return "reranker_response_invalid"
    if isinstance(exc, RerankerConfigurationError):
        return "reranker_not_configured"
    if isinstance(exc, RerankerInputError):
        return "reranker_input_invalid"
    return "reranker_failed"
