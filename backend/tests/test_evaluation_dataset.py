"""Acceptance tests for the formal, evidence-backed evaluation dataset."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation.models import EvaluationAnnotation
from evaluation.resolve_dataset import (
    DatasetResolutionError,
    read_jsonl,
    resolve_dataset,
)
from evaluation.validate_dataset import DatasetValidationError, validate_dataset


SOURCE_DATASET = REPO_ROOT / "evaluation" / "dataset.source.jsonl"
RESOLVED_DATASET = REPO_ROOT / "evaluation" / "dataset.jsonl"


def test_formal_dataset_meets_coverage_and_grounding_rules() -> None:
    """The committed dataset satisfies all Day 7 Task 04 acceptance rules."""
    rows = validate_dataset(RESOLVED_DATASET)

    counts = Counter(row.category for row in rows)
    assert len(rows) == 24
    assert counts == {
        "identifier": 6,
        "fact": 4,
        "comparison": 4,
        "procedure": 4,
        "citation": 3,
        "multi_chunk": 3,
    }
    assert sum(row.tests_structured_chunking for row in rows) >= 5
    assert {Path(row.source).suffix for row in rows} >= {".md", ".pdf"}


def test_evidence_resolution_is_deterministic_and_committed(tmp_path: Path) -> None:
    """Two independent resolutions produce the exact committed JSONL bytes."""
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"

    resolve_dataset(SOURCE_DATASET, first)
    resolve_dataset(SOURCE_DATASET, second)

    expected = RESOLVED_DATASET.read_bytes()
    assert first.read_bytes() == second.read_bytes() == expected


def test_multi_chunk_rows_resolve_to_multiple_ids_for_every_strategy() -> None:
    """Multi-chunk labels remain multi-chunk under baseline and optimized splits."""
    rows = validate_dataset(RESOLVED_DATASET)

    for row in rows:
        if row.category == "multi_chunk":
            assert all(
                len(chunk_ids) >= 2
                for chunk_ids in row.relevant_chunk_ids_by_strategy.values()
            )


def test_annotation_schema_rejects_duplicate_keywords() -> None:
    """Case-insensitive duplicate answer keywords are invalid."""
    payload = json.loads(SOURCE_DATASET.read_text(encoding="utf-8").splitlines()[0])
    payload["expected_answer_keywords"] = ["Thread_ID", "thread_id"]

    with pytest.raises(ValidationError, match="must be unique"):
        EvaluationAnnotation.model_validate(payload)


def test_validator_rejects_duplicate_sample_ids(tmp_path: Path) -> None:
    """Dataset-level uniqueness is checked independently of row validation."""
    lines = RESOLVED_DATASET.read_text(encoding="utf-8").splitlines()
    duplicate = json.loads(lines[1])
    duplicate["id"] = json.loads(lines[0])["id"]
    lines[1] = json.dumps(duplicate, ensure_ascii=False, separators=(",", ":"))
    invalid = tmp_path / "duplicate.jsonl"
    invalid.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(DatasetValidationError, match="duplicate sample IDs"):
        validate_dataset(invalid)


def test_jsonl_reader_reports_the_invalid_line(tmp_path: Path) -> None:
    """Malformed JSONL reports an actionable path and line number."""
    invalid = tmp_path / "broken.jsonl"
    valid_line = SOURCE_DATASET.read_text(encoding="utf-8").splitlines()[0]
    invalid.write_text(f"{valid_line}\nnot-json\n", encoding="utf-8")

    with pytest.raises(DatasetResolutionError, match=r"broken\.jsonl:2"):
        read_jsonl(invalid, EvaluationAnnotation)
