"""SSE endpoint for direct and retrieval-augmented chat."""

from __future__ import annotations

import asyncio

import anyio
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
    client_request_id = request.state.client_request_id

    async def event_stream():
        events = service.stream(
            payload,
            request_id=request_id,
            client_request_id=client_request_id,
        )
        disconnect = asyncio.create_task(_wait_for_disconnect(request))
        next_event: asyncio.Task | None = None
        try:
            while True:
                next_event = asyncio.create_task(anext(events))
                completed, _ = await asyncio.wait(
                    {next_event, disconnect},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if disconnect in completed:
                    next_event.cancel()
                    await asyncio.gather(next_event, return_exceptions=True)
                    return
                try:
                    event = next_event.result()
                except StopAsyncIteration:
                    return
                yield encode_sse_event(event)
        finally:
            # Starlette may cancel this iterator through an AnyIO task group.
            # A shielded cleanup scope lets cancellation reach the graph first,
            # then waits for provider/trace finalizers before returning.
            with anyio.CancelScope(shield=True):
                disconnect.cancel()
                await asyncio.gather(disconnect, return_exceptions=True)
                if next_event is not None and not next_event.done():
                    next_event.cancel()
                    await asyncio.gather(next_event, return_exceptions=True)
                await events.aclose()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _wait_for_disconnect(request: Request) -> None:
    """Wait for the ASGI disconnect message without polling or heartbeats."""
    if await request.is_disconnected():
        return
    while True:
        message = await request.receive()
        if message["type"] == "http.disconnect":
            return
