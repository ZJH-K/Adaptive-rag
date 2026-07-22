"""LangGraph assembly for the lightweight adaptive RAG workflow."""

from __future__ import annotations

from functools import partial

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agent.nodes import (
    TextGenerator,
    direct_answer,
    generate_answer,
    retrieve,
    rewrite_query,
    route_query,
)
from src.agent.state import AgentState
from src.rag.service import ContextConstructor, Retriever


def build_graph(
    llm_client: TextGenerator,
    retriever: Retriever,
    context_builder: ContextConstructor | None = None,
) -> CompiledStateGraph:
    """Build and compile the two-branch adaptive RAG graph once."""

    workflow = StateGraph(AgentState)
    workflow.add_node(
        "route_query",
        partial(route_query, llm_client=llm_client),
    )
    workflow.add_node(
        "direct_answer",
        partial(direct_answer, llm_client=llm_client),
    )
    workflow.add_node(
        "rewrite_query",
        partial(rewrite_query, llm_client=llm_client),
    )
    workflow.add_node(
        "retrieve",
        partial(
            retrieve,
            retriever=retriever,
            context_builder=context_builder,
        ),
    )
    workflow.add_node(
        "generate_answer",
        partial(generate_answer, llm_client=llm_client),
    )

    workflow.add_edge(START, "route_query")
    workflow.add_conditional_edges(
        "route_query",
        _retrieval_required,
        {
            False: "direct_answer",
            True: "rewrite_query",
        },
    )
    workflow.add_edge("rewrite_query", "retrieve")
    workflow.add_edge("retrieve", "generate_answer")
    workflow.add_edge("direct_answer", END)
    workflow.add_edge("generate_answer", END)

    return workflow.compile(name="adaptive_rag")


def _retrieval_required(state: AgentState) -> bool:
    need_retrieval = state.get("need_retrieval")
    if not isinstance(need_retrieval, bool):
        raise ValueError("Agent state need_retrieval must be a boolean")
    return need_retrieval
