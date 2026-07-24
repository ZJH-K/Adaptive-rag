"""Runner behavior tests; fake providers here never produce formal reports."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation.metrics import evaluate_answer, evaluate_retrieval
from evaluation.run_eval import (
    DATASET_VERSION,
    EvaluationRunner,
    ExperimentConfig,
    ExperimentExecution,
    ProductionExperimentExecutor,
    RunnerExecutionError,
    SampleRunRecord,
    build_experiment_configs,
    exit_code_for_summary,
    validate_experiment_plans,
)
from evaluation.validate_dataset import validate_dataset
from src.config import Settings


DATASET = REPO_ROOT / "evaluation" / "dataset.jsonl"


def _settings(*, reranker: bool = True, credentials: bool = True) -> Settings:
    return Settings(
        _env_file=None,
        embedding_api_key="embedding-test" if credentials else None,
        llm_api_key="llm-test" if credentials else None,
        reranker_api_key="reranker-test" if credentials and reranker else None,
        embedding_model="test-embedding",
        llm_model="test-llm",
        reranker_model="test-reranker",
        dense_top_n=20,
        bm25_top_n=20,
        retrieve_top_n=20,
        rerank_top_k=5,
        rrf_k=60,
    )


class BehaviorFakeExecutor:
    """Return deterministic runner-control records, never formal quality data."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...], str]] = []

    def execute(self, config, samples, *, cutoffs):  # type: ignore[no-untyped-def]
        self.calls.append(
            (
                config.experiment,
                tuple(sample.id for sample in samples),
                str(config.persist_path),
            )
        )
        records = []
        for sample in samples:
            strategy = (
                "recursive"
                if config.chunk_strategy == "recursive"
                else "pdf_page_aware"
                if sample.source.endswith(".pdf")
                else "markdown_heading"
            )
            relevant = sample.relevant_chunk_ids_by_strategy[strategy]
            retrieved = [relevant[0]]
            answer = " ".join(sample.expected_answer_keywords)
            records.append(
                SampleRunRecord(
                    sample_id=sample.id,
                    experiment=config.experiment,
                    status="COMPLETED",
                    question=sample.question,
                    source=sample.source,
                    category=sample.category,
                    relevant_chunk_ids=relevant,
                    retrieved_chunk_ids=retrieved,
                    relevant_ranks={chunk_id: 1 if index == 0 else None for index, chunk_id in enumerate(relevant)},
                    retrieval_metrics=evaluate_retrieval(
                        retrieved, relevant, ks=cutoffs
                    ),
                    retrieval_latency_ms=10.0,
                    generated_answer=answer,
                    expected_answer_keywords=sample.expected_answer_keywords,
                    answer_metrics=evaluate_answer(
                        answer, sample.expected_answer_keywords
                    ),
                    generation_latency_ms=5.0,
                )
            )
        return ExperimentExecution(records=records, indexed_chunk_count=99)


class FailingBehaviorExecutor:
    def execute(self, config, samples, *, cutoffs):  # type: ignore[no-untyped-def]
        raise RunnerExecutionError("fake_provider_failed")


class UnexpectedExecutor:
    def execute(self, config, samples, *, cutoffs):  # type: ignore[no-untyped-def]
        raise AssertionError("validate-only must not execute providers")


def test_abcd_configuration_matrix_and_isolated_indexes(tmp_path: Path) -> None:
    configs = build_experiment_configs(_settings(), run_root=tmp_path)

    assert configs["A"].chunk_strategy == "recursive"
    assert configs["A"].bm25_enabled is False
    assert configs["A"].reranker_enabled is False
    assert configs["B"].chunk_strategy == "source_optimized"
    assert configs["B"].bm25_enabled is False
    assert configs["C"].bm25_enabled is True
    assert configs["C"].rrf_enabled is True
    assert configs["C"].reranker_enabled is False
    assert configs["D"].bm25_enabled is True
    assert configs["D"].reranker_enabled is True
    assert configs["A"].rerank_top_k == configs["A"].retrieve_top_n
    assert configs["D"].rerank_top_k == 5
    assert len({config.persist_path for config in configs.values()}) == 4
    assert len({config.collection_name for config in configs.values()}) == 4
    assert all(config.dataset_version == DATASET_VERSION for config in configs.values())


def test_validate_plan_checks_real_strategy_ids_without_credentials(
    tmp_path: Path,
) -> None:
    samples = validate_dataset(DATASET)
    configs = build_experiment_configs(_settings(credentials=False), run_root=tmp_path)

    counts = validate_experiment_plans(configs, samples)

    assert counts == {"A": 12, "B": 22, "C": 22, "D": 22}


def test_validate_only_writes_no_fake_sample_metrics(tmp_path: Path) -> None:
    summary, report_dir = EvaluationRunner(
        _settings(credentials=False), executor=UnexpectedExecutor()
    ).run(
        experiment_names=("A", "B", "C", "D"),
        output_dir=tmp_path / "validation",
        dataset_path=DATASET,
        validate_only=True,
        run_id="behavior-validation",
    )

    assert {item.status for item in summary.experiments.values()} == {"VALIDATED"}
    assert all(item.aggregate is None for item in summary.experiments.values())
    assert not list(report_dir.glob("samples_*.jsonl"))
    assert "N/A" in (report_dir / "report.md").read_text(encoding="utf-8")


