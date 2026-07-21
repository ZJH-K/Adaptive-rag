"""Minimal OpenAI-compatible client for DeepSeek chat completions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, Protocol

from openai import APITimeoutError, OpenAI
from pydantic import BaseModel

from src.config import Settings
from src.llm.exceptions import (
    LLMConfigurationError,
    LLMInputError,
    LLMRequestError,
    LLMResponseError,
    LLMTimeoutError,
)


class ChatMessage(BaseModel):
    """A provider-neutral text message accepted by the LLM client."""

    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionsResource(Protocol):
    """Minimal chat-completions endpoint required from an API client."""

    def create(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> Any:
        """Create one non-streaming chat completion."""
        ...


class ChatResource(Protocol):
    """Minimal chat namespace exposed by an OpenAI-compatible client."""

    completions: ChatCompletionsResource


class LLMAPIClient(Protocol):
    """Minimal protocol implemented by OpenAI and offline test fakes."""

    chat: ChatResource


class DeepSeekClient:
    """Generate assistant text through DeepSeek's OpenAI-compatible API."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        temperature: float | None = None,
        api_client: LLMAPIClient | None = None,
    ) -> None:
        """Initialize configuration without making a network request."""
        configured = settings or Settings()
        self.base_url = configured.llm_base_url if base_url is None else base_url
        self.api_key = configured.llm_api_key if api_key is None else api_key
        self.model = configured.llm_model if model is None else model
        self.timeout_seconds = (
            configured.llm_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        self.temperature = (
            configured.llm_temperature if temperature is None else temperature
        )
        self._api_client = api_client
        self._validate_configuration()

    def generate(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
    ) -> str:
        """Return non-empty assistant text for an ordered message sequence."""
        normalized_messages = self._normalize_messages(messages)
        client = self._get_api_client()
        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=normalized_messages,
                temperature=float(self.temperature),
            )
        except (APITimeoutError, TimeoutError) as exc:
            raise LLMTimeoutError("LLM request timed out") from exc
        except Exception as exc:
            detail = self._safe_request_detail(exc)
            raise LLMRequestError(f"LLM request failed ({detail})") from exc

        choices = getattr(response, "choices", None)
        if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)):
            raise LLMResponseError("LLM response has no valid choices list")
        if not choices:
            raise LLMResponseError("LLM response contains no choices")

        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if not isinstance(content, str) or not content.strip():
            raise LLMResponseError("LLM response contains no assistant text")
        return content.strip()

    def _validate_configuration(self) -> None:
        """Validate non-secret constructor configuration."""
        if not isinstance(self.base_url, str) or not self.base_url.strip():
            raise LLMConfigurationError("LLM base URL is required")
        if not isinstance(self.model, str) or not self.model.strip():
            raise LLMConfigurationError("LLM model is required")
        if (
            not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds <= 0
        ):
            raise LLMConfigurationError("LLM timeout must be greater than zero")
        if (
            not isinstance(self.temperature, (int, float))
            or isinstance(self.temperature, bool)
            or not 0 <= self.temperature <= 2
        ):
            raise LLMConfigurationError(
                "LLM temperature must be between zero and two"
            )

    def _get_api_client(self) -> LLMAPIClient:
        """Validate the API key and lazily construct the SDK client."""
        if not isinstance(self.api_key, str) or not self.api_key.strip():
            raise LLMConfigurationError("LLM API key is required")
        if self._api_client is None:
            self._api_client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=float(self.timeout_seconds),
                max_retries=0,
            )
        return self._api_client

    @staticmethod
    def _normalize_messages(
        messages: Sequence[ChatMessage | Mapping[str, object]],
    ) -> list[dict[str, str]]:
        """Validate messages and convert them into SDK-compatible dictionaries."""
        if isinstance(messages, (str, bytes)) or not isinstance(messages, Sequence):
            raise LLMInputError("Messages must be a non-empty sequence")
        if not messages:
            raise LLMInputError("Messages must be a non-empty sequence")

        normalized: list[dict[str, str]] = []
        valid_roles = {"system", "user", "assistant"}
        for index, message in enumerate(messages):
            if isinstance(message, ChatMessage):
                role = message.role
                content = message.content
            elif isinstance(message, Mapping):
                role = message.get("role")
                content = message.get("content")
            else:
                raise LLMInputError(f"Message at index {index} is invalid")
            if role not in valid_roles:
                raise LLMInputError(f"Message at index {index} has an invalid role")
            if not isinstance(content, str) or not content.strip():
                raise LLMInputError(
                    f"Message at index {index} must have non-empty content"
                )
            normalized.append({"role": str(role), "content": content.strip()})
        return normalized

    @staticmethod
    def _safe_request_detail(exc: Exception) -> str:
        """Describe an upstream failure without including its response body."""
        status_code = getattr(exc, "status_code", None)
        if isinstance(status_code, int) and not isinstance(status_code, bool):
            return f"HTTP {status_code}"
        return type(exc).__name__
