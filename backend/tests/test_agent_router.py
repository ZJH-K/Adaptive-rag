"""Offline tests for query routing and the direct-answer node."""

from collections.abc import Mapping, Sequence
from typing import TypeVar

import pytest
from pydantic import BaseModel

from src.agent.nodes import (
    ROUTER_PARSE_FAILURE_REASON,
    direct_answer,
    route_query,
)
from src.llm.client import ChatMessage, parse_structured_output


StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)


class FakeLLMClient:
    """Return configured text while recording every generation request."""

    def __init__(self, responses: dict[str, str], default: str = "通用回答") -> None:
        self.responses = responses
        self.default = default
        self.calls: list[list[ChatMessage | Mapping[str, object]]] = []

    def generate(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
    ) -> str:
        copied_messages = list(messages)
        self.calls.append(copied_messages)
        prompt = "\n".join(_message_content(message) for message in messages)
        for question, response in self.responses.items():
            if question in prompt:
                return response
        return self.default

    def generate_structured(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
        response_model: type[StructuredOutputT],
    ) -> StructuredOutputT:
        """Parse configured text through the production fallback parser."""
        return parse_structured_output(self.generate(messages), response_model)


def _message_content(message: ChatMessage | Mapping[str, object]) -> str:
    if isinstance(message, ChatMessage):
        return message.content
    content = message.get("content", "")
    return content if isinstance(content, str) else ""


@pytest.mark.parametrize(
    "question",
    [
        "什么是 RAG？",
        "请解释 Python list 和 tuple 的区别。",
    ],
)
def test_router_sends_general_questions_to_direct_answer(question: str) -> None:
    llm = FakeLLMClient(
        {
            question: (
                '{"need_retrieval": false, '
                '"reason": "这是可直接回答的通用知识问题"}'
            )
        }
    )

    result = route_query({"question": question}, llm)

    assert result["need_retrieval"] is False
    assert result["route_reason"] == "这是可直接回答的通用知识问题"
    assert result["current_stage"] == "router"
    assert result["answer_available"] is False


@pytest.mark.parametrize(
    ("question", "history"),
    [
        ("我上传的 LangGraph 文档中如何配置 checkpoint？", []),
        (
            "上面提到的状态保存机制有什么限制？",
            [
                {
                    "role": "user",
                    "content": "LangGraph 如何保存状态？",
                }
            ],
        ),
    ],
)
def test_router_sends_document_questions_to_retrieval(
    question: str,
    history: list[dict[str, object]],
) -> None:
    llm = FakeLLMClient(
        {
            question: (
                '{"need_retrieval": true, '
                '"reason": "问题依赖当前知识库或对话上下文"}'
            )
        }
    )

    result = route_query(
        {"question": question, "chat_history": history},
        llm,
    )

    assert result["need_retrieval"] is True
    assert result["route_reason"]
    if history:
        assert "LangGraph 如何保存状态？" in _message_content(llm.calls[0][0])


@pytest.mark.parametrize(
    "output",
    [
        '```json\n{"need_retrieval": false, "reason": "direct"}\n```',
        '说明：{"need_retrieval": false, "reason": "direct"} 完毕',
    ],
)
def test_router_accepts_wrapped_valid_json(output: str) -> None:
    llm = FakeLLMClient({}, default=output)

    result = route_query({"question": "测试问题"}, llm)

    assert result["need_retrieval"] is False
    assert result["route_reason"] == "direct"


@pytest.mark.parametrize(
    "invalid_output",
    [
        "not json",
        '{"need_retrieval": "yes", "reason": "invalid type"}',
        '{"need_retrieval": false}',
        '{"need_retrieval": false, "reason": "   "}',
        '{"need_retrieval": false, "reason": "direct", "extra": true}',
        "",
    ],
)
def test_invalid_router_output_conservatively_falls_back_to_retrieval(
    invalid_output: str,
) -> None:
    llm = FakeLLMClient({}, default=invalid_output)

    result = route_query({"question": "测试问题"}, llm)

    assert result["need_retrieval"] is True
    assert result["route_reason"] == ROUTER_PARSE_FAILURE_REASON
    event = result["degradation_events"][0]
    assert event.stage == "router"
    assert event.error_type == "invalid_response"
    assert event.fallback == "retrieve"


def test_direct_answer_returns_only_answer_without_retrieval_context() -> None:
    llm = FakeLLMClient({}, default="RAG 是检索增强生成。")
    state = {
        "question": "什么是 RAG？",
        "context": "SENSITIVE_RETRIEVAL_CONTEXT",
        "retrieved_documents": [],
    }

    result = direct_answer(state, llm)

    assert result["answer"] == "RAG 是检索增强生成。"
    assert result["current_stage"] == "direct_answer"
    assert result["answer_available"] is True
    sent_text = "\n".join(
        _message_content(message) for message in llm.calls[0]
    )
    assert "什么是 RAG？" in sent_text
    assert "SENSITIVE_RETRIEVAL_CONTEXT" not in sent_text


@pytest.mark.parametrize("node", [route_query, direct_answer])
def test_nodes_reject_missing_or_blank_questions(node) -> None:
    llm = FakeLLMClient({})

    with pytest.raises(ValueError, match="question"):
        node({"question": "   "}, llm)

    assert llm.calls == []
