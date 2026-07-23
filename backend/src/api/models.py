"""Shared safe API response models."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class APIErrorDetail(BaseModel):
    """Secret-free error information returned to clients."""

    code: str
    message: str
    request_id: str


class APIErrorResponse(BaseModel):
    """Stable envelope for known and unknown API errors."""

    error: APIErrorDetail


class LivenessResponse(BaseModel):
    """Process liveness independent of runtime or provider readiness."""

    status: Literal["alive"] = "alive"


class ChromaHealth(BaseModel):
    """Local vector-store readiness without an external probe."""

    status: Literal["ready", "unavailable"]
    chunk_count: int = Field(default=0, ge=0)
    error_code: str | None = None


class BM25Health(BaseModel):
    """In-memory lexical index generation and consistency state."""

    status: Literal["ready", "degraded", "rebuilding", "unavailable"]
    generation: int = Field(default=0, ge=0)
    chunk_count: int = Field(default=0, ge=0)
    needs_rebuild: bool = False
    last_successful_rebuild_at: str | None = None
    last_error_code: str | None = None


class ModelHealth(BaseModel):
    """Static provider configuration readiness."""

    configured: bool
    model: str


class RerankerHealth(BaseModel):
    """Optional reranker enablement, configuration, and availability."""

    enabled: bool
    configured: bool
    available: bool
    model: str
    last_error_code: str | None = None


class TracingHealth(BaseModel):
    """Optional tracing enablement, configuration, and availability."""

    enabled: bool
    configured: bool
    available: bool
    last_error_code: str | None = None


class HealthResponse(BaseModel):
    """Local, non-invasive application readiness snapshot."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok", "degraded", "unavailable"]
    request_id: str
    chroma: ChromaHealth
    bm25: BM25Health
    llm: ModelHealth
    embedding: ModelHealth
    reranker: RerankerHealth
    tracing: TracingHealth


class DocumentUploadResponse(BaseModel):
    """Result published after vector and lexical index synchronization."""

    document_id: str
    filename: str
    chunks_count: int = Field(ge=0)
    status: Literal["done", "degraded"]
    duplicate: bool = False
    bm25_generation: int = Field(ge=0)
    error_code: str | None = None


class LoadDefaultRequest(BaseModel):
    """Optional controls for loading the configured built-in corpus."""

    knowledge_base_id: str | None = Field(default=None, min_length=1)
    chunk_strategy: Literal[
        "auto", "recursive", "markdown_heading", "pdf_page_aware"
    ] = "auto"


class LoadDefaultItem(BaseModel):
    """Safe per-file result in a built-in corpus batch."""

    filename: str
    status: Literal["done", "degraded", "skipped", "failed"]
    chunks_count: int = Field(default=0, ge=0)
    document_id: str | None = None
    error_code: str | None = None


class LoadDefaultResponse(BaseModel):
    """Aggregate result that cannot conceal individual file failures."""

    status: Literal["done", "degraded", "failed"]
    knowledge_base_id: str
    processed: int = Field(ge=0)
    skipped: int = Field(ge=0)
    failed: int = Field(ge=0)
    chunks_count: int = Field(ge=0)
    items: list[LoadDefaultItem]


class DocumentStatsResponse(BaseModel):
    """Statistics read from the live vector and BM25 indexes."""

    knowledge_base_id: str
    documents_count: int = Field(ge=0)
    chunks_count: int = Field(ge=0)
    chroma: ChromaHealth
    bm25: BM25Health
