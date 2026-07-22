"""Offline topology, isolation, redaction, and adapter tests for tracing."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any, TypeVar

from pydantic import BaseModel

from src.agent.graph import build_graph
from src.agent.state import RewriteResult, RouteDecision
from src.config import Settings
from src.llm.client import ChatMessage
from src.llm.exceptions import LLMTimeoutError
from src.observability.langfuse import LangfuseTraceObserver, build_trace_observer
from src.observability.tracing import (
    FakeTraceObserver,
    NoOpTraceObserver,
    TracingPolicy,
)
from src.rag.retrieval import (
    DenseRetrievalUnavailableError,
    HybridRetrievalPipeline,
    RerankerRequestError,
)
from src.rag.schemas import SearchHit


StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)
SECRET = "sk-secret-observability-value"


class TraceLLM:
    """Return deterministic branch decisions and answers."""

    def __init__(self, *, generation_fails: bool = False) -> None:
        self.generation_fails = generation_fails

    def generate_structured(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
        response_model: type[StructuredOutputT],
    ) -> StructuredOutputT:
        text = _message_text(messages)
        if response_model is RouteDecision:
            direct = "direct question" in text
            return response_model.model_validate(
                {
                    "need_retrieval": not direct,
                    "reason": "general" if direct else "document",
                }
            )
        return response_model.model_validate(
            {"rewritten_query": "standalone checkpoint query"}
        )

    def generate(
        self,
        messages: Sequence[ChatMessage | Mapping[str, object]],
    ) -> str:
        text = _message_text(messages)
        if "通用问答助手" in text:
            return "direct result"
        if self.generation_fails:
            raise LLMTimeoutError(f"generation timeout {SECRET}")
        return "grounded result [S1]"


class FakeRetriever:
    """Return configured path hits or a recognized request failure."""

    def __init__(
        self,
        hits: list[SearchHit],
        *,
        fail: bool = False,
        barrier: Barrier | None = None,
    ) -> None:
        self.hits = hits
        self.fail = fail
        self.barrier = barrier

    def retrieve(self, query: str, *, top_n: int | None = None) -> list[SearchHit]:
        if self.barrier is not None:
            self.barrier.wait(timeout=5)
        if self.fail:
            raise DenseRetrievalUnavailableError()
        return list(self.hits if top_n is None else self.hits[:top_n])


class SuccessReranker:
    """Apply deterministic scores while preserving all hit fields."""

    def rerank(self, query: str, hits: Sequence[SearchHit]) -> list[SearchHit]:
        return [
            hit.model_copy(update={"rerank_score": 1.0 - index * 0.1}, deep=True)
            for index, hit in enumerate(reversed(hits))
        ]


class FailedReranker:
    """Raise a recognized provider failure."""

    def rerank(self, query: str, hits: Sequence[SearchHit]) -> list[SearchHit]:
        raise RerankerRequestError(f"reranker failed {SECRET}")


def _hit(chunk_id: str, source: str) -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        text=f"private full document body {SECRET}",
        metadata={"source": f"{source}.md", "section": "Tracing"},
        dense_score=0.91 if source == "dense" else None,
        bm25_score=4.2 if source == "bm25" else None,
    )


def _pipeline(
    *,
    dense_fail: bool = False,
    reranker: Any = None,
    reranker_enabled: bool = False,
    barrier: Barrier | None = None,
) -> HybridRetrievalPipeline:
    return HybridRetrievalPipeline(
        FakeRetriever([_hit("dense-1", "dense")], fail=dense_fail, barrier=barrier),
        FakeRetriever([_hit("bm25-1", "bm25")]),
        reranker=reranker,
        settings=Settings(_env_file=None),
        hybrid_enabled=True,
        reranker_enabled=reranker_enabled,
        dense_top_n=2,
        bm25_top_n=2,
        retrieve_top_n=2,
        rerank_top_k=2,
    )


def _observer() -> FakeTraceObserver:
    return FakeTraceObserver(
        TracingPolicy(capture_question=True, capture_answer=True)
    )


def test_direct_branch_has_only_router_and_direct_answer() -> None:
    observer = _observer()
    result = build_graph(TraceLLM(), _pipeline(), observer=observer).invoke(
        {"question": "direct question"}
    )

    records = observer.records_for(result["trace_id"])
    assert [record.name for record in records] == [
        "chat_request", "router", "direct_answer"
    ]
    assert result["trace_id"] in observer.finished_trace_ids
    assert records[1].input["question"] == "direct question"
    assert records[-1].output["answer"] == "direct result"


def test_rag_branch_records_complete_topology_and_real_result_data() -> None:
    observer = _observer()
    result = build_graph(
        TraceLLM(),
        _pipeline(reranker=SuccessReranker(), reranker_enabled=True),
        observer=observer,
    ).invoke({"question": "document question"})

    records = observer.records_for(result["trace_id"])
    assert [record.name for record in records] == [
        "chat_request",
        "router",
        "query_rewrite",
        "dense_retrieval",
        "bm25_retrieval",
        "rrf_fusion",
        "rerank",
        "context_build",
        "final_answer",
    ]
    assert records[2].output["rewritten_query"] == "standalone checkpoint query"
    rerank = records[6]
    assert rerank.metadata["input_count"] == 2
    assert rerank.metadata["output_count"] == 2
    assert rerank.output["retrieved_chunk_ids"] == [
        hit.chunk_id for hit in result["retrieved_documents"]
    ]
    assert rerank.output["hits"][0]["rerank_score"] == 1.0
    assert records[5].output["retrieved_chunk_ids"] != (
        rerank.output["retrieved_chunk_ids"]
    )
    assert records[7].output["context_chunk_ids"] == result["context_chunk_ids"]
    assert records[8].output["sources"] == [
        source.model_dump() for source in result["context_sources"]
    ]


def test_disabled_reranker_does_not_create_observation() -> None:
    observer = _observer()
    result = build_graph(TraceLLM(), _pipeline(), observer=observer).invoke(
        {"question": "document question"}
    )

    names = [record.name for record in observer.records_for(result["trace_id"])]
    assert "rerank" not in names


def test_reranker_failure_and_dense_failure_are_warning_degradations() -> None:
    observer = _observer()
    result = build_graph(
        TraceLLM(),
        _pipeline(
            dense_fail=True,
            reranker=FailedReranker(),
            reranker_enabled=True,
        ),
        observer=observer,
    ).invoke({"question": "document question"})

    records = {record.name: record for record in observer.records_for(result["trace_id"])}
    assert records["dense_retrieval"].level == "WARNING"
    assert records["dense_retrieval"].metadata["fallback"] == (
        "remaining_retrieval_path"
    )
    assert records["rerank"].level == "WARNING"
    assert records["rerank"].metadata["fallback"] == "candidate_order"
    assert result["answer"] == "grounded result [S1]"


def test_generation_fatal_is_closed_and_contains_no_raw_error() -> None:
    observer = _observer()
    result = build_graph(
        TraceLLM(generation_fails=True),
        _pipeline(),
        observer=observer,
    ).invoke({"question": "document question"})

    final = observer.records_for(result["trace_id"])[-1]
    assert final.name == "final_answer"
    assert final.level == "ERROR"
    assert final.metadata["fatal"] is True
    assert result["trace_id"] in observer.finished_trace_ids
    assert SECRET not in repr(final)


def test_two_interleaved_requests_keep_trace_data_isolated() -> None:
    observer = _observer()
    barrier = Barrier(2)
    graph = build_graph(
        TraceLLM(),
        _pipeline(barrier=barrier),
        observer=observer,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(graph.invoke, {"question": f"document question {index}"})
            for index in range(2)
        ]
        results = [future.result(timeout=10) for future in futures]

    trace_ids = [result["trace_id"] for result in results]
    assert len(set(trace_ids)) == 2
    for index, trace_id in enumerate(trace_ids):
        records = observer.records_for(trace_id)
        assert len(records) == 8
        assert records[1].input["question"] == f"document question {index}"
        assert {record.trace_id for record in records} == {trace_id}


def test_unconfigured_factory_returns_noop() -> None:
    observer = build_trace_observer(
        Settings(_env_file=None, langfuse_enabled=False)
    )

    assert isinstance(observer, NoOpTraceObserver)
    status = observer.start_request()
    assert status.request_id is not None
    assert status.trace_id is None
    assert status.tracing_enabled is False


def test_default_redaction_blocks_content_and_credentials() -> None:
    observer = FakeTraceObserver()
    status = observer.start_request()
    assert status.request_id is not None
    observer.record(
        request_id=status.request_id,
        name="safe",
        kind="span",
        input={
            "question": f"private question {SECRET}",
            "api_key": SECRET,
            "headers": {"authorization": SECRET},
            "context": f"full document {SECRET}",
        },
        output={"answer": f"private answer {SECRET}"},
    )

    serialized = repr(observer.records[0])
    assert SECRET not in serialized
    assert observer.records[0].input["question"].startswith("[redacted;")
    assert "api_key" not in observer.records[0].input
    assert "headers" not in observer.records[0].input
    assert "context" not in observer.records[0].input


class RecordingObservation:
    def __init__(self, client: "RecordingSDKClient") -> None:
        self.client = client

    def update(self, **kwargs: Any) -> None:
        self.client.updated = True
        if self.client.fail_update:
            raise RuntimeError("SDK update failed")

    def start_observation(self, **kwargs: Any) -> "RecordingObservation":
        self.client.started += 1
        return RecordingObservation(self.client)

    def end(self) -> None:
        self.client.ended += 1


class RecordingSDKClient:
    def __init__(self, *, fail_start: bool = False, fail_update: bool = False) -> None:
        self.fail_start = fail_start
        self.fail_update = fail_update
        self.started = 0
        self.ended = 0
        self.updated = False

    def create_trace_id(self) -> str:
        if self.fail_start:
            raise RuntimeError("SDK ID failed")
        return "a" * 32

    def start_observation(self, **kwargs: Any) -> RecordingObservation:
        if self.fail_start:
            raise RuntimeError("SDK start failed")
        self.started += 1
        return RecordingObservation(self)

    def flush(self) -> None:
        return

    def shutdown(self) -> None:
        return


def test_langfuse_adapter_closes_span_when_sdk_update_raises() -> None:
    client = RecordingSDKClient(fail_update=True)
    observer = LangfuseTraceObserver(client, environment="test")

    status = observer.start_request()
    assert status.request_id is not None
    token = observer.start_observation(
        request_id=status.request_id,
        name="failing_sdk",
        kind="span",
    )
    observer.finish_observation(token, output={"answer": "safe"})

    assert client.started == 2
    assert client.ended == 1
    assert observer.get_status(status.request_id).trace_error_code == (
        "trace_observation_finish_failed"
    )


def test_langfuse_sdk_failure_never_changes_workflow_result() -> None:
    observer = LangfuseTraceObserver(
        RecordingSDKClient(fail_start=True),
        environment="test",
    )
    result = build_graph(TraceLLM(), _pipeline(), observer=observer).invoke(
        {"question": "document question"}
    )

    assert result["answer"] == "grounded result [S1]"
    assert result["request_id"]
    assert "trace_id" not in result
    assert result["tracing_status"].trace_error_code == "trace_creation_failed"


def _message_text(
    messages: Sequence[ChatMessage | Mapping[str, object]],
) -> str:
    return "\n".join(
        message.content
        if isinstance(message, ChatMessage)
        else str(message.get("content", ""))
        for message in messages
    )
