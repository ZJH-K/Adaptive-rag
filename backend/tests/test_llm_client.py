"""Offline unit tests for the OpenAI-compatible DeepSeek client."""

from types import SimpleNamespace
from typing import Any

import pytest
from openai.types.chat import ChatCompletion

from src.agent.state import RewriteResult, RouteDecision
from src.config import Settings
from src.llm import (
    ChatMessage,
    DeepSeekClient,
    LLMConfigurationError,
    LLMInputError,
    LLMRequestError,
    LLMResponseError,
    LLMTimeoutError,
    parse_structured_output,
)


class FakeCompletionsResource:
    def __init__(
        self,
        *,
        content: str = "assistant response",
        error: Exception | None = None,
        response: Any | None = None,
    ) -> None:
        self.content = content
        self.error = error
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def create(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        response_format: dict[str, str] | None = None,
    ) -> Any:
        call: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format is not None:
            call["response_format"] = response_format
        self.calls.append(call)
        if self.error is not None:
            raise self.error
        if self.response is not None:
            return self.response
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self.content)
                )
            ]
        )


class FakeAPIClient:
    def __init__(self, completions: FakeCompletionsResource | None = None) -> None:
        self.chat = SimpleNamespace(
            completions=completions or FakeCompletionsResource()
        )


def _client(
    fake: FakeAPIClient | None = None,
    **overrides: Any,
) -> DeepSeekClient:
    arguments: dict[str, Any] = {
        "settings": Settings(_env_file=None),
        "api_key": "offline-test-key",
        "api_client": fake or FakeAPIClient(),
    }
    arguments.update(overrides)
    return DeepSeekClient(**arguments)


def test_generate_extracts_assistant_text_and_normalizes_messages() -> None:
    fake = FakeAPIClient()

    answer = _client(fake).generate(
        [
            ChatMessage(role="system", content=" Be concise. "),
            {"role": "user", "content": " Reply with ok. "},
        ]
    )

    assert answer == "assistant response"
    assert fake.chat.completions.calls == [
        {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "Be concise."},
                {"role": "user", "content": "Reply with ok."},
            ],
            "temperature": 0.1,
        }
    ]


def test_generate_structured_enables_json_mode_and_validates_model() -> None:
    fake = FakeAPIClient(
        FakeCompletionsResource(
            content='{"need_retrieval": true, "reason": "document"}'
        )
    )

    result = _client(fake).generate_structured(
        [{"role": "user", "content": "Return JSON."}],
        RouteDecision,
    )

    assert result == RouteDecision(need_retrieval=True, reason="document")
    assert fake.chat.completions.calls[0]["response_format"] == {
        "type": "json_object"
    }


@pytest.mark.parametrize(
    "content",
    [
        '```json\n{"rewritten_query": "standalone"}\n```',
        'Result: {"rewritten_query": "standalone"}.',
    ],
)
def test_structured_fallback_parses_wrapped_json_without_json_mode(
    content: str,
) -> None:
    fake = FakeAPIClient(FakeCompletionsResource(content=content))

    result = _client(fake, json_mode_enabled=False).generate_structured(
        [{"role": "user", "content": "Return JSON."}],
        RewriteResult,
    )

    assert result.rewritten_query == "standalone"
    assert "response_format" not in fake.chat.completions.calls[0]


def test_generate_structured_accepts_real_openai_sdk_response_shape() -> None:
    response = ChatCompletion.model_validate(
        {
            "id": "chatcmpl-offline",
            "choices": [
                {
                    "finish_reason": "stop",
                    "index": 0,
                    "message": {
                        "content": '{"rewritten_query": "SDK-shaped"}',
                        "role": "assistant",
                    },
                }
            ],
            "created": 0,
            "model": "deepseek-chat",
            "object": "chat.completion",
        }
    )
    fake = FakeAPIClient(FakeCompletionsResource(response=response))

    result = _client(fake).generate_structured(
        [{"role": "user", "content": "Return JSON."}],
        RewriteResult,
    )

    assert result.rewritten_query == "SDK-shaped"


