"""Pure session-state and SSE consumption tests."""

from __future__ import annotations

from sse import SSEEvent
from state import ChatAccumulator, bounded_chat_history, clear_conversation


def test_direct_event_consumption_retains_provider_deltas() -> None:
    accumulator = ChatAccumulator()
    for event in [
        SSEEvent("route", {"need_retrieval": False, "reason": "general"}),
        SSEEvent("token", {"text": "第一段"}),
        SSEEvent("token", {"text": "第二段"}),
        SSEEvent(
            "done",
            {
                "status": "success",
                "request_id": "r1",
                "trace_id": None,
                "tracing_enabled": False,
                "trace_exported": False,
            },
        ),
    ]:
        accumulator.apply(event)

    message = accumulator.assistant_message()
    assert message["content"] == "第一段第二段"
    assert message["sources"] == []
    assert message["process"]["route"]["need_retrieval"] is False
    assert message["process"]["done"]["request_id"] == "r1"


def test_rag_sources_are_copied_only_from_sources_event() -> None:
    accumulator = ChatAccumulator()
    accumulator.apply(
        SSEEvent(
            "retrieval",
            {
                "hits": [
                    {"chunk_id": "raw-only", "source": "must-not-be-source.md"}
                ]
            },
        )
    )
    accumulator.apply(
        SSEEvent(
            "sources",
            {
                "sources": [
                    {
                        "citation_id": "S1",
                        "chunk_id": "used",
                        "source": "guide.md",
                        "section": "Install",
                    }
                ],
                "context_chunk_ids": ["used"],
            },
        )
    )

    assert [source["chunk_id"] for source in accumulator.sources] == ["used"]
    assert accumulator.context_chunk_ids == ["used"]


def test_error_preserves_partial_answer() -> None:
    accumulator = ChatAccumulator()
    accumulator.apply(SSEEvent("token", {"text": "partial"}))
    accumulator.apply(
        SSEEvent(
            "error",
            {"code": "llm_timeout", "message": "Try again.", "retryable": True},
        )
    )
    accumulator.apply(SSEEvent("done", {"status": "failed"}))

    assert accumulator.answer == "partial"
    assert accumulator.error["code"] == "llm_timeout"
    assert accumulator.assistant_message()["content"] == "partial"


def test_history_is_bounded_and_strips_frontend_metadata() -> None:
    messages = [
        {
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f" message {index} ",
            "sources": [{"secret": "not-sent"}],
        }
        for index in range(15)
    ]

    history = bounded_chat_history(messages)

    assert len(history) == 12
    assert history[0]["content"] == "message 3"
    assert all(set(message) == {"role", "content"} for message in history)


def test_clear_conversation_changes_only_messages() -> None:
    state = {"messages": [{"role": "user", "content": "hello"}], "stats": 3}

    clear_conversation(state)

    assert state == {"messages": [], "stats": 3}
