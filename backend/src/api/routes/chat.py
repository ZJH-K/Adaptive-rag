"""SSE endpoint for direct and retrieval-augmented chat."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from src.api.dependencies import ChatService, get_chat_service, get_settings
from src.api.errors import APIError
from src.api.sse import ChatStreamRequest, encode_sse_event
from src.config import Settings


router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/stream")
async def stream_chat(
    payload: ChatStreamRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
    service: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    """Validate request boundaries, then return ordered UTF-8 SSE events."""
    if payload.knowledge_base_id != settings.knowledge_base_id:
        raise APIError(
            "invalid_knowledge_base",
            "Only the configured knowledge base is supported.",
            status_code=400,
        )
    request_id = request.state.request_id

    async def event_stream():
        events = service.stream(payload, request_id=request_id)
        try:
            async for event in events:
                if await request.is_disconnected():
                    return
                yield encode_sse_event(event)
        finally:
            await events.aclose()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
