"""Provider-native streaming tests for the OpenAI-compatible LLM client."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from src.config import Settings
from src.llm import DeepSeekClient, LLMResponseError, LLMTimeoutError


class FakeStream:
    """Yield configured SDK-shaped chunks and record cancellation cleanup."""

    def __init__(
        self,
        deltas: list[str | None],
        *,
        error_after: int | None = None,
    ) -> None:
        self.deltas = deltas
        self.error_after = error_after
        self.index = 0
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if self.error_after is not None and self.index == self.error_after:
            raise TimeoutError("secret upstream timeout")
        if self.index >= len(self.deltas):
            raise StopIteration
        content = self.deltas[self.index]
        self.index += 1
        return SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=content))]
        )

    def close(self) -> None:
        self.closed = True


class FakeCompletions:
    def __init__(self, stream: FakeStream, *, error: Exception | None = None) -> None:
        self.stream = stream
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> FakeStream:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.stream


class FakeAsyncStream:
    """Async SDK-shaped stream with observable close state."""

    def __init__(self, deltas: list[str | None]) -> None:
        self.deltas = deltas
        self.index = 0
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index >= len(self.deltas):
            raise StopAsyncIteration
        content = self.deltas[self.index]
        self.index += 1
        return SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=content))]
        )

    async def close(self) -> None:
        self.closed = True


class FakeAsyncCompletions:
    def __init__(self, stream: FakeAsyncStream) -> None:
        self.stream = stream
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> FakeAsyncStream:
        self.calls.append(kwargs)
        return self.stream


def _client(completions: FakeCompletions) -> DeepSeekClient:
    api_client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    return DeepSeekClient(
        Settings(_env_file=None, llm_api_key="offline-key"),
        api_client=api_client,
    )


def test_stream_generate_forwards_stream_true_and_preserves_provider_deltas() -> None:
    stream = FakeStream(["你", "好", None, "！"])
    completions = FakeCompletions(stream)

    deltas = list(
        _client(completions).stream_generate(
            [{"role": "user", "content": "hello"}]
        )
    )

    assert deltas == ["你", "好", "！"]
    assert "".join(deltas) == "你好！"
    assert completions.calls[0]["stream"] is True
    assert "response_format" not in completions.calls[0]
    assert stream.closed is True


def test_stream_generate_rejects_a_stream_without_text() -> None:
    stream = FakeStream([None, ""])

    with pytest.raises(LLMResponseError, match="no assistant text"):
        list(
            _client(FakeCompletions(stream)).stream_generate(
                [{"role": "user", "content": "hello"}]
            )
        )

    assert stream.closed is True


def test_stream_create_timeout_is_typed() -> None:
    stream = FakeStream([])
    completions = FakeCompletions(stream, error=TimeoutError("secret"))

    with pytest.raises(LLMTimeoutError, match="timed out"):
        next(
            _client(completions).stream_generate(
                [{"role": "user", "content": "hello"}]
            )
        )


def test_midstream_timeout_is_typed_and_closes_provider() -> None:
    stream = FakeStream(["first", "second"], error_after=1)
    iterator = _client(FakeCompletions(stream)).stream_generate(
        [{"role": "user", "content": "hello"}]
    )

    assert next(iterator) == "first"
    with pytest.raises(LLMTimeoutError, match="timed out"):
        next(iterator)
    assert stream.closed is True


def test_closing_delta_iterator_closes_upstream_stream() -> None:
    stream = FakeStream(["first", "never-consumed"])
    iterator = _client(FakeCompletions(stream)).stream_generate(
        [{"role": "user", "content": "hello"}]
    )

    assert next(iterator) == "first"
    iterator.close()

    assert stream.closed is True
    assert stream.index == 1


def test_async_stream_preserves_deltas_and_closes_upstream() -> None:
    stream = FakeAsyncStream(["异", None, "步"])
    completions = FakeAsyncCompletions(stream)
    api_client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    client = DeepSeekClient(
        Settings(_env_file=None, llm_api_key="offline-key"),
        async_api_client=api_client,
    )

    async def collect() -> list[str]:
        return [
            token
            async for token in client.astream_generate(
                [{"role": "user", "content": "hello"}]
            )
        ]

    assert asyncio.run(collect()) == ["异", "步"]
    assert completions.calls[0]["stream"] is True
    assert stream.closed is True


def test_closing_async_delta_iterator_closes_upstream_immediately() -> None:
    stream = FakeAsyncStream(["first", "never-consumed"])
    api_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeAsyncCompletions(stream))
    )
    client = DeepSeekClient(
        Settings(_env_file=None, llm_api_key="offline-key"),
        async_api_client=api_client,
    )

    async def consume_one() -> None:
        iterator = client.astream_generate(
            [{"role": "user", "content": "hello"}]
        )
        assert await anext(iterator) == "first"
        await iterator.aclose()

    asyncio.run(consume_one())
    assert stream.closed is True
    assert stream.index == 1
