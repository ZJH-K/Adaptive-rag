"""Explicit opt-in smoke test for DeepSeek structured Agent outputs."""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any

import pytest
from openai import OpenAI

from src.agent.nodes import rewrite_query, route_query
from src.config import Settings
from src.llm.client import DeepSeekClient


pytestmark = pytest.mark.external_llm


class RecordingCompletions:
    """Proxy a real SDK resource while retaining safe response summaries."""

    def __init__(self, resource: object) -> None:
        self.resource = resource
        self.raw_contents: list[str] = []

    def create(self, **kwargs: Any) -> object:
        """Forward one request and record only assistant content."""
        response = self.resource.create(**kwargs)  # type: ignore[attr-defined]
        choices = getattr(response, "choices", [])
        message = getattr(choices[0], "message", None) if choices else None
        content = getattr(message, "content", None)
        self.raw_contents.append(content if isinstance(content, str) else "")
        return response


def _summary(text: str, limit: int = 200) -> str:
    """Return a bounded single-line response summary without credentials."""
    normalized = " ".join(text.split())
    return normalized[:limit] + ("..." if len(normalized) > limit else "")


def test_real_deepseek_router_and_rewrite_structured_contract() -> None:
    """Validate two routes and one contextual rewrite against DeepSeek."""
    if os.getenv("RUN_LLM_SMOKE") != "1":
        pytest.skip("set RUN_LLM_SMOKE=1 to enable the external LLM smoke test")

    settings = Settings()
    if not settings.llm_api_key:
        pytest.skip("LLM_API_KEY is not configured")

    sdk = OpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        timeout=settings.llm_timeout_seconds,
        max_retries=0,
    )
    recorder = RecordingCompletions(sdk.chat.completions)
    api_client = SimpleNamespace(
        chat=SimpleNamespace(completions=recorder)
    )
    client = DeepSeekClient(settings=settings, api_client=api_client)

    try:
        direct = route_query({"question": "什么是 RAG？"}, client)
        retrieve = route_query(
            {"question": "我上传的 LangGraph 文档如何配置 checkpoint？"},
            client,
        )
        rewrite = rewrite_query(
            {
                "question": "上面提到的状态保存机制有什么限制？",
                "chat_history": [
                    {
                        "role": "user",
                        "content": "LangGraph checkpoint 如何保存状态？",
                    }
                ],
            },
            client,
        )

        assert direct["need_retrieval"] is False
        assert retrieve["need_retrieval"] is True
        assert rewrite["rewritten_query"]
    finally:
        for index, raw in enumerate(recorder.raw_contents, start=1):
            print(f"structured response {index}: {_summary(raw)}")
