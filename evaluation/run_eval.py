"""Run auditable A/B/C/D retrieval and answer evaluation experiments."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Literal, Protocol


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
for import_root in (REPO_ROOT, BACKEND_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from pydantic import BaseModel, ConfigDict, Field

from evaluation.metrics import (
    AggregateEvaluationResult,
    AnswerMetrics,
    RetrievalMetrics,
    SampleEvaluationResult,
    UndefinedMetricError,
    aggregate_results,
    evaluate_answer,
    evaluate_retrieval,
    rerank_gain,
)
from evaluation.models import ResolvedEvaluationSample
from evaluation.resolve_dataset import RESOLVED_DATASET, build_chunks
from evaluation.validate_dataset import validate_dataset
from src.config import Settings
from src.llm.client import DeepSeekClient
from src.rag.context_builder import ContextBuilder, ContextSource
from src.rag.embeddings.client import EmbeddingClient
from src.rag.retrieval.pipeline import RetrievalDiagnostics, RetrievalResult
from src.rag.runtime import RetrievalRuntime, build_retrieval_runtime
from src.rag.service import BasicRAGService


DATASET_VERSION = "day7-task04-v1"
DEFAULT_KS = (1, 3, 5, 10)
ExperimentName = Literal["A", "B", "C", "D"]
ExperimentStatus = Literal["VALIDATED", "COMPLETED", "FAILED", "SKIPPED", "NOT_RUN"]
SampleStatus = Literal["COMPLETED", "FAILED"]


class ExperimentConfig(BaseModel):
    """Safe, serializable configuration for one experiment group."""

    model_config = ConfigDict(frozen=True)

    experiment: ExperimentName
    chunk_strategy: Literal["recursive", "source_optimized"]
    chunk_strategies_by_source_type: dict[str, str]
    dense_enabled: bool = True
    bm25_enabled: bool
    rrf_enabled: bool
    rrf_k: int = Field(gt=0)
    reranker_enabled: bool
    dense_top_n: int = Field(gt=0)
    bm25_top_n: int = Field(gt=0)
    retrieve_top_n: int = Field(gt=0)
    rerank_top_k: int = Field(gt=0)
    embedding_model: str
    reranker_model: str
    llm_model: str
    collection_name: str
    persist_path: str
    dataset_version: str
    chunk_size: int = Field(default=800, gt=0)
    chunk_overlap: int = Field(default=100, ge=0)


class ProviderReadiness(BaseModel):
    """Credential presence only; validation mode performs no external request."""

    embedding_configured: bool
    llm_configured: bool
    reranker_configured: bool


class RunConfiguration(BaseModel):
    """Auditable inputs and environment identity saved before execution."""

    run_id: str
    created_at_utc: str
    validate_only: bool
    dataset_path: str
    dataset_version: str
    dataset_sha256: str
    sample_count: int
    knowledge_files: list[str]
    knowledge_sha256: dict[str, str]
    cutoffs: list[int]
    python_version: str
    code_version: str | None
    working_tree_dirty: bool | None = None
    dependency_lock_sha256: str | None
    providers: ProviderReadiness
    experiments: dict[ExperimentName, ExperimentConfig]


class SampleRunRecord(BaseModel):
    """One auditable sample result, including stage scores and safe failures."""

    sample_id: str
    experiment: ExperimentName
    status: SampleStatus
    error_code: str | None = None
    question: str
    source: str
    category: str
    relevant_chunk_ids: list[str]
    retrieved_chunk_ids: list[str] = Field(default_factory=list)
    relevant_ranks: dict[str, int | None] = Field(default_factory=dict)
    retrieval_metrics: RetrievalMetrics | None = None
    retrieval_diagnostics: RetrievalDiagnostics | None = None
    retrieval_latency_ms: float | None = Field(default=None, ge=0.0)
    rerank_gain: float | None = None
    generated_answer: str | None = None
    expected_answer_keywords: list[str] = Field(default_factory=list)
    answer_metrics: AnswerMetrics | None = None
    sources: list[ContextSource] = Field(default_factory=list)
    generation_latency_ms: float | None = Field(default=None, ge=0.0)


class ExperimentExecution(BaseModel):
    """Raw execution output returned by a production or behavior-test executor."""

    records: list[SampleRunRecord]
    indexed_chunk_count: int = Field(ge=0)


class ExperimentSummary(BaseModel):
    """Status and optional aggregate for one experiment."""

    experiment: ExperimentName
    status: ExperimentStatus
    reason_code: str | None = None
    validated_chunk_count: int | None = Field(default=None, ge=0)
    indexed_chunk_count: int | None = Field(default=None, ge=0)
    completed_sample_count: int = Field(default=0, ge=0)
    failed_sample_count: int = Field(default=0, ge=0)
    aggregate: AggregateEvaluationResult | None = None


class EvaluationRunSummary(BaseModel):
    """Top-level report summary; NOT_RUN/SKIPPED groups have no aggregate."""

    run_id: str
    validate_only: bool
    dataset_version: str
    sample_count: int = Field(ge=0)
    experiments: dict[ExperimentName, ExperimentSummary]


class ExperimentExecutor(Protocol):
    """Injectable experiment boundary used by runner behavior tests."""

    def execute(
        self,
        config: ExperimentConfig,
        samples: Sequence[ResolvedEvaluationSample],
        *,
        cutoffs: tuple[int, ...],
    ) -> ExperimentExecution:
        """Execute one isolated experiment through real or fake providers."""
        ...


class RunnerExecutionError(RuntimeError):
    """Safe experiment-level failure with a reportable code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _FixedResultRetriever:
    """Expose one already-executed production retrieval result to RAGService."""

    def __init__(self, result: RetrievalResult) -> None:
        self.result = result

    def retrieve_with_diagnostics(self, query: str) -> RetrievalResult:
        return self.result


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _code_version() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    revision = result.stdout.strip()
    return revision or None