@pytest.mark.parametrize(
    "content",
    [
        "",
        "not json",
        "{}",
        '{"need_retrieval": "yes", "reason": "wrong type"}',
        '{"need_retrieval": true, "reason": "ok", "extra": 1}',
    ],
)
def test_structured_output_rejects_empty_invalid_or_nonconforming_content(
    content: str,
) -> None:
    if content:
        with pytest.raises(LLMResponseError):
            parse_structured_output(content, RouteDecision)
    else:
        with pytest.raises(LLMResponseError, match="empty"):
            parse_structured_output(content, RouteDecision)


def test_missing_api_key_fails_before_api_call() -> None:
    fake = FakeAPIClient()
    client = DeepSeekClient(
        settings=Settings(_env_file=None),
        api_client=fake,
    )

    with pytest.raises(LLMConfigurationError, match="API key"):
        client.generate([{"role": "user", "content": "hello"}])

    assert fake.chat.completions.calls == []


def test_timeout_is_mapped_to_project_exception() -> None:
    fake = FakeAPIClient(
        FakeCompletionsResource(error=TimeoutError("upstream timeout"))
    )

    with pytest.raises(LLMTimeoutError, match="timed out"):
        _client(fake).generate([{"role": "user", "content": "hello"}])


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(choices=[]),
        SimpleNamespace(choices=None),
        SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=None))]
        ),
        SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="   "))]
        ),
    ],
)
def test_empty_or_invalid_response_is_rejected(response: Any) -> None:
    fake = FakeAPIClient(FakeCompletionsResource(response=response))

    with pytest.raises(LLMResponseError):
        _client(fake).generate([{"role": "user", "content": "hello"}])


def test_custom_sdk_configuration_and_model_are_forwarded(monkeypatch) -> None:
    captured: dict[str, Any] = {}
    fake = FakeAPIClient()

    def fake_openai(**kwargs: Any) -> FakeAPIClient:
        captured.update(kwargs)
        return fake

    monkeypatch.setattr("src.llm.client.OpenAI", fake_openai)
    client = DeepSeekClient(
        settings=Settings(_env_file=None),
        base_url="https://custom.example/v1",
        api_key="custom-test-key",
        model="custom-chat-model",
        timeout_seconds=12.5,
        temperature=0.3,
    )

    client.generate([{"role": "user", "content": "hello"}])

    assert captured["base_url"] == "https://custom.example/v1"
    assert captured["timeout"] == 12.5
    assert captured["max_retries"] == 0
    assert fake.chat.completions.calls[0]["model"] == "custom-chat-model"
    assert fake.chat.completions.calls[0]["temperature"] == 0.3


def test_upstream_error_is_wrapped_without_exposing_api_key() -> None:
    secret = "secret-value-that-must-not-leak"
    fake = FakeAPIClient(
        FakeCompletionsResource(
            error=RuntimeError(f"upstream rejected {secret}")
        )
    )

    with pytest.raises(LLMRequestError) as error:
        _client(fake, api_key=secret).generate(
            [{"role": "user", "content": "hello"}]
        )

    assert "RuntimeError" in str(error.value)
    assert secret not in str(error.value)
    assert secret not in repr(error.value)


def test_upstream_status_code_is_retained_without_response_body() -> None:
    class UpstreamStatusError(Exception):
        status_code = 429

    fake = FakeAPIClient(
        FakeCompletionsResource(error=UpstreamStatusError("sensitive body"))
    )

    with pytest.raises(LLMRequestError, match="HTTP 429") as error:
        _client(fake).generate([{"role": "user", "content": "hello"}])

    assert "sensitive body" not in str(error.value)


@pytest.mark.parametrize(
    "messages",
    [
        [],
        [{"role": "user", "content": " "}],
        [{"role": "tool", "content": "result"}],
        [object()],
    ],
)
def test_invalid_messages_fail_without_api_call(messages: list[object]) -> None:
    fake = FakeAPIClient()

    with pytest.raises(LLMInputError):
        _client(fake).generate(messages)  # type: ignore[arg-type]

    assert fake.chat.completions.calls == []


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"base_url": " "}, "base URL"),
        ({"model": ""}, "model"),
        ({"timeout_seconds": 0}, "timeout"),
        ({"temperature": -0.1}, "temperature"),
        ({"temperature": 2.1}, "temperature"),
    ],
)
def test_invalid_configuration_is_rejected(
    overrides: dict[str, Any], message: str
) -> None:
    with pytest.raises(LLMConfigurationError, match=message):
        _client(**overrides)
