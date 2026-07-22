"""Safe, structured failure contracts for workflow consumers."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.llm.exceptions import (
    LLMConfigurationError,
    LLMInputError,
    LLMRequestError,
    LLMResponseError,
    LLMTimeoutError,
)


WorkflowStage = Literal[
    "router",
    "rewrite",
    "retrieval",
    "rerank",
    "context",
    "direct_answer",
    "generation",
]


class WorkflowFailure(BaseModel):
    """Public, secret-free description of one workflow failure."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    stage: WorkflowStage
    error_type: str
    safe_message: str
    degraded: bool
    fatal: bool
    fallback_used: bool
    fallback: str | None = None
    duration_ms: float = Field(ge=0.0)
    provider: str | None = None
    code: str | None = None


def classify_llm_failure(exc: Exception) -> tuple[str, str]:
    """Map an LLM exception to stable public type and code values."""

    if isinstance(exc, LLMTimeoutError):
        return "timeout", "llm_timeout"
    if isinstance(exc, LLMResponseError):
        return "invalid_response", "llm_response_invalid"
    if isinstance(exc, LLMConfigurationError):
        return "configuration_error", "llm_configuration_invalid"
    if isinstance(exc, LLMInputError):
        return "invalid_input", "llm_input_invalid"
    if isinstance(exc, LLMRequestError):
        return "provider_unavailable", "llm_request_failed"
    return "llm_error", "llm_failed"
