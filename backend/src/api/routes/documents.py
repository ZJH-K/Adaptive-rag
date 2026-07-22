"""Document upload, built-in corpus loading, and statistics routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from starlette.concurrency import run_in_threadpool

from src.api.dependencies import get_document_service
from src.api.documents import DocumentService
from src.api.errors import APIError
from src.api.models import (
    APIErrorResponse,
    DocumentStatsResponse,
    DocumentUploadResponse,
    LoadDefaultRequest,
    LoadDefaultResponse,
)


router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    responses={
        400: {"model": APIErrorResponse},
        413: {"model": APIErrorResponse},
        415: {"model": APIErrorResponse},
        422: {"model": APIErrorResponse},
        502: {"model": APIErrorResponse},
        503: {"model": APIErrorResponse},
    },
)
async def upload_document(
    file: Annotated[UploadFile, File()],
    knowledge_base_id: Annotated[str | None, Form()] = None,
    chunk_strategy: Annotated[str, Form()] = "recursive",
    service: DocumentService = Depends(get_document_service),
) -> DocumentUploadResponse:
    """Validate and synchronously publish one searchable document."""
    filename = file.filename or ""
    content_type = file.content_type
    content = bytearray()
    try:
        while len(content) <= service.max_upload_bytes:
            block = await file.read(
                min(1024 * 1024, service.max_upload_bytes + 1 - len(content))
            )
            if not block:
                break
            content.extend(block)
    finally:
        await file.close()
    if len(content) > service.max_upload_bytes:
        raise APIError(
            "file_too_large",
            "The uploaded file exceeds the configured size limit.",
            status_code=413,
        )
    return await run_in_threadpool(
        service.ingest_bytes,
        filename=filename,
        content_type=content_type,
        content=bytes(content),
        knowledge_base_id=(
            service.knowledge_base_id
            if knowledge_base_id is None
            else knowledge_base_id
        ),
        chunk_strategy=chunk_strategy,
    )


@router.post(
    "/load-default",
    response_model=LoadDefaultResponse,
    responses={400: {"model": APIErrorResponse}, 404: {"model": APIErrorResponse}},
)
async def load_default_documents(
    request: LoadDefaultRequest | None = None,
    service: DocumentService = Depends(get_document_service),
) -> LoadDefaultResponse:
    """Load the configured built-in corpus with per-file results."""
    return await run_in_threadpool(service.load_default, request)


@router.get(
    "/stats",
    response_model=DocumentStatsResponse,
    responses={503: {"model": APIErrorResponse}},
)
async def document_stats(
    service: DocumentService = Depends(get_document_service),
) -> DocumentStatsResponse:
    """Return document and chunk counts from live indexes."""
    return await run_in_threadpool(service.stats)
