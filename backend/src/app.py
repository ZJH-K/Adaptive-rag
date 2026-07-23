"""FastAPI application factory and single shared service lifecycle."""

from __future__ import annotations

import logging
import re
import inspect
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from src.agent.graph import build_graph
from src.api.chat import ChatStreamingService
from src.api.documents import DocumentService
from src.api.errors import APIError
from src.api.models import APIErrorDetail, APIErrorResponse
from src.api.routes.documents import router as documents_router
from src.api.routes.chat import router as chat_router
from src.api.routes.health import router as health_router
from src.config import Settings
from src.llm.client import DeepSeekClient
from src.observability.langfuse import build_trace_observer
from src.observability.tracing import TraceObserver
from src.rag.embeddings.client import EmbeddingClient
from src.rag.runtime import RetrievalRuntime, build_retrieval_runtime


logger = logging.getLogger(__name__)
CLIENT_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
RuntimeFactory = Callable[[Settings], RetrievalRuntime]
ObserverFactory = Callable[[Settings], TraceObserver]
LLMFactory = Callable[[Settings], Any]


@dataclass(slots=True)
class ApplicationServices:
    """The one lifespan-owned application dependency container."""

    settings: Settings
    observer: TraceObserver
    runtime: RetrievalRuntime | None = None
    llm_client: DeepSeekClient | None = None
    chat_service: Any = None
    workflow: Any = None
    document_service: DocumentService | None = None
    startup_error_code: str | None = None
    accepting_operations: bool = False


def _default_runtime_factory(settings: Settings) -> RetrievalRuntime:
    embedding_client = EmbeddingClient(settings)
    return build_retrieval_runtime(embedding_client, settings=settings)


def create_app(
    settings: Settings | None = None,
    *,
    runtime_factory: RuntimeFactory = _default_runtime_factory,
    observer_factory: ObserverFactory = build_trace_observer,
    llm_factory: LLMFactory = DeepSeekClient,
) -> FastAPI:
    """Create the application without connecting to external services."""
    configured = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        observer = observer_factory(configured)
        services = ApplicationServices(settings=configured, observer=observer)
        app.state.services = services
        observer.startup()
        try:
            runtime = runtime_factory(configured)
            llm_client = llm_factory(configured)
            services.runtime = runtime
            services.llm_client = llm_client
            services.document_service = DocumentService(configured, runtime)
            services.workflow = build_graph(
                llm_client,
                runtime.retriever,
                observer=observer,
            )
            services.chat_service = ChatStreamingService(
                services.workflow,
                observer,
            )
            services.accepting_operations = True
        except Exception:
            services.startup_error_code = "runtime_startup_failed"
            logger.exception("Application runtime startup failed")

        try:
            yield
        finally:
            services.accepting_operations = False
            if services.llm_client is not None:
                await _safe_async_cleanup(
                    getattr(services.llm_client, "aclose", None),
                    "Async LLM client close failed",
                )
                await _safe_sync_cleanup(
                    getattr(services.llm_client, "close", None),
                    "Synchronous LLM client close failed",
                )
            await _safe_sync_cleanup(
                observer.flush,
                "Observability flush failed during shutdown",
            )
            await _safe_sync_cleanup(
                observer.shutdown,
                "Observability shutdown failed",
            )
            if services.runtime is not None:
                await _safe_sync_cleanup(
                    services.runtime.close,
                    "Retrieval runtime close failed",
                )

    app = FastAPI(
        title="Adaptive RAG API",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next: Callable[..., Any]):
        request.state.request_id = uuid4().hex
        client_request_id = request.headers.get("X-Request-ID")
        request.state.client_request_id = client_request_id
        if client_request_id is not None and CLIENT_REQUEST_ID_PATTERN.fullmatch(
            client_request_id
        ) is None:
            return _error_response(
                request,
                400,
                "invalid_client_request_id",
                "X-Request-ID contains unsupported characters or length.",
            )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        if client_request_id is not None:
            response.headers["X-Client-Request-ID"] = client_request_id
        return response

    @app.exception_handler(APIError)
    async def unavailable_handler(
        request: Request,
        exc: APIError,
    ) -> JSONResponse:
        return _error_response(
            request,
            exc.status_code,
            exc.code,
            exc.safe_message,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(
            request,
            422,
            "invalid_request",
            "The request payload is invalid.",
        )

    @app.exception_handler(Exception)
    async def unknown_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled API error", exc_info=exc)
        return _error_response(
            request,
            500,
            "internal_error",
            "The server could not complete the request.",
        )

    app.include_router(health_router)
    app.include_router(documents_router)
    app.include_router(chat_router)
    return app


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", uuid4().hex)
    body = APIErrorResponse(
        error=APIErrorDetail(
            code=code,
            message=message,
            request_id=request_id,
        )
    )
    headers = {"X-Request-ID": request_id}
    client_request_id = getattr(request.state, "client_request_id", None)
    if client_request_id is not None and CLIENT_REQUEST_ID_PATTERN.fullmatch(
        client_request_id
    ) is not None:
        headers["X-Client-Request-ID"] = client_request_id
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(),
        headers=headers,
    )


async def _safe_sync_cleanup(
    cleanup: Callable[[], Any] | None,
    message: str,
) -> None:
    """Run one blocking cleanup without preventing later resources closing."""
    if not callable(cleanup):
        return
    try:
        await run_in_threadpool(cleanup)
    except Exception:
        logger.exception(message)


async def _safe_async_cleanup(
    cleanup: Callable[[], Any] | None,
    message: str,
) -> None:
    """Await one optional async cleanup and contain only cleanup failures."""
    if not callable(cleanup):
        return
    try:
        result = cleanup()
        if inspect.isawaitable(result):
            await result
    except Exception:
        logger.exception(message)
