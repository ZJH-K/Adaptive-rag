"""Byte-boundary tests for the incremental SSE parser."""

from __future__ import annotations

import pytest

from sse import SSEParseError, SSEParser


def _parse_chunks(chunks: list[bytes]):
    parser = SSEParser()
    events = []
    for chunk in chunks:
        events.extend(parser.feed(chunk))
    events.extend(parser.close())
    return events


def test_parser_handles_every_utf8_byte_boundary() -> None:
    payload = (
        'event: token\r\ndata: {"text":"中文增量"}\r\n\r\n'
        'event: done\ndata: {"status":"success"}\n\n'
    ).encode("utf-8")

    events = _parse_chunks([bytes([byte]) for byte in payload])

    assert [event.event for event in events] == ["token", "done"]
    assert events[0].data == {"text": "中文增量"}
    assert events[1].data == {"status": "success"}


def test_parser_handles_multiple_events_in_one_chunk_and_comments() -> None:
    chunk = (
        b": keepalive\n\n"
        b"event: route\ndata: {\"need_retrieval\":false}\n\n"
        b"event: token\ndata: {\"text\":\"ok\"}\n\n"
    )

    events = _parse_chunks([chunk])

    assert [event.event for event in events] == ["route", "token"]


def test_parser_joins_multiple_data_lines() -> None:
    events = _parse_chunks(
        [b'event: custom\ndata: {"value":\ndata: 1}\n\n']
    )

    assert events[0].data == {"value": 1}


def test_parser_dispatches_final_event_without_blank_line() -> None:
    events = _parse_chunks([b'event: done\ndata: {"status":"success"}'])

    assert events[0].event == "done"


def test_invalid_json_is_diagnostic() -> None:
    parser = SSEParser()

    with pytest.raises(SSEParseError) as raised:
        parser.feed(b"event: token\ndata: not-json\n\n")

    assert raised.value.code == "invalid_json"


def test_incomplete_utf8_at_end_is_diagnostic() -> None:
    parser = SSEParser()
    parser.feed(b"event: token\ndata: \xe4")

    with pytest.raises(SSEParseError) as raised:
        parser.close()

    assert raised.value.code == "invalid_utf8"