def test_all_groups_reuse_identical_dataset_and_write_serializable_samples(
    tmp_path: Path,
) -> None:
    executor = BehaviorFakeExecutor()
    summary, report_dir = EvaluationRunner(
        _settings(), executor=executor
    ).run(
        experiment_names=("A", "B", "C", "D"),
        output_dir=tmp_path / "run",
        dataset_path=DATASET,
        run_id="behavior-all",
    )

    assert all(item.status == "COMPLETED" for item in summary.experiments.values())
    sample_sequences = [call[1] for call in executor.calls]
    assert len(sample_sequences) == 4
    assert all(sequence == sample_sequences[0] for sequence in sample_sequences)
    for name in "ABCD":
        lines = (report_dir / f"samples_{name}.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        assert len(lines) == 24
        payload = json.loads(lines[0])
        assert payload["experiment"] == name
        assert payload["retrieval_metrics"]["valid"] is True


def test_missing_reranker_skips_d_without_copying_c(tmp_path: Path) -> None:
    executor = BehaviorFakeExecutor()
    summary, report_dir = EvaluationRunner(
        _settings(reranker=False), executor=executor
    ).run(
        experiment_names=("A", "B", "C", "D"),
        output_dir=tmp_path / "missing-reranker",
        dataset_path=DATASET,
        run_id="behavior-missing-reranker",
    )

    assert summary.experiments["C"].status == "COMPLETED"
    assert summary.experiments["D"].status == "SKIPPED"
    assert summary.experiments["D"].reason_code == "reranker_not_configured"
    assert summary.experiments["D"].aggregate is None
    assert [call[0] for call in executor.calls] == ["A", "B", "C"]
    assert not (report_dir / "samples_D.jsonl").exists()
    assert exit_code_for_summary(summary) == 2


def test_missing_core_credentials_marks_every_group_not_run(tmp_path: Path) -> None:
    summary, report_dir = EvaluationRunner(
        _settings(credentials=False), executor=UnexpectedExecutor()
    ).run(
        experiment_names=("A", "B", "C", "D"),
        output_dir=tmp_path / "not-run",
        dataset_path=DATASET,
        run_id="behavior-not-run",
    )

    assert {item.status for item in summary.experiments.values()} == {"NOT_RUN"}
    assert {
        item.reason_code for item in summary.experiments.values()
    } == {"embedding_not_configured"}
    assert all(item.aggregate is None for item in summary.experiments.values())
    assert not list(report_dir.glob("samples_*.jsonl"))
    assert exit_code_for_summary(summary) == 2


def test_provider_failure_is_failed_not_zero_metric(tmp_path: Path) -> None:
    summary, report_dir = EvaluationRunner(
        _settings(), executor=FailingBehaviorExecutor()
    ).run(
        experiment_names=("C",),
        output_dir=tmp_path / "failed",
        dataset_path=DATASET,
        run_id="behavior-failed",
    )

    result = summary.experiments["C"]
    assert result.status == "FAILED"
    assert result.reason_code == "fake_provider_failed"
    assert result.aggregate is None
    assert not (report_dir / "samples_C.jsonl").exists()


def test_report_table_values_come_from_summary_json(tmp_path: Path) -> None:
    summary, report_dir = EvaluationRunner(
        _settings(), executor=BehaviorFakeExecutor()
    ).run(
        experiment_names=("A",),
        output_dir=tmp_path / "report",
        dataset_path=DATASET,
        run_id="behavior-report",
    )
    saved = json.loads((report_dir / "summary.json").read_text(encoding="utf-8"))
    report = (report_dir / "report.md").read_text(encoding="utf-8")
    aggregate = summary.experiments["A"].aggregate

    assert aggregate is not None
    expected_mrr = saved["experiments"]["A"]["aggregate"]["mrr"]
    assert expected_mrr == aggregate.mrr
    assert f"{expected_mrr:.4f}" in report
    assert "| A | COMPLETED |" in report
    assert report.count("组 Hit@1 命中") == 3


def test_output_directory_reuse_is_rejected_before_execution(tmp_path: Path) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    (output / "prior-run.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="must be empty"):
        EvaluationRunner(_settings(), executor=UnexpectedExecutor()).run(
            experiment_names=("A",),
            output_dir=output,
            dataset_path=DATASET,
            validate_only=True,
        )


def test_production_executor_rejects_nonempty_isolated_index(tmp_path: Path) -> None:
    index = tmp_path / "indexes" / "A"
    index.mkdir(parents=True)
    (index / "old-state").write_text("do not reuse", encoding="utf-8")
    config: ExperimentConfig = build_experiment_configs(
        _settings(), run_root=tmp_path
    )["A"]

    with pytest.raises(RunnerExecutionError, match="isolated_index_path_not_empty"):
        ProductionExperimentExecutor(_settings()).execute(
            config, validate_dataset(DATASET), cutoffs=(1, 3, 5, 10)
        )