def _working_tree_dirty() -> bool | None:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return bool(result.stdout.strip())


def _safe_error_code(exc: Exception, prefix: str) -> str:
    """Return a class-based code without leaking provider messages or secrets."""
    name = type(exc).__name__
    safe_name = "".join(
        character.lower() if character.isalnum() else "_" for character in name
    ).strip("_")
    return f"{prefix}_{safe_name or 'error'}"


def build_experiment_configs(
    settings: Settings,
    *,
    run_root: Path,
) -> dict[ExperimentName, ExperimentConfig]:
    """Build the only allowed A/B/C/D configuration differences."""
    definitions: dict[ExperimentName, tuple[str, bool, bool]] = {
        "A": ("recursive", False, False),
        "B": ("source_optimized", False, False),
        "C": ("source_optimized", True, False),
        "D": ("source_optimized", True, True),
    }
    configs: dict[ExperimentName, ExperimentConfig] = {}
    for name, (chunk_strategy, hybrid, rerank) in definitions.items():
        persist_path = (run_root / "indexes" / name).resolve()
        configs[name] = ExperimentConfig(
            experiment=name,
            chunk_strategy=chunk_strategy,
            chunk_strategies_by_source_type=(
                {"markdown": "recursive", "pdf": "recursive"}
                if chunk_strategy == "recursive"
                else {"markdown": "markdown_heading", "pdf": "pdf_page_aware"}
            ),
            bm25_enabled=hybrid,
            rrf_enabled=hybrid,
            rrf_k=settings.rrf_k,
            reranker_enabled=rerank,
            dense_top_n=settings.dense_top_n,
            bm25_top_n=settings.bm25_top_n,
            retrieve_top_n=settings.retrieve_top_n,
            rerank_top_k=(settings.rerank_top_k if rerank else settings.retrieve_top_n),
            embedding_model=settings.embedding_model,
            reranker_model=settings.reranker_model,
            llm_model=settings.llm_model,
            collection_name=f"adaptive_rag_eval_{name.lower()}",
            persist_path=str(persist_path),
            dataset_version=DATASET_VERSION,
        )
    return configs


