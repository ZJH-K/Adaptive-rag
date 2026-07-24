"""Minimal OpenAI-compatible client for DeepSeek chat completions."""

from __future__ import annotations

import json
import inspect
from collections.abc import Iterator, Mapping, Sequence
from typing import Any, AsyncIterator, Literal, Protocol, TypeVar

from openai import APITimeoutError, AsyncOpenAI, OpenAI
from pydantic import BaseModel, ValidationError

from src.config import Settings
from src.llm.exceptions import (
    LLMConfigurationError,
    LLMInputError,
    LLMRequestError,
    LLMResponseError,
    LLMTimeoutError,
)


StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)
JSON_OBJECT_RESPONSE_FORMAT = {"type": "json_object"}


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
        response_format: dict[str, str] | None = None,
        stream: bool = False,
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
        json_mode_enabled: bool | None = None,
        api_client: LLMAPIClient | None = None,
        async_api_client: Any | None = None,
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
        self.json_mode_enabled = (
            configured.llm_json_mode_enabled
            if json_mode_enabled is None
            else json_mode_enabled
        )
        self._api_client = api_client
        self._async_api_client = async_api_client
        self._validate_configuration()

    def generate(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
    ) -> str:
        """Return non-empty assistant text for an ordered message sequence."""
        return self._request_text(messages)

    def close(self) -> None:
        """Idempotently close the lazily-created synchronous SDK client."""
        client = self._api_client
        self._api_client = None
        if client is None:
            return
        close = getattr(client, "close", None)
        if callable(close):
            close()

    async def aclose(self) -> None:
        """Idempotently close the lazily-created asynchronous SDK client."""
        client = self._async_api_client
        self._async_api_client = None
        if client is None:
            return
        close = getattr(client, "aclose", None)
        if not callable(close):
            close = getattr(client, "close", None)
        if callable(close):
            result = close()
            if inspect.isawaitable(result):
                await result

    def generate_structured(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
        response_model: type[StructuredOutputT],
    ) -> StructuredOutputT:
        """Generate and strictly validate one structured JSON object."""
        response_format = (
            JSON_OBJECT_RESPONSE_FORMAT if self.json_mode_enabled else None
        )
        text = self._request_text(messages, response_format=response_format)
        return parse_structured_output(text, response_model)

    def stream_generate(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
    ) -> Iterator[str]:
        """Yield provider-supplied text deltas from a real streaming request."""
        normalized_messages = self._normalize_messages(messages)
        client = self._get_api_client()
        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=normalized_messages,
                temperature=float(self.temperature),
                stream=True,
            )
        except (APITimeoutError, TimeoutError) as exc:
            raise LLMTimeoutError("LLM streaming request timed out") from exc
        except Exception as exc:
            detail = self._safe_request_detail(exc)
            raise LLMRequestError(
                f"LLM streaming request failed ({detail})"
            ) from exc

        emitted = False
        close = getattr(response, "close", None)
        try:
            for chunk in response:
                content = self._extract_stream_delta(chunk)
                if content is None:
                    continue
                emitted = True
                yield content
        except (LLMResponseError, LLMTimeoutError, LLMRequestError):
            raise
        except (APITimeoutError, TimeoutError) as exc:
            raise LLMTimeoutError("LLM stream timed out") from exc
        except Exception as exc:
            detail = self._safe_request_detail(exc)
            raise LLMRequestError(f"LLM stream failed ({detail})") from exc
        finally:
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        if not emitted:
            raise LLMResponseError("LLM stream contains no assistant text")

    async def astream_generate(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
    ) -> AsyncIterator[str]:
        """Yield provider deltas asynchronously so cancellation closes upstream."""
        normalized_messages = self._normalize_messages(messages)
        client = self._get_async_api_client()
        try:
            response = await client.chat.completions.create(
                model=self.model,
                messages=normalized_messages,
                temperature=float(self.temperature),
                stream=True,
            )
        except (APITimeoutError, TimeoutError) as exc:
            raise LLMTimeoutError("LLM streaming request timed out") from exc
        except Exception as exc:
            detail = self._safe_request_detail(exc)
            raise LLMRequestError(
                f"LLM streaming request failed ({detail})"
            ) from exc

        emitted = False
        close = getattr(response, "close", None)
        try:
            async for chunk in response:
                content = self._extract_stream_delta(chunk)
                if content is None:
                    continue
                emitted = True
                yield content
        except (LLMResponseError, LLMTimeoutError, LLMRequestError):
            raise
        except (APITimeoutError, TimeoutError) as exc:
            raise LLMTimeoutError("LLM stream timed out") from exc
        except Exception as exc:
            detail = self._safe_request_detail(exc)
            raise LLMRequestError(f"LLM stream failed ({detail})") from exc
        finally:
            if callable(close):
                try:
                    result = close()
                    if inspect.isawaitable(result):
                        await result
                except Exception:
                    pass
        if not emitted:
            raise LLMResponseError("LLM stream contains no assistant text")

    def _request_text(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
        *,
        response_format: dict[str, str] | None = None,
    ) -> str:
        """Send one completion request and extract its assistant text."""
        normalized_messages = self._normalize_messages(messages)
        client = self._get_api_client()
        request: dict[str, Any] = {
            "model": self.model,
            "messages": normalized_messages,
            "temperature": float(self.temperature),
        }
        if response_format is not None:
            request["response_format"] = dict(response_format)
        try:
            response = client.chat.completions.create(**request)
        except (APITimeoutError, TimeoutError) as exc:
            raise LLMTimeoutError("LLM request timed out") from exc
        except Exception as exc:
            detail = self._safe_request_detail(exc)
            raise LLMRequestError(f"LLM request failed ({detail})") from exc

        return self._extract_assistant_text(response)

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
        if not isinstance(self.json_mode_enabled, bool):
            raise LLMConfigurationError("LLM JSON mode flag must be a boolean")

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

    def _get_async_api_client(self) -> Any:
        """Validate the API key and lazily construct the async SDK client."""
        if not isinstance(self.api_key, str) or not self.api_key.strip():
            raise LLMConfigurationError("LLM API key is required")
        if self._async_api_client is None:
            self._async_api_client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=float(self.timeout_seconds),
                max_retries=0,
            )
        return self._async_api_client

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
    def _extract_assistant_text(response: object) -> str:
        """Extract text from the response shape returned by the OpenAI SDK."""
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

    @staticmethod
    def _extract_stream_delta(chunk: object) -> str | None:
        """Extract one optional text delta from an SDK stream chunk."""
        choices = getattr(chunk, "choices", None)
        if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)):
            raise LLMResponseError("LLM stream chunk has no valid choices list")
        if not choices:
            return None
        delta = getattr(choices[0], "delta", None)
        content = getattr(delta, "content", None)
        if content is None or content == "":
            return None
        if not isinstance(content, str):
            raise LLMResponseError(
                "LLM stream delta contains invalid assistant text"
            )
        return content

    @staticmethod
    def _safe_request_detail(exc: Exception) -> str:
        """Describe an upstream failure without including its response body."""
        status_code = getattr(exc, "status_code", None)
        if isinstance(status_code, int) and not isinstance(status_code, bool):
            return f"HTTP {status_code}"
        return type(exc).__name__


def parse_structured_output(
    text: str,
    response_model: type[StructuredOutputT],
) -> StructuredOutputT:
    """Extract the first JSON object and validate it against a Pydantic model."""
    if not isinstance(text, str) or not text.strip():
        raise LLMResponseError("Structured LLM response is empty")

    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        try:
            return response_model.model_validate(payload)
        except ValidationError as exc:
            raise LLMResponseError(
                f"Structured LLM response failed {response_model.__name__} validation"
            ) from exc

    raise LLMResponseError("Structured LLM response contains no valid JSON object")
