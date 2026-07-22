"""Offline tests for the contextual query-rewrite node."""

from collections.abc import Mapping, Sequence
from typing import TypeVar

import pytest
from pydantic import BaseModel

from src.agent.nodes import REWRITE_HISTORY_LIMIT, rewrite_query
from src.llm.client import ChatMessage, parse_structured_output


StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)


class FakeRewriteLLM:
    """Return fixed rewrite output and record messages without external calls."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[list[ChatMessage | Mapping[str, object]]] = []

    def generate(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
    ) -> str:
        self.calls.append(list(messages))
        return self.response

    def generate_structured(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
        response_model: type[StructuredOutputT],
    ) -> StructuredOutputT:
        """Parse configured text through the production fallback parser."""
        return parse_structured_output(self.generate(messages), response_model)


def _sent_text(client: FakeRewriteLLM) -> str:
    parts: list[str] = []
    for message in client.calls[0]:
        if isinstance(message, ChatMessage):
            parts.append(message.content)
        else:
            content = message.get("content")
            if isinstance(content, str):
                parts.append(content)
    return "\n".join(parts)


def test_contextual_reference_is_completed_with_necessary_entities() -> None:
    question = "上面提到的状态保存机制有什么限制？"
    history = [
        {
            "role": "user",
            "content": "LangGraph checkpoint 如何保存状态？",
        },
        {
            "role": "assistant",
            "content": "checkpoint 可用于持久化图状态。",
        },
    ]
    llm = FakeRewriteLLM(
        '{"rewritten_query": '
        '"LangGraph checkpoint 状态保存机制有哪些限制？"}'
    )
    state = {"question": question, "chat_history": history}

    result = rewrite_query(state, llm)

    assert result == {
        "rewritten_query": "LangGraph checkpoint 状态保存机制有哪些限制？"
    }
    assert "LangGraph" in result["rewritten_query"]
    assert "checkpoint" in result["rewritten_query"]
    assert "限制" in result["rewritten_query"]
    assert set(result) == {"rewritten_query"}
    assert state["question"] == question
    assert "LangGraph checkpoint 如何保存状态？" in _sent_text(llm)


def test_standalone_question_keeps_its_original_topic() -> None:
    question = "LangGraph checkpoint 如何持久化 Agent 状态？"
    llm = FakeRewriteLLM(
        '{"rewritten_query": '
        '"LangGraph checkpoint 如何持久化 Agent 状态？"}'
    )

    result = rewrite_query({"question": question}, llm)

    assert result == {"rewritten_query": question}


@pytest.mark.parametrize(
    "output",
    [
        '```json\n{"rewritten_query": "独立问题"}\n```',
        '结果如下：{"rewritten_query": "独立问题"}。',
    ],
)
def test_rewrite_accepts_wrapped_valid_json(output: str) -> None:
    llm = FakeRewriteLLM(output)

    result = rewrite_query({"question": "它是什么？"}, llm)

    assert result == {"rewritten_query": "独立问题"}


@pytest.mark.parametrize(
    "invalid_output",
    [
        "not json",
        "{}",
        '{"rewritten_query": "   "}',
        '{"rewritten_query": ["query one", "query two"]}',
        '{"rewritten_query": "valid", "extra": "forbidden"}',
        "",
    ],
)
def test_invalid_rewrite_output_falls_back_to_original_question(
    invalid_output: str,
) -> None:
    question = "  上面提到的机制有什么限制？  "
    llm = FakeRewriteLLM(invalid_output)

    result = rewrite_query({"question": question}, llm)

    assert result == {"rewritten_query": question.strip()}


def test_rewrite_prompt_uses_only_bounded_recent_history() -> None:
    history = [
        {"role": "user", "content": f"history-{index}"}
        for index in range(REWRITE_HISTORY_LIMIT + 2)
    ]
    llm = FakeRewriteLLM('{"rewritten_query": "独立检索问题"}')

    rewrite_query(
        {"question": "它有什么限制？", "chat_history": history},
        llm,
    )

    prompt = _sent_text(llm)
    assert "history-0" not in prompt
    assert "history-1" not in prompt
    for index in range(2, REWRITE_HISTORY_LIMIT + 2):
        assert f"history-{index}" in prompt


def test_rewrite_rejects_blank_question_before_llm_call() -> None:
    llm = FakeRewriteLLM('{"rewritten_query": "unused"}')

    with pytest.raises(ValueError, match="question"):
        rewrite_query({"question": "   "}, llm)

    assert llm.calls == []
