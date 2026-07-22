"""Incremental UTF-8 Server-Sent Event parser for the chat stream."""

from __future__ import annotations

import codecs
import json
from dataclasses import dataclass
from typing import Any


class SSEParseError(ValueError):
    """A safe, diagnosable error in an SSE byte stream."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message


@dataclass(frozen=True, slots=True)
class SSEEvent:
    """One decoded SSE event with an object JSON payload."""

    event: str
    data: dict[str, Any]


class SSEParser:
    """Parse arbitrarily chunked UTF-8 SSE bytes without full buffering."""

    def __init__(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")("strict")
        self._text = ""
        self._event_name: str | None = None
        self._data_lines: list[str] = []
        self._closed = False

    def feed(self, chunk: bytes) -> list[SSEEvent]:
        """Consume one network byte chunk and return completed events."""
        if self._closed:
            raise SSEParseError("parser_closed", "The SSE parser is already closed.")
        if not isinstance(chunk, bytes):
            raise SSEParseError("invalid_chunk", "SSE chunks must be bytes.")
        try:
            self._text += self._decoder.decode(chunk, final=False)
        except UnicodeDecodeError as exc:
            raise SSEParseError(
                "invalid_utf8", "The SSE stream contains invalid UTF-8."
            ) from exc
        return self._drain_lines(final=False)

    def close(self) -> list[SSEEvent]:
        """Finalize decoding and dispatch one final complete event if present."""
        if self._closed:
            return []
        self._closed = True
        try:
            self._text += self._decoder.decode(b"", final=True)
        except UnicodeDecodeError as exc:
            raise SSEParseError(
                "invalid_utf8", "The SSE stream ended within a UTF-8 character."
            ) from exc
        events = self._drain_lines(final=True)
        if self._data_lines:
            event = self._dispatch()
            if event is not None:
                events.append(event)
        return events

    def _drain_lines(self, *, final: bool) -> list[SSEEvent]:
        events: list[SSEEvent] = []
        while True:
            line = self._pop_line(final=final)
            if line is None:
                break
            event = self._process_line(line)
            if event is not None:
                events.append(event)
        return events

    def _pop_line(self, *, final: bool) -> str | None:
        for index, character in enumerate(self._text):
            if character == "\n":
                line = self._text[:index]
                self._text = self._text[index + 1 :]
                return line
            if character == "\r":
                if index + 1 == len(self._text) and not final:
                    return None
                consumed = 2 if self._text[index + 1 : index + 2] == "\n" else 1
                line = self._text[:index]
                self._text = self._text[index + consumed :]
                return line
        if final and self._text:
            line = self._text
            self._text = ""
            return line
        return None

    def _process_line(self, line: str) -> SSEEvent | None:
        if line == "":
            return self._dispatch()
        if line.startswith(":"):
            return None
        field, separator, value = line.partition(":")
        if separator and value.startswith(" "):
            value = value[1:]
        if field == "event":
            self._event_name = value or "message"
        elif field == "data":
            self._data_lines.append(value)
        return None

    def _dispatch(self) -> SSEEvent | None:
        if not self._data_lines:
            self._event_name = None
            return None
        raw_data = "\n".join(self._data_lines)
        event_name = self._event_name or "message"
        self._event_name = None
        self._data_lines = []
        try:
            payload = json.loads(raw_data)
        except json.JSONDecodeError as exc:
            raise SSEParseError(
                "invalid_json",
                f"SSE event '{event_name}' contains invalid JSON.",
            ) from exc
        if not isinstance(payload, dict):
            raise SSEParseError(
                "invalid_payload",
                f"SSE event '{event_name}' must contain a JSON object.",
            )
        return SSEEvent(event=event_name, data=payload)
