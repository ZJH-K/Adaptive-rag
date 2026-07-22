"""Shared state and structured-output contracts for the RAG workflow."""

from operator import add
from typing import Annotated, Any, TypedDict

from pydantic import BaseModel, ConfigDict, StringConstraints

from src.agent.failures import WorkflowFailure, WorkflowStage
from src.observability.tracing import TracingStatus
from src.rag.context_builder import ContextSource
from src.rag.retrieval.pipeline import RetrievalDiagnostics
from src.rag.schemas import SearchHit


NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class AgentState(TypedDict, total=False):
    """State passed between nodes in the lightweight adaptive RAG graph."""

    question: str
    chat_history: list[dict[str, Any]]

    need_retrieval: bool
    route_reason: str

    rewritten_query: str
    retrieved_documents: list[SearchHit]
    context: str
    context_sources: list[ContextSource]
    context_chunk_ids: list[str]
    retrieval_diagnostics: RetrievalDiagnostics
    answer: str

    current_stage: WorkflowStage
    degradation_events: Annotated[list[WorkflowFailure], add]
    fatal_error: WorkflowFailure | None
    answer_available: bool

    request_id: str
    trace_id: str | None
    tracing_status: TracingStatus


class RouteDecision(BaseModel):
    """Validated structured output returned by the query router."""

    model_config = ConfigDict(extra="forbid", strict=True)

    need_retrieval: bool
    reason: NonEmptyText


class RewriteResult(BaseModel):
    """Validated structured output returned by the query rewriter."""

    model_config = ConfigDict(extra="forbid", strict=True)

    rewritten_query: NonEmptyText
