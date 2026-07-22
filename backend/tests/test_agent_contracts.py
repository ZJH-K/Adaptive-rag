"""Deterministic tests for Agent state, structured outputs, and prompts."""

from typing import get_type_hints

import pytest
from pydantic import ValidationError

from src.agent.prompts import (
    QUERY_REWRITE_PROMPT,
    ROUTER_PROMPT,
    format_query_rewrite_prompt,
    format_router_prompt,
)
from src.agent.state import AgentState, RewriteResult, RouteDecision
from src.rag.context_builder import ContextSource
from src.rag.schemas import SearchHit


def test_agent_state_matches_the_workflow_contract() -> None:
    annotations = get_type_hints(AgentState)

    assert set(annotations) == {
        "question",
        "chat_history",
        "need_retrieval",
        "route_reason",
        "rewritten_query",
        "retrieved_documents",
        "context",
        "context_sources",
        "context_chunk_ids",
        "answer",
        "trace_id",
    }
    assert annotations["retrieved_documents"] == list[SearchHit]
    assert annotations["context_sources"] == list[ContextSource]
    assert annotations["context_chunk_ids"] == list[str]
    assert AgentState.__total__ is False


def test_valid_structured_outputs_are_parsed_and_trimmed() -> None:
    decision = RouteDecision(
        need_retrieval=True,
        reason="  问题依赖上传文档  ",
    )
    rewrite = RewriteResult(
        rewritten_query="  LangGraph checkpoint 有什么限制？  "
    )

    assert decision.reason == "问题依赖上传文档"
    assert rewrite.rewritten_query == "LangGraph checkpoint 有什么限制？"


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (RouteDecision, {"need_retrieval": True}),
        (RouteDecision, {"need_retrieval": "true", "reason": "文档问题"}),
        (RouteDecision, {"need_retrieval": True, "reason": "   "}),
        (RewriteResult, {}),
        (RewriteResult, {"rewritten_query": 123}),
        (RewriteResult, {"rewritten_query": "", "extra": "forbidden"}),
    ],
)
def test_invalid_structured_outputs_are_rejected(
    model: type[RouteDecision] | type[RewriteResult],
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_router_prompt_contains_required_routing_rules() -> None:
    assert "通用知识问题" in ROUTER_PROMPT
    assert "用户上传文档" in ROUTER_PROMPT
    assert "内置文档" in ROUTER_PROMPT
    assert "上面提到" in ROUTER_PROMPT
    assert "精确引用" in ROUTER_PROMPT
    assert "Markdown 代码块" in ROUTER_PROMPT
    assert "思维链" in ROUTER_PROMPT


def test_rewrite_prompt_contains_required_constraints() -> None:
    assert "独立检索问题" in QUERY_REWRITE_PROMPT
    assert "保留用户原意" in QUERY_REWRITE_PROMPT
    assert "不添加" in QUERY_REWRITE_PROMPT
    assert "一个独立问题" in QUERY_REWRITE_PROMPT
    assert "聊天历史" in QUERY_REWRITE_PROMPT
    assert "Markdown 代码块" in QUERY_REWRITE_PROMPT


def test_prompt_formatters_include_question_and_history() -> None:
    history = [
        {"role": "user", "content": "LangGraph 如何保存状态？"},
        {"role": "assistant", "content": "它使用 checkpoint。"},
    ]

    router_prompt = format_router_prompt("它有什么限制？", history)
    rewrite_prompt = format_query_rewrite_prompt("它有什么限制？", history)

    assert "它有什么限制？" in router_prompt
    assert "LangGraph 如何保存状态？" in router_prompt
    assert "它有什么限制？" in rewrite_prompt
    assert "checkpoint" in rewrite_prompt
    assert "{question}" not in router_prompt
    assert "{chat_history}" not in rewrite_prompt
