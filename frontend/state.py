"""Pure frontend chat state transitions independent of Streamlit."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sse import SSEEvent


MAX_HISTORY_MESSAGES = 12


def bounded_chat_history(
    messages: list[dict[str, Any]],
    *,
    limit: int = MAX_HISTORY_MESSAGES,
) -> list[dict[str, str]]:
    """Return the newest role/content messages accepted by the backend."""
    history: list[dict[str, str]] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role in {"user", "assistant"} and isinstance(content, str):
            normalized = content.strip()
            if normalized:
                history.append({"role": role, "content": normalized[:4000]})
    return history[-limit:]


def clear_conversation(state: dict[str, Any]) -> None:
    """Clear only browser-local messages and leave backend data untouched."""
    state["messages"] = []


@dataclass(slots=True)
class ChatAccumulator:
    """Accumulate one SSE response while retaining partial text on errors."""

    answer: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list)
    context_chunk_ids: list[str] = field(default_factory=list)
    route: dict[str, Any] | None = None
    rewrite: dict[str, Any] | None = None
    retrieval: dict[str, Any] | None = None
    done: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

    def apply(self, event: SSEEvent) -> None:
        """Apply one typed backend event without deriving sources from hits."""
        if event.event == "token":
            text = event.data.get("text")
            if isinstance(text, str):
                self.answer += text
        elif event.event == "sources":
            sources = event.data.get("sources")
            chunk_ids = event.data.get("context_chunk_ids")
            self.sources = list(sources) if isinstance(sources, list) else []
            self.context_chunk_ids = (
                [value for value in chunk_ids if isinstance(value, str)]
                if isinstance(chunk_ids, list)
                else []
            )
        elif event.event == "route":
            self.route = dict(event.data)
        elif event.event == "rewrite":
            self.rewrite = dict(event.data)
        elif event.event == "retrieval":
            self.retrieval = dict(event.data)
        elif event.event == "error":
            self.error = dict(event.data)
        elif event.event == "done":
            self.done = dict(event.data)

    def assistant_message(
        self,
        *,
        capabilities: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the serializable assistant record stored in session state."""
        return {
            "role": "assistant",
            "content": self.answer,
            "sources": list(self.sources),
            "context_chunk_ids": list(self.context_chunk_ids),
            "process": {
                "route": self.route,
                "rewrite": self.rewrite,
                "retrieval": self.retrieval,
                "done": self.done,
                "capabilities": capabilities or {},
            },
            "error": self.error,
        }
