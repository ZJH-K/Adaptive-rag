"""Stable request dependencies backed only by the lifespan container."""

from collections.abc import AsyncIterator
from typing import Any, Protocol

from fastapi import Request

from src.api.errors import ServiceUnavailableError
from src.api.sse import ChatSSEEvent, ChatStreamRequest
from src.config import Settings
from src.rag.ingestion import IngestionPipeline
from src.rag.runtime import RetrievalRuntime


class ChatService(Protocol):
    """Shared streaming workflow consumed by the chat route."""

    def stream(
        self,
        request: ChatStreamRequest,
        *,
        request_id: str,
        client_request_id: str | None = None,
    ) -> AsyncIterator[ChatSSEEvent]: ...


def _services(request: Request) -> Any:
    services = getattr(request.app.state, "services", None)
    if services is None:
        raise ServiceUnavailableError("application_not_initialized")
    return services


def get_settings(request: Request) -> Settings:
    """Return the one settings object created for this application."""
    return _services(request).settings


def get_runtime(request: Request) -> RetrievalRuntime:
    """Return the shared runtime or a typed unavailable error."""
    runtime = _services(request).runtime
    if runtime is None:
        raise ServiceUnavailableError("runtime_unavailable")
    return runtime


def get_ingestion_service(request: Request) -> IngestionPipeline:
    """Return the runtime-owned ingestion service."""
    return get_runtime(request).ingestion_pipeline


def get_document_service(request: Request) -> Any:
    """Return the lifespan-owned documents application service."""
    document_service = _services(request).document_service
    if document_service is None:
        raise ServiceUnavailableError("document_service_unavailable")
    return document_service


def get_chat_service(request: Request) -> ChatService:
    """Return the lifespan-compiled workflow without rebuilding it."""
    chat_service = _services(request).chat_service
    if chat_service is None:
        raise ServiceUnavailableError("chat_service_unavailable")
    return chat_service
