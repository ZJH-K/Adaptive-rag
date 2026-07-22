"""Typed chat request and Server-Sent Event contracts."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from src.rag.context_builder import ContextSource


QuestionText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4000),
]
HistoryText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4000),
]


class ChatHistoryMessage(BaseModel):
    """One bounded in-request conversation message."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["user", "assistant"]
    content: HistoryText


class ChatStreamRequest(BaseModel):
    """Validated request accepted before an SSE response is opened."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    question: QuestionText
    knowledge_base_id: str = Field(min_length=1, max_length=128)
    chat_history: list[ChatHistoryMessage] = Field(
        default_factory=list,
        max_length=20,
    )


class RouteEventData(BaseModel):
    """Observable routing decision without hidden model reasoning."""

    need_retrieval: bool
    reason: str


class RewriteEventData(BaseModel):
    """Standalone query selected for retrieval."""

    rewritten_query: str


class RetrievalHitSummary(BaseModel):
    """Text-free final retrieval hit diagnostic."""

    chunk_id: str
    source: str | None = None
    page: int | None = None
    section: str | None = None
    heading_path: list[str] = Field(default_factory=list)
    dense_score: float | None = None
    bm25_score: float | None = None
    fused_score: float | None = None
    rerank_score: float | None = None


class RetrievalEventData(BaseModel):
    """Safe request-local retrieval and degradation diagnostics."""

    mode: Literal["dense", "bm25", "hybrid", "unknown"]
    dense_count: int = Field(ge=0)
    bm25_count: int = Field(ge=0)
    fused_count: int = Field(ge=0)
    final_count: int = Field(ge=0)
    rrf_entered: bool
    rerank_entered: bool
    reranker_degraded: bool
    degradation_codes: list[str] = Field(default_factory=list)
    degraded_sources: list[Literal["dense", "bm25"]] = Field(default_factory=list)
    total_latency_ms: float = Field(ge=0.0)
    hits: list[RetrievalHitSummary] = Field(default_factory=list)


class TokenEventData(BaseModel):
    """One unmodified provider text delta."""

    text: str


class SourcesEventData(BaseModel):
    """Exact ContextBuilder sources used in the generation prompt."""

    sources: list[ContextSource] = Field(default_factory=list)
    context_chunk_ids: list[str] = Field(default_factory=list)


class ErrorEventData(BaseModel):
    """Secret-free terminal stream error."""

    code: str
    message: str
    retryable: bool


class DoneEventData(BaseModel):
    """Request and provider-trace terminal state."""

    status: Literal["success", "failed", "cancelled"]
    request_id: str
    trace_id: str | None = None
    tracing_enabled: bool
    tracing_configured: bool
    tracing_available: bool
    trace_exported: bool
    trace_error_code: str | None = None


class RouteEvent(BaseModel):
    """SSE route event."""

    event: Literal["route"] = "route"
    data: RouteEventData


class RewriteEvent(BaseModel):
    """SSE rewrite event."""

    event: Literal["rewrite"] = "rewrite"
    data: RewriteEventData


class RetrievalEvent(BaseModel):
    """SSE retrieval event."""

    event: Literal["retrieval"] = "retrieval"
    data: RetrievalEventData


class TokenEvent(BaseModel):
    """SSE token event."""

    event: Literal["token"] = "token"
    data: TokenEventData


class SourcesEvent(BaseModel):
    """SSE sources event."""

    event: Literal["sources"] = "sources"
    data: SourcesEventData


class ErrorEvent(BaseModel):
    """SSE error event."""

    event: Literal["error"] = "error"
    data: ErrorEventData


class DoneEvent(BaseModel):
    """SSE done event."""

    event: Literal["done"] = "done"
    data: DoneEventData


ChatSSEEvent: TypeAlias = (
    RouteEvent
    | RewriteEvent
    | RetrievalEvent
    | TokenEvent
    | SourcesEvent
    | ErrorEvent
    | DoneEvent
)


def encode_sse_event(event: ChatSSEEvent) -> str:
    """Serialize one typed event as UTF-8-compatible SSE text."""
    return f"event: {event.event}\ndata: {event.data.model_dump_json()}\n\n"
