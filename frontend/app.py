"""Streamlit browser demo for the Adaptive RAG FastAPI backend."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from api_client import APIClientError, AdaptiveRAGAPIClient
from sse import SSEEvent
from state import ChatAccumulator, bounded_chat_history, clear_conversation


KNOWLEDGE_BASE_ID = "technical_docs"


@st.cache_resource
def get_api_client() -> AdaptiveRAGAPIClient:
    """Reuse one connection-pooled API client across Streamlit reruns."""
    return AdaptiveRAGAPIClient.from_env()


def render_sources(sources: list[dict[str, Any]]) -> None:
    """Render only the citation descriptors received from the sources event."""
    if not sources:
        return
    with st.expander("Sources", expanded=True):
        for source in sorted(sources, key=_citation_order):
            citation_id = source.get("citation_id", "S?")
            filename = source.get("source", "unknown_source")
            page = source.get("page")
            section = source.get("section")
            heading_path = source.get("heading_path")
            if isinstance(page, int):
                location = f"第 {page} 页"
            elif isinstance(section, str) and section:
                location = f"章节：{section}"
            elif isinstance(heading_path, list) and heading_path:
                location = "章节：" + " › ".join(map(str, heading_path))
            else:
                location = "位置未标注"
            st.markdown(f"**[{citation_id}] {filename}** — {location}")


def render_process(process: dict[str, Any]) -> None:
    """Render observable workflow fields without prompts or hidden reasoning."""
    route = process.get("route")
    rewrite = process.get("rewrite")
    retrieval = process.get("retrieval")
    done = process.get("done")
    capabilities = process.get("capabilities") or {}
    if not any((route, rewrite, retrieval, done)):
        return

    with st.expander("RAG 过程", expanded=False):
        if isinstance(route, dict):
            branch = "检索增强" if route.get("need_retrieval") else "直接回答"
            st.markdown(f"**Router Decision:** {branch}")
            st.caption(str(route.get("reason") or "无附加原因"))
        if isinstance(rewrite, dict):
            st.markdown("**Query Rewrite**")
            st.code(str(rewrite.get("rewritten_query") or ""), language=None)
        if isinstance(retrieval, dict):
            degraded_sources = set(retrieval.get("degraded_sources") or [])
            dense_status = "degraded" if "dense" in degraded_sources else "ready"
            bm25_status = "degraded" if "bm25" in degraded_sources else "ready"
            dense, bm25, final = st.columns(3)
            dense.metric(
                "Dense Retrieval",
                retrieval.get("dense_count", 0),
                dense_status,
            )
            bm25.metric(
                "BM25 Retrieval",
                retrieval.get("bm25_count", 0),
                bm25_status,
            )
            final.metric("Final Candidates", retrieval.get("final_count", 0))
            st.markdown(
                "**RRF Fusion:** "
                + ("已执行" if retrieval.get("rrf_entered") else "未执行")
                + f"；融合候选 {retrieval.get('fused_count', 0)}"
            )
            reranker = capabilities.get("reranker") or {}
            st.markdown(
                "**Reranker Results:** "
                f"enabled={reranker.get('enabled', False)}, "
                f"configured={reranker.get('configured', False)}, "
                f"used={retrieval.get('rerank_entered', False)}, "
                f"degraded={retrieval.get('reranker_degraded', False)}, "
                f"top-k={retrieval.get('final_count', 0)}"
            )
            codes = retrieval.get("degradation_codes") or []
            if codes:
                st.warning("降级路径：" + ", ".join(map(str, codes)))
        if isinstance(done, dict):
            st.markdown("**Langfuse Trace 状态**")
            st.json(
                {
                    "request_id": done.get("request_id"),
                    "tracing_enabled": done.get("tracing_enabled", False),
                    "trace_id": done.get("trace_id"),
                    "trace_exported": done.get("trace_exported", False),
                    "trace_error_code": done.get("trace_error_code"),
                },
                expanded=False,
            )


def render_message(message: dict[str, Any]) -> None:
    """Render one browser-local chat message and its structured metadata."""
    role = message.get("role", "assistant")
    with st.chat_message(role):
        content = message.get("content")
        if isinstance(content, str) and content:
            st.markdown(content)
        error = message.get("error")
        if isinstance(error, dict):
            st.error(
                f"{error.get('message', '回答未完成。')} "
                f"({error.get('code', 'chat_error')})"
            )
        sources = message.get("sources")
        if isinstance(sources, list):
            render_sources(sources)
        process = message.get("process")
        if isinstance(process, dict):
            render_process(process)


def _citation_order(source: dict[str, Any]) -> int:
    citation_id = source.get("citation_id")
    if isinstance(citation_id, str) and citation_id.startswith("S"):
        try:
            return int(citation_id[1:])
        except ValueError:
            pass
    return 10_000


def _strategy_options(filename: str | None) -> list[str]:
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".pdf":
        return ["pdf_page_aware", "recursive"]
    if suffix in {".md", ".markdown"}:
        return ["markdown_heading", "recursive"]
    return ["recursive"]


def _show_ingestion_result(result: dict[str, Any], *, operation: str) -> None:
    status = result.get("status")
    if status == "done":
        st.sidebar.success(f"{operation}完成。")
    elif status == "degraded":
        st.sidebar.warning(
            f"{operation}已完成，但索引处于降级状态："
            f"{result.get('error_code') or result.get('failed', 0)}"
        )
    else:
        st.sidebar.error(f"{operation}失败。")


def main() -> None:
    """Render the complete document and streaming chat demo."""
    st.set_page_config(page_title="Adaptive RAG", page_icon="📚", layout="wide")
    st.title("Adaptive RAG 技术文档助手")
    st.caption("所有解析、检索与模型调用均由 FastAPI 后端执行。")

    if "messages" not in st.session_state:
        st.session_state.messages = []
    client = get_api_client()

    st.sidebar.header("知识库")
    knowledge_base_id = st.sidebar.selectbox(
        "当前知识库",
        [KNOWLEDGE_BASE_ID],
        disabled=True,
    )
    uploaded_file = st.sidebar.file_uploader(
        "上传 PDF / Markdown",
        type=["pdf", "md", "markdown"],
    )
    strategy = st.sidebar.selectbox(
        "Chunk Strategy",
        _strategy_options(uploaded_file.name if uploaded_file else None),
    )
    if st.sidebar.button("上传并建立索引", disabled=uploaded_file is None):
        try:
            result = client.upload_document(
                filename=uploaded_file.name,
                content=uploaded_file.getvalue(),
                content_type=uploaded_file.type or "application/octet-stream",
                knowledge_base_id=knowledge_base_id,
                chunk_strategy=strategy,
            )
            _show_ingestion_result(result, operation="上传")
        except APIClientError as exc:
            st.sidebar.error(f"上传失败：{exc.safe_message} ({exc.code})")

    if st.sidebar.button("加载内置知识库"):
        try:
            result = client.load_default(knowledge_base_id=knowledge_base_id)
            _show_ingestion_result(result, operation="内置知识库加载")
            st.sidebar.caption(
                f"processed={result.get('processed', 0)}, "
                f"skipped={result.get('skipped', 0)}, "
                f"failed={result.get('failed', 0)}"
            )
        except APIClientError as exc:
            st.sidebar.error(f"加载失败：{exc.safe_message} ({exc.code})")

    health: dict[str, Any] = {}
    try:
        stats = client.stats()
        documents, chunks = st.sidebar.columns(2)
        documents.metric("文档", stats.get("documents_count", 0))
        chunks.metric("Chunks", stats.get("chunks_count", 0))
        bm25 = stats.get("bm25") or {}
        st.sidebar.caption(
            f"BM25: {bm25.get('status', 'unknown')} · "
            f"generation {bm25.get('generation', 0)}"
        )
        health = client.health()
        reranker = health.get("reranker") or {}
        tracing = health.get("tracing") or {}
        st.sidebar.caption(
            "Reranker: "
            f"enabled={reranker.get('enabled', False)}, "
            f"available={reranker.get('available', False)}"
        )
        st.sidebar.caption(
            "Tracing: "
            f"enabled={tracing.get('enabled', False)}, "
            f"available={tracing.get('available', False)}"
        )
    except APIClientError as exc:
        st.sidebar.error(f"后端不可用：{exc.safe_message} ({exc.code})")

    if st.sidebar.button("清空当前会话"):
        clear_conversation(st.session_state)
        st.rerun()

    for message in st.session_state.messages:
        render_message(message)

    question = st.chat_input("询问通用问题或当前技术文档……")
    if not question:
        return

    history = bounded_chat_history(st.session_state.messages)
    user_message = {"role": "user", "content": question}
    st.session_state.messages.append(user_message)
    render_message(user_message)

    accumulator = ChatAccumulator()
    with st.chat_message("assistant"):
        answer_placeholder = st.empty()
        stream = client.stream_chat(
            question=question,
            knowledge_base_id=knowledge_base_id,
            chat_history=history,
        )
        try:
            for event in stream:
                accumulator.apply(event)
                if event.event == "token":
                    answer_placeholder.markdown(accumulator.answer + "▌")
        except APIClientError as exc:
            accumulator.apply(
                SSEEvent(
                    event="error",
                    data={
                        "code": exc.code,
                        "message": exc.safe_message,
                        "retryable": True,
                    },
                )
            )
        finally:
            stream.close()

        if accumulator.answer:
            answer_placeholder.markdown(accumulator.answer)
        elif accumulator.error:
            answer_placeholder.markdown("回答未完成。")
        if accumulator.error:
            st.error(
                f"{accumulator.error.get('message')} "
                f"({accumulator.error.get('code')})"
            )
        render_sources(accumulator.sources)
        message = accumulator.assistant_message(capabilities=health)
        render_process(message["process"])
    st.session_state.messages.append(message)


if __name__ == "__main__":
    main()