def _strategy_for_sample(
    config: ExperimentConfig, sample: ResolvedEvaluationSample
) -> str:
    source_type = "pdf" if Path(sample.source).suffix.lower() == ".pdf" else "markdown"
    return config.chunk_strategies_by_source_type[source_type]


def _relevant_ids(
    config: ExperimentConfig, sample: ResolvedEvaluationSample
) -> list[str]:
    strategy = _strategy_for_sample(config, sample)
    return list(sample.relevant_chunk_ids_by_strategy[strategy])


class ProductionExperimentExecutor:
    """Run experiments through production ingestion, retrieval, and RAG service."""

    def __init__(
        self,
        settings: Settings,
        *,
        embedding_factory: Callable[[Settings], EmbeddingClient] = EmbeddingClient,
        llm_factory: Callable[[Settings], DeepSeekClient] = DeepSeekClient,
        runtime_factory: Callable[..., RetrievalRuntime] = build_retrieval_runtime,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        self.settings = settings
        self.embedding_factory = embedding_factory
        self.llm_factory = llm_factory
        self.runtime_factory = runtime_factory
        self.clock = clock

    def execute(
        self,
        config: ExperimentConfig,
        samples: Sequence[ResolvedEvaluationSample],
        *,
        cutoffs: tuple[int, ...],
    ) -> ExperimentExecution:
        persist_path = Path(config.persist_path)
        if persist_path.exists() and any(persist_path.iterdir()):
            raise RunnerExecutionError("isolated_index_path_not_empty")
        persist_path.mkdir(parents=True, exist_ok=True)
        configured = self.settings.model_copy(
            update={
                "chroma_persist_dir": persist_path,
                "chroma_collection": config.collection_name,
                "hybrid_retrieval_enabled": config.bm25_enabled,
                "reranker_enabled": config.reranker_enabled,
                "dense_top_n": config.dense_top_n,
                "bm25_top_n": config.bm25_top_n,
                "retrieve_top_n": config.retrieve_top_n,
                "rerank_top_k": config.rerank_top_k,
                "rrf_k": config.rrf_k,
            }
        )
        embedding = self.embedding_factory(configured)
        llm = self.llm_factory(configured)
        runtime: RetrievalRuntime | None = None
        try:
            runtime = self.runtime_factory(
                embedding,
                settings=configured,
                persist_dir=persist_path,
                collection_name=config.collection_name,
            )
            self._ingest_corpus(runtime, config, samples)
            indexed_chunk_count = runtime.vector_store.count()
            records = [
                self._evaluate_sample(runtime, llm, config, sample, cutoffs)
                for sample in samples
            ]
            return ExperimentExecution(
                records=records,
                indexed_chunk_count=indexed_chunk_count,
            )
        except RunnerExecutionError:
            raise
        except Exception as exc:
            raise RunnerExecutionError(_safe_error_code(exc, "experiment")) from exc
        finally:
            if runtime is not None:
                runtime.close()
            else:
                embedding.close()
            llm.close()

    @staticmethod
    def _ingest_corpus(
        runtime: RetrievalRuntime,
        config: ExperimentConfig,
        samples: Sequence[ResolvedEvaluationSample],
    ) -> None:
        sources = sorted({sample.source for sample in samples})
        for source in sources:
            sample = next(item for item in samples if item.source == source)
            strategy = _strategy_for_sample(config, sample)
            result = runtime.ingestion_pipeline.ingest(
                REPO_ROOT / source,
                chunk_strategy=strategy,
            )
            if result.status != "done" or result.bm25_synced is False:
                raise RunnerExecutionError(result.error_code or "ingestion_partial")

    def _evaluate_sample(
        self,
        runtime: RetrievalRuntime,
        llm: DeepSeekClient,
        config: ExperimentConfig,
        sample: ResolvedEvaluationSample,
        cutoffs: tuple[int, ...],
    ) -> SampleRunRecord:
        relevant = _relevant_ids(config, sample)
        base = {
            "sample_id": sample.id,
            "experiment": config.experiment,
            "question": sample.question,
            "source": sample.source,
            "category": sample.category,
            "relevant_chunk_ids": relevant,
            "expected_answer_keywords": sample.expected_answer_keywords,
        }
        try:
            retrieval_result = runtime.retriever.retrieve_with_diagnostics(
                sample.question
            )
            diagnostics = retrieval_result.diagnostics
            if diagnostics.degradation_codes:
                raise RunnerExecutionError(
                    "retrieval_degraded_" + "_".join(diagnostics.degradation_codes)
                )
            retrieved = [hit.chunk_id for hit in retrieval_result.hits]
            retrieval_metrics = evaluate_retrieval(retrieved, relevant, ks=cutoffs)
            gain = self._rerank_gain(config, diagnostics, retrieved, relevant)

            generation_started = self.clock()
            service = BasicRAGService(
                _FixedResultRetriever(retrieval_result),
                llm,
                context_builder=ContextBuilder(),
            )
            response = service.answer(sample.question)
            generation_latency_ms = max(
                0.0, (self.clock() - generation_started) * 1000.0
            )
            answer_metrics = evaluate_answer(
                response.answer,
                sample.expected_answer_keywords,
            )
            return SampleRunRecord(
                **base,
                status="COMPLETED",
                retrieved_chunk_ids=retrieved,
                relevant_ranks=_relevant_ranks(retrieved, relevant),
                retrieval_metrics=retrieval_metrics,
                retrieval_diagnostics=diagnostics,
                retrieval_latency_ms=diagnostics.total_latency_ms,
                rerank_gain=gain,
                generated_answer=response.answer,
                answer_metrics=answer_metrics,
                sources=response.sources,
                generation_latency_ms=generation_latency_ms,
            )
        except Exception as exc:
            code = exc.code if isinstance(exc, RunnerExecutionError) else _safe_error_code(
                exc, "sample"
            )
            return SampleRunRecord(**base, status="FAILED", error_code=code)

    @staticmethod
    def _rerank_gain(
        config: ExperimentConfig,
        diagnostics: RetrievalDiagnostics,
        retrieved: list[str],
        relevant: list[str],
    ) -> float | None:
        if not config.reranker_enabled:
            return None
        before = [item.chunk_id for item in diagnostics.fused_results]
        try:
            return rerank_gain(before, retrieved, relevant)
        except UndefinedMetricError:
            return None


def _relevant_ranks(
    retrieved_ids: Sequence[str], relevant_ids: Sequence[str]
) -> dict[str, int | None]:
    positions = {chunk_id: rank for rank, chunk_id in enumerate(retrieved_ids, start=1)}
    return {chunk_id: positions.get(chunk_id) for chunk_id in relevant_ids}


def _aggregate_records(
    records: Sequence[SampleRunRecord], cutoffs: tuple[int, ...]
) -> AggregateEvaluationResult | None:
    metric_results = [
        SampleEvaluationResult(
            sample_id=record.sample_id,
            retrieval=record.retrieval_metrics,
            answer=record.answer_metrics,
            latency_ms=record.retrieval_latency_ms,
            rerank_gain=record.rerank_gain,
        )
        for record in records
        if record.retrieval_metrics is not None
    ]
    return aggregate_results(metric_results, ks=cutoffs) if metric_results else None


def _provider_readiness(settings: Settings) -> ProviderReadiness:
    return ProviderReadiness(
        embedding_configured=bool(
            isinstance(settings.embedding_api_key, str)
            and settings.embedding_api_key.strip()
        ),
        llm_configured=bool(
            isinstance(settings.llm_api_key, str) and settings.llm_api_key.strip()
        ),
        reranker_configured=bool(
            isinstance(settings.reranker_api_key, str)
            and settings.reranker_api_key.strip()
        ),
    )


def _preflight_status(
    config: ExperimentConfig,
    providers: ProviderReadiness,
    *,
    validate_only: bool,
) -> tuple[ExperimentStatus | None, str | None]:
    if validate_only:
        return "VALIDATED", "validation_only_no_metrics"
    if not providers.embedding_configured:
        return "NOT_RUN", "embedding_not_configured"
    if not providers.llm_configured:
        return "NOT_RUN", "llm_not_configured"
    if config.reranker_enabled and not providers.reranker_configured:
        return "SKIPPED", "reranker_not_configured"
    return None, None


def validate_experiment_plans(
    configs: dict[ExperimentName, ExperimentConfig],
    samples: Sequence[ResolvedEvaluationSample],
) -> dict[ExperimentName, int]:
    """Validate isolated index plans and evidence IDs without external services."""
    persist_paths = [Path(config.persist_path).resolve() for config in configs.values()]
    collection_names = [config.collection_name for config in configs.values()]
    if len(persist_paths) != len(set(persist_paths)):
        raise ValueError("experiment persist paths must be isolated")
    if len(collection_names) != len(set(collection_names)):
        raise ValueError("experiment collection names must be isolated")

    chunk_cache: dict[str, dict[str, list]] = {}
    validated_counts: dict[ExperimentName, int] = {}
    for name, config in configs.items():
        selected_ids: set[str] = set()
        total_chunks = 0
        for source in sorted({sample.source for sample in samples}):
            if source not in chunk_cache:
                chunk_cache[source] = build_chunks(source)
            sample = next(item for item in samples if item.source == source)
            strategy = _strategy_for_sample(config, sample)
            chunks = chunk_cache[source][strategy]
            total_chunks += len(chunks)
            selected_ids.update(chunk.chunk_id for chunk in chunks)
        for sample in samples:
            missing = set(_relevant_ids(config, sample)) - selected_ids
            if missing:
                raise ValueError(
                    f"{name}/{sample.id} has labels outside the planned index"
                )
        validated_counts[name] = total_chunks
    return validated_counts


class EvaluationRunner:
    """Validate, execute, persist, and report one auditable evaluation run."""

    def __init__(
        self,
        settings: Settings,
        *,
        executor: ExperimentExecutor | None = None,
    ) -> None:
        self.settings = settings
        self.executor = executor or ProductionExperimentExecutor(settings)

    def run(
        self,
        *,
        experiment_names: Sequence[ExperimentName],
        output_dir: Path,
        dataset_path: Path = RESOLVED_DATASET,
        validate_only: bool = False,
        cutoffs: tuple[int, ...] = DEFAULT_KS,
        run_id: str | None = None,
    ) -> tuple[EvaluationRunSummary, Path]:
        samples = validate_dataset(dataset_path.resolve())
        selected = tuple(dict.fromkeys(experiment_names))
        if not selected:
            raise ValueError("at least one experiment is required")
        if output_dir.exists() and any(output_dir.iterdir()):
            raise ValueError(f"output directory must be empty: {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=True)

        actual_run_id = run_id or datetime.now(timezone.utc).strftime(
            "eval-%Y%m%dT%H%M%SZ"
        )
        all_configs = build_experiment_configs(self.settings, run_root=output_dir)
        configs = {name: all_configs[name] for name in selected}
        validated_counts = validate_experiment_plans(configs, samples)
        providers = _provider_readiness(self.settings)
        manifest = _build_manifest(
            run_id=actual_run_id,
            validate_only=validate_only,
            dataset_path=dataset_path.resolve(),
            samples=samples,
            configs=configs,
            providers=providers,
            cutoffs=cutoffs,
        )
        _write_json(output_dir / "config.json", manifest)

        experiment_summaries: dict[ExperimentName, ExperimentSummary] = {}
        records_by_experiment: dict[ExperimentName, list[SampleRunRecord]] = {}
        for name, config in configs.items():
            preflight_status, reason = _preflight_status(
                config, providers, validate_only=validate_only
            )
            if preflight_status is not None:
                experiment_summaries[name] = ExperimentSummary(
                    experiment=name,
                    status=preflight_status,
                    reason_code=reason,
                    validated_chunk_count=validated_counts[name],
                )
                continue
            try:
                execution = self.executor.execute(config, samples, cutoffs=cutoffs)
            except RunnerExecutionError as exc:
                experiment_summaries[name] = ExperimentSummary(
                    experiment=name,
                    status="FAILED",
                    reason_code=exc.code,
                    validated_chunk_count=validated_counts[name],
                )
                continue
            records_by_experiment[name] = execution.records
            _write_jsonl(output_dir / f"samples_{name}.jsonl", execution.records)
            failed = sum(record.status == "FAILED" for record in execution.records)
            aggregate = _aggregate_records(execution.records, cutoffs)
            experiment_summaries[name] = ExperimentSummary(
                experiment=name,
                status="FAILED" if failed else "COMPLETED",
                reason_code="sample_failures" if failed else None,
                validated_chunk_count=validated_counts[name],
                indexed_chunk_count=execution.indexed_chunk_count,
                completed_sample_count=len(execution.records) - failed,
                failed_sample_count=failed,
                aggregate=aggregate,
            )

        summary = EvaluationRunSummary(
            run_id=actual_run_id,
            validate_only=validate_only,
            dataset_version=DATASET_VERSION,
            sample_count=len(samples),
            experiments=experiment_summaries,
        )
        _write_json(output_dir / "summary.json", summary)
        (output_dir / "report.md").write_text(
            render_markdown_report(manifest, summary, records_by_experiment),
            encoding="utf-8",
            newline="\n",
        )
        return summary, output_dir


def _build_manifest(
    *,
    run_id: str,
    validate_only: bool,
    dataset_path: Path,
    samples: Sequence[ResolvedEvaluationSample],
    configs: dict[ExperimentName, ExperimentConfig],
    providers: ProviderReadiness,
    cutoffs: tuple[int, ...],
) -> RunConfiguration:
    sources = sorted({sample.source for sample in samples})
    lock_path = BACKEND_ROOT / "uv.lock"
    return RunConfiguration(
        run_id=run_id,
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        validate_only=validate_only,
        dataset_path=str(dataset_path),
        dataset_version=DATASET_VERSION,
        dataset_sha256=_sha256_file(dataset_path),
        sample_count=len(samples),
        knowledge_files=sources,
        knowledge_sha256={source: _sha256_file(REPO_ROOT / source) for source in sources},
        cutoffs=list(cutoffs),
        python_version=platform.python_version(),
        code_version=_code_version(),
        working_tree_dirty=_working_tree_dirty(),
        dependency_lock_sha256=_sha256_file(lock_path) if lock_path.is_file() else None,
        providers=providers,
        experiments=configs,
    )


def _write_json(path: Path, model: BaseModel) -> None:
    path.write_text(
        json.dumps(model.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_jsonl(path: Path, records: Iterable[BaseModel]) -> None:
    path.write_text(
        "".join(
            json.dumps(
                record.model_dump(mode="json"),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
            for record in records
        ),
        encoding="utf-8",
        newline="\n",
    )


def _format_metric(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.4f}"


def _aggregate_value(
    summary: ExperimentSummary,
    field: str,
    *,
    k: int | None = None,
) -> float | None:
    aggregate = summary.aggregate
    if aggregate is None:
        return None
    value = getattr(aggregate, field)
    if k is not None:
        return value.get(k)
    return value


def _case_lines(
    records_by_experiment: dict[ExperimentName, list[SampleRunRecord]],
    *,
    positive: bool,
) -> list[str]:
    pairs: list[tuple[str, ExperimentName, ExperimentName, float]] = []
    for before, after in (("A", "B"), ("B", "C"), ("C", "D")):
        before_records = {
            item.sample_id: item for item in records_by_experiment.get(before, [])
        }
        after_records = {
            item.sample_id: item for item in records_by_experiment.get(after, [])
        }
        for sample_id in sorted(before_records.keys() & after_records.keys()):
            left = before_records[sample_id].retrieval_metrics
            right = after_records[sample_id].retrieval_metrics
            if left is None or right is None:
                continue
            delta = (right.reciprocal_rank or 0.0) - (left.reciprocal_rank or 0.0)
            if (positive and delta > 0) or (not positive and delta <= 0):
                pairs.append((sample_id, before, after, delta))
    pairs.sort(key=lambda item: item[3], reverse=positive)
    return [
        f"- {sample_id}：{before}→{after}，Reciprocal Rank 变化 {delta:+.4f}。"
        for sample_id, before, after, delta in pairs[:3]
    ]


def _successful_case_lines(
    records_by_experiment: dict[ExperimentName, list[SampleRunRecord]],
) -> list[str]:
    """Report real improvements, then successful Hit@1 cases without invention."""
    lines = _case_lines(records_by_experiment, positive=True)
    selected_ids = {line.split("：", maxsplit=1)[0].removeprefix("- ") for line in lines}
    if len(lines) >= 3:
        return lines[:3]
    for experiment in ("D", "C", "B", "A"):
        for record in records_by_experiment.get(experiment, []):
            metrics = record.retrieval_metrics
            if (
                record.sample_id in selected_ids
                or metrics is None
                or metrics.hit_rate_at_k.get(1) != 1.0
            ):
                continue
            lines.append(
                f"- {record.sample_id}：{experiment} 组 Hit@1 命中，"
                f"Reciprocal Rank {_format_metric(metrics.reciprocal_rank)}。"
            )
            selected_ids.add(record.sample_id)
            if len(lines) == 3:
                return lines
    return lines


def render_markdown_report(
    manifest: RunConfiguration,
    summary: EvaluationRunSummary,
    records_by_experiment: dict[ExperimentName, list[SampleRunRecord]],
) -> str:
    """Render a report directly from the same summary object saved as JSON."""
    lines = [
        f"# Adaptive RAG Evaluation — {summary.run_id}",
        "",
        "## 环境与配置",
        "",
        f"- 模式：{'VALIDATE ONLY（不产生指标）' if summary.validate_only else '正式执行'}",
        f"- 数据集版本：`{summary.dataset_version}`",
        f"- 样本数：{summary.sample_count}",
        f"- Python：`{manifest.python_version}`",
        f"- 代码版本：`{manifest.code_version or 'unavailable'}`",
        f"- 工作树状态：`{'dirty' if manifest.working_tree_dirty else 'clean' if manifest.working_tree_dirty is False else 'unavailable'}`",
        f"- Dataset SHA-256：`{manifest.dataset_sha256}`",
        f"- K：{', '.join(map(str, manifest.cutoffs))}",
        f"- Embedding 模型：`{next(iter(manifest.experiments.values())).embedding_model}`",
        f"- LLM 模型：`{next(iter(manifest.experiments.values())).llm_model}`",
        f"- Reranker 模型：`{next(iter(manifest.experiments.values())).reranker_model}`",
        "",
        "| 组 | Chunk | Retrieval | Rerank | Collection |",
        "|---|---|---|---|---|",
    ]
    for name, config in manifest.experiments.items():
        retrieval = "Dense + BM25 + RRF" if config.bm25_enabled else "Dense"
        lines.append(
            f"| {name} | {config.chunk_strategy} | {retrieval} | "
            f"{'Yes' if config.reranker_enabled else 'No'} | "
            f"`{config.collection_name}` |"
        )
    lines.extend(
        [
        "",
        "## 四组指标对比",
        "",
        "| 组 | 状态 | Hit@1 | Hit@5 | Recall@5 | MRR | 关键词覆盖率 | 检索延迟 ms |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for name, experiment in summary.experiments.items():
        lines.append(
            "| " + " | ".join(
                (
                    name,
                    experiment.status,
                    _format_metric(_aggregate_value(experiment, "mean_hit_rate_at_k", k=1)),
                    _format_metric(_aggregate_value(experiment, "mean_hit_rate_at_k", k=5)),
                    _format_metric(_aggregate_value(experiment, "mean_recall_at_k", k=5)),
                    _format_metric(_aggregate_value(experiment, "mrr")),
                    _format_metric(_aggregate_value(experiment, "mean_keyword_coverage")),
                    _format_metric(_aggregate_value(experiment, "average_latency_ms")),
                )
            ) + " |"
        )

    lines.extend(["", "## 阶段变化", ""])
    for before, after, label in (
        ("A", "B", "结构化切分"),
        ("B", "C", "Hybrid + RRF"),
        ("C", "D", "Rerank"),
    ):
        if before not in summary.experiments or after not in summary.experiments:
            continue
        left = _aggregate_value(summary.experiments[before], "mrr")
        right = _aggregate_value(summary.experiments[after], "mrr")
        delta = "N/A" if left is None or right is None else f"{right - left:+.4f}"
        lines.append(f"- {before}→{after}（{label}）：MRR 变化 {delta}。")

    lines.extend(["", "## 失败、跳过与未配置", ""])
    unavailable = [
        f"- {name}: {item.status} — `{item.reason_code or 'none'}`"
        for name, item in summary.experiments.items()
        if item.status != "COMPLETED"
    ]
    lines.extend(unavailable or ["- 无。"])

    lines.extend(["", "## 成功案例", ""])
    successes = _successful_case_lines(records_by_experiment)
    lines.extend(successes or ["- 未产生可审计的真实改善案例。"])
    lines.extend(["", "## 失败或退化案例", ""])
    regressions = _case_lines(records_by_experiment, positive=False)
    lines.extend(regressions or ["- 未产生可审计的真实失败/退化案例。"])

    lines.extend(
        [
            "",
            "## 已知限制",
            "",
            "- 这是 24 条项目内小数据集对比，不能外推为生产环境普适结论。",
            "- 外部 Provider 未配置或失败时不生成零分，也不复制其他组结果。",
            "- 关键词覆盖率只能检查核心词出现，不能替代答案忠实度人工复核。",
            "",
            "## 运行命令",
            "",
            "```bash",
            "uv run --project backend python evaluation/run_eval.py --validate-only --all",
            "uv run --project backend python evaluation/run_eval.py --all",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _default_output_dir(validate_only: bool) -> Path:
    prefix = "validation" if validate_only else "run"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return REPO_ROOT / "evaluation" / "reports" / f"{prefix}-{stamp}"


def _parse_experiments(args: argparse.Namespace) -> tuple[ExperimentName, ...]:
    if args.all:
        return "A", "B", "C", "D"
    if args.experiment:
        return (args.experiment,)
    raise ValueError("use --all or --experiment A|B|C|D")


def exit_code_for_summary(summary: EvaluationRunSummary) -> int:
    """Return success only for validation or fully completed formal selections."""
    if summary.validate_only:
        return 0
    return 0 if all(
        result.status == "COMPLETED" for result in summary.experiments.values()
    ) else 2


def main() -> int:
    """CLI entry point with explicit non-zero status for incomplete formal runs."""
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--all", action="store_true")
    selection.add_argument("--experiment", choices=("A", "B", "C", "D"))
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--dataset", type=Path, default=RESOLVED_DATASET)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    output_dir = (args.output_dir or _default_output_dir(args.validate_only)).resolve()
    try:
        experiments = _parse_experiments(args)
        summary, report_dir = EvaluationRunner(Settings()).run(
            experiment_names=experiments,
            output_dir=output_dir,
            dataset_path=args.dataset,
            validate_only=args.validate_only,
        )
    except Exception as exc:
        parser.exit(1, f"evaluation setup failed: {_safe_error_code(exc, 'setup')}\n")

    print(f"Evaluation artifacts: {report_dir}")
    for name, result in summary.experiments.items():
        print(f"{name}: {result.status} ({result.reason_code or 'ok'})")
    return exit_code_for_summary(summary)


if __name__ == "__main__":
    raise SystemExit(main())
