"""Unified HTTP and streaming client for the Adaptive RAG backend."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import httpx

from sse import SSEEvent, SSEParseError, SSEParser


class APIClientError(RuntimeError):
    """Safe frontend-facing backend or transport error."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.status_code = status_code
        self.request_id = request_id


class AdaptiveRAGAPIClient:
    """Call JSON endpoints and incrementally consume chat SSE."""

    def __init__(
        self,
        backend_url: str,
        *,
        client: httpx.Client | None = None,
        connect_timeout: float = 3.0,
        read_timeout: float = 120.0,
    ) -> None:
        normalized = backend_url.strip().rstrip("/")
        if not normalized:
            raise ValueError("backend_url must not be blank")
        self.backend_url = normalized
        self._owns_client = client is None
        self._timeout = httpx.Timeout(
            connect=connect_timeout,
            read=read_timeout,
            write=30.0,
            pool=5.0,
        )
        self._client = client or httpx.Client(timeout=self._timeout)

    @classmethod
    def from_env(cls) -> "AdaptiveRAGAPIClient":
        """Build a client from non-secret frontend environment settings."""
        return cls(os.getenv("BACKEND_URL", "http://127.0.0.1:8000"))

    def health(self) -> dict[str, Any]:
        """Return backend health and optional capability readiness."""
        return self._json_request("GET", "/api/health")

    def stats(self) -> dict[str, Any]:
        """Return live document and chunk statistics."""
        return self._json_request("GET", "/api/documents/stats")

    def upload_document(
        self,
        *,
        filename: str,
        content: bytes,
        content_type: str,
        knowledge_base_id: str,
        chunk_strategy: str,
    ) -> dict[str, Any]:
        """Upload one bounded PDF or Markdown document."""
        return self._json_request(
            "POST",
            "/api/documents/upload",
            files={"file": (filename, content, content_type)},
            data={
                "knowledge_base_id": knowledge_base_id,
                "chunk_strategy": chunk_strategy,
            },
        )

    def load_default(
        self,
        *,
        knowledge_base_id: str,
        chunk_strategy: str = "auto",
    ) -> dict[str, Any]:
        """Load the backend-configured built-in knowledge corpus."""
        return self._json_request(
            "POST",
            "/api/documents/load-default",
            json={
                "knowledge_base_id": knowledge_base_id,
                "chunk_strategy": chunk_strategy,
            },
        )

    def stream_chat(
        self,
        *,
        question: str,
        knowledge_base_id: str,
        chat_history: list[dict[str, str]],
    ) -> Iterator[SSEEvent]:
        """Yield SSE events as network chunks arrive and close on interruption."""
        payload = {
            "question": question,
            "knowledge_base_id": knowledge_base_id,
            "chat_history": chat_history,
        }
        try:
            with self._client.stream(
                "POST",
                f"{self.backend_url}/api/chat/stream",
                json=payload,
                headers={"Accept": "text/event-stream"},
                timeout=self._timeout,
            ) as response:
                if response.status_code >= 400:
                    raise self._response_error(response)
                content_type = response.headers.get("content-type", "")
                if not content_type.startswith("text/event-stream"):
                    raise APIClientError(
                        "invalid_stream_response",
                        "Backend returned a non-SSE chat response.",
                        status_code=response.status_code,
                    )
                parser = SSEParser()
                for chunk in response.iter_bytes():
                    for event in parser.feed(chunk):
                        yield event
                yield from parser.close()
        except APIClientError:
            raise
        except SSEParseError as exc:
            raise APIClientError(exc.code, exc.safe_message) from exc
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise APIClientError(
                "backend_unavailable",
                "Backend is unreachable or timed out.",
            ) from exc
        except httpx.HTTPError as exc:
            raise APIClientError(
                "backend_request_failed",
                "Backend request failed.",
            ) from exc

    def close(self) -> None:
        """Close an internally-created HTTP client."""
        if self._owns_client:
            self._client.close()

    def _json_request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._client.request(
                method,
                f"{self.backend_url}{path}",
                timeout=self._timeout,
                **kwargs,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise APIClientError(
                "backend_unavailable",
                "Backend is unreachable or timed out.",
            ) from exc
        except httpx.HTTPError as exc:
            raise APIClientError(
                "backend_request_failed",
                "Backend request failed.",
            ) from exc
        if response.status_code >= 400:
            raise self._response_error(response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise APIClientError(
                "invalid_backend_response",
                "Backend returned invalid JSON.",
                status_code=response.status_code,
            ) from exc
        if not isinstance(payload, dict):
            raise APIClientError(
                "invalid_backend_response",
                "Backend returned an invalid response object.",
                status_code=response.status_code,
            )
        return payload

    @staticmethod
    def _response_error(response: httpx.Response) -> APIClientError:
        code = "backend_error"
        message = "Backend could not complete the request."
        request_id = response.headers.get("X-Request-ID")
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                if isinstance(error.get("code"), str):
                    code = error["code"]
                if isinstance(error.get("message"), str):
                    message = error["message"]
                if isinstance(error.get("request_id"), str):
                    request_id = error["request_id"]
        return APIClientError(
            code,
            message,
            status_code=response.status_code,
            request_id=request_id,
        )
