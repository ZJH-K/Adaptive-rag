"""Non-invasive readiness endpoint."""

from fastapi import APIRouter, Request, Response, status

from src.api.models import (
    BM25Health,
    ChromaHealth,
    HealthResponse,
    LivenessResponse,
    ModelHealth,
    RerankerHealth,
    TracingHealth,
)
from src.observability.tracing import TracingStatus
from src.rag.retrieval import get_reranker_status


router = APIRouter(prefix="/api", tags=["health"])


@router.get("/live", response_model=LivenessResponse)
def live() -> LivenessResponse:
    """Report process liveness without requiring providers or runtime readiness."""
    return LivenessResponse()


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
def health(request: Request, response: Response) -> HealthResponse:
    """Return local readiness without calling paid external providers."""
    services = getattr(request.app.state, "services", None)
    request_id = request.state.request_id
    if services is None:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return _unavailable_health(request_id)

    settings = services.settings
    llm = ModelHealth(
        configured=bool(settings.llm_api_key and settings.llm_model),
        model=settings.llm_model,
    )
    embedding = ModelHealth(
        configured=bool(settings.embedding_api_key and settings.embedding_model),
        model=settings.embedding_model,
    )

    runtime = services.runtime
    if (
        runtime is None
        or services.startup_error_code is not None
        or not services.accepting_operations
    ):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return _unavailable_health(
            request_id,
            llm=llm,
            embedding=embedding,
            tracing=_tracing_health(services.observer.get_status()),
        )

    try:
        chroma = ChromaHealth(status="ready", chunk_count=runtime.vector_store.count())
    except Exception:
        chroma = ChromaHealth(
            status="unavailable",
            error_code="chroma_unavailable",
        )

    try:
        index = runtime.get_index_status()
        bm25_status = (
            "rebuilding" if index.is_rebuilding
            else "degraded" if index.needs_rebuild
            else "ready"
        )
        bm25 = BM25Health(
            status=bm25_status,
            generation=index.generation,
            chunk_count=index.chunk_count,
            needs_rebuild=index.needs_rebuild,
            last_successful_rebuild_at=(
                index.last_successful_rebuild_at.isoformat()
                if index.last_successful_rebuild_at is not None else None
            ),
            last_error_code=index.last_failure_code,
        )
    except Exception:
        bm25 = BM25Health(
            status="unavailable",
            needs_rebuild=True,
            last_error_code="bm25_status_unavailable",
        )
    reranker_state = get_reranker_status(runtime.reranker)
    reranker = RerankerHealth(**reranker_state.model_dump())
    tracing = _tracing_health(services.observer.get_status())

    core_unavailable = (
        chroma.status == "unavailable"
        or not llm.configured
        or not embedding.configured
    )
    optional_degraded = (
        bm25.status != "ready"
        or (reranker.enabled and not reranker.available)
        or (tracing.enabled and not tracing.available)
    )
    overall = (
        "unavailable" if core_unavailable
        else "degraded" if optional_degraded
        else "ok"
    )
    if core_unavailable:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status=overall,
        request_id=request_id,
        chroma=chroma,
        bm25=bm25,
        llm=llm,
        embedding=embedding,
        reranker=reranker,
        tracing=tracing,
    )


def _tracing_health(state: TracingStatus) -> TracingHealth:
    return TracingHealth(
        enabled=state.tracing_enabled,
        configured=state.tracing_configured,
        available=state.tracing_available,
        last_error_code=state.trace_error_code,
    )


def _unavailable_health(
    request_id: str,
    *,
    llm: ModelHealth | None = None,
    embedding: ModelHealth | None = None,
    tracing: TracingHealth | None = None,
) -> HealthResponse:
    return HealthResponse(
        status="unavailable",
        request_id=request_id,
        chroma=ChromaHealth(
            status="unavailable",
            error_code="runtime_unavailable",
        ),
        bm25=BM25Health(status="unavailable"),
        llm=llm or ModelHealth(configured=False, model="unavailable"),
        embedding=embedding or ModelHealth(configured=False, model="unavailable"),
        reranker=RerankerHealth(
            enabled=False,
            configured=False,
            available=False,
            model="unavailable",
        ),
        tracing=tracing or TracingHealth(
            enabled=False,
            configured=False,
            available=False,
        ),
    )
