"""LangGraph assembly for the lightweight adaptive RAG workflow."""

from __future__ import annotations

from functools import partial

from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agent.nodes import (
    TextGenerator,
    adirect_answer,
    agenerate_answer,
    direct_answer,
    generate_answer,
    retrieve,
    rewrite_query,
    route_query,
)
from src.agent.state import AgentState
from src.observability.langfuse import build_trace_observer
from src.observability.tracing import TraceObserver
from src.rag.service import ContextConstructor, Retriever


def build_graph(
    llm_client: TextGenerator,
    retriever: Retriever,
    context_builder: ContextConstructor | None = None,
    observer: TraceObserver | None = None,
) -> CompiledStateGraph:
    """Build and compile the two-branch adaptive RAG graph once."""

    workflow = StateGraph(AgentState)
    configured_observer = observer or build_trace_observer()
    workflow.add_node(
        "route_query",
        partial(
            route_query,
            llm_client=llm_client,
            observer=configured_observer,
        ),
    )
    workflow.add_node(
        "direct_answer",
        RunnableLambda(
            partial(
                direct_answer,
                llm_client=llm_client,
                observer=configured_observer,
            ),
            afunc=partial(
                adirect_answer,
                llm_client=llm_client,
                observer=configured_observer,
            ),
            name="direct_answer",
        ),
    )
    workflow.add_node(
        "rewrite_query",
        partial(
            rewrite_query,
            llm_client=llm_client,
            observer=configured_observer,
        ),
    )
    workflow.add_node(
        "retrieve",
        partial(
            retrieve,
            retriever=retriever,
            context_builder=context_builder,
            observer=configured_observer,
        ),
    )
    workflow.add_node(
        "generate_answer",
        RunnableLambda(
            partial(
                generate_answer,
                llm_client=llm_client,
                observer=configured_observer,
            ),
            afunc=partial(
                agenerate_answer,
                llm_client=llm_client,
                observer=configured_observer,
            ),
            name="generate_answer",
        ),
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
    workflow.add_conditional_edges(
        "retrieve",
        _generation_allowed,
        {False: END, True: "generate_answer"},
    )
    workflow.add_edge("direct_answer", END)
    workflow.add_edge("generate_answer", END)

    return workflow.compile(name="adaptive_rag")


def _retrieval_required(state: AgentState) -> bool:
    need_retrieval = state.get("need_retrieval")
    if not isinstance(need_retrieval, bool):
        raise ValueError("Agent state need_retrieval must be a boolean")
    return need_retrieval


def _generation_allowed(state: AgentState) -> bool:
    """Stop after a fatal context failure instead of invoking generation."""

    return state.get("fatal_error") is None
