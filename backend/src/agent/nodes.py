"""Node functions for the lightweight adaptive RAG workflow."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, TypeVar

from pydantic import BaseModel

from src.agent.prompts import (
    DIRECT_ANSWER_PROMPT,
    format_query_rewrite_prompt,
    format_router_prompt,
)
from src.agent.state import AgentState, RewriteResult, RouteDecision
from src.llm.client import ChatMessage
from src.llm.exceptions import LLMError, LLMResponseError
from src.rag.context_builder import ContextBuilder
from src.rag.service import (
    NO_EVIDENCE_ANSWER,
    ContextConstructor,
    RAGGenerationError,
    Retriever,
    build_rag_messages,
)


ROUTER_PARSE_FAILURE_REASON = "router_output_parse_failed"
REWRITE_HISTORY_LIMIT = 6
StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)


class TextGenerator(Protocol):
    """Minimal language-model capability required by Agent nodes."""

    def generate(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
    ) -> str:
        """Return assistant text for ordered messages."""
        ...

    def generate_structured(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
        response_model: type[StructuredOutputT],
    ) -> StructuredOutputT:
        """Return one provider-assisted, validated structured response."""
        ...


def route_query(
    state: AgentState,
    llm_client: TextGenerator,
) -> AgentState:
    """Classify a question and return only the routing state fields."""

    question = _require_question(state)
    prompt = format_router_prompt(question, state.get("chat_history"))
    try:
        decision = llm_client.generate_structured(
            [ChatMessage(role="user", content=prompt)],
            RouteDecision,
        )
    except LLMResponseError:
        return {
            "need_retrieval": True,
            "route_reason": ROUTER_PARSE_FAILURE_REASON,
        }

    return {
        "need_retrieval": decision.need_retrieval,
        "route_reason": decision.reason,
    }


def direct_answer(
    state: AgentState,
    llm_client: TextGenerator,
) -> AgentState:
    """Answer a general question without accessing retrieval context."""

    question = _require_question(state)
    answer = llm_client.generate(
        [
            ChatMessage(role="system", content=DIRECT_ANSWER_PROMPT),
            ChatMessage(role="user", content=question),
        ]
    )
    return {"answer": answer}


def rewrite_query(
    state: AgentState,
    llm_client: TextGenerator,
) -> AgentState:
    """Rewrite a contextual question as one standalone retrieval query."""

    question = _require_question(state)
    history = state.get("chat_history", [])[-REWRITE_HISTORY_LIMIT:]
    prompt = format_query_rewrite_prompt(question, history)
    try:
        result = llm_client.generate_structured(
            [ChatMessage(role="user", content=prompt)],
            RewriteResult,
        )
    except LLMResponseError:
        return {"rewritten_query": question}

    return {"rewritten_query": result.rewritten_query}


def retrieve(
    state: AgentState,
    retriever: Retriever,
    context_builder: ContextConstructor | None = None,
) -> AgentState:
    """Retrieve dense hits and build bounded citation-aware context."""

    question = _require_question(state)
    rewritten_query = state.get("rewritten_query")
    query = (
        rewritten_query.strip()
        if isinstance(rewritten_query, str) and rewritten_query.strip()
        else question
    )

    hits = list(retriever.retrieve(query))
    context_result = (context_builder or ContextBuilder()).build(hits)
    return {
        "retrieved_documents": hits,
        "context": context_result.context,
        "context_sources": context_result.sources,
        "context_chunk_ids": context_result.used_chunk_ids,
    }


def generate_answer(
    state: AgentState,
    llm_client: TextGenerator,
) -> AgentState:
    """Generate one grounded answer without performing another retrieval."""

    question = _require_question(state)
    context = state.get("context")
    retrieved_documents = state.get("retrieved_documents", [])
    if (
        not isinstance(context, str)
        or not context.strip()
        or not retrieved_documents
    ):
        return {"answer": NO_EVIDENCE_ANSWER}

    try:
        answer = llm_client.generate(build_rag_messages(question, context))
    except LLMError as exc:
        raise RAGGenerationError(
            "Unable to generate an answer from the retrieved context"
        ) from exc
    return {"answer": answer}


def _require_question(state: AgentState) -> str:
    question = state.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("Agent state question must be a non-empty string")
    return question.strip()
