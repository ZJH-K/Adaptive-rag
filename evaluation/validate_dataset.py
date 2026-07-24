"""Validate the formal evaluation dataset and its source-grounded chunk IDs."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT_PATH = Path(__file__).resolve().parents[1]
if str(REPO_ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT_PATH))

from evaluation.models import ResolvedEvaluationSample
from evaluation.resolve_dataset import (
    REPO_ROOT,
    RESOLVED_DATASET,
    DatasetResolutionError,
    build_chunks,
    read_jsonl,
    resolve_annotation,
)


class DatasetValidationError(ValueError):
    """Raised when one or more dataset acceptance rules fail."""


def validate_dataset(
    dataset_path: Path = RESOLVED_DATASET,
    *,
    repo_root: Path = REPO_ROOT,
) -> list[ResolvedEvaluationSample]:
    """Validate schema, coverage, evidence locations, and strategy chunk IDs."""
    rows = read_jsonl(dataset_path, ResolvedEvaluationSample)
    errors: list[str] = []
    if not 20 <= len(rows) <= 30:
        errors.append(f"sample count must be 20-30, got {len(rows)}")

    ids = [row.id for row in rows]
    duplicate_ids = sorted(item for item, count in Counter(ids).items() if count > 1)
    if duplicate_ids:
        errors.append(f"duplicate sample IDs: {', '.join(duplicate_ids)}")

    category_counts = Counter(row.category for row in rows)
    required_categories = {
        "fact", "procedure", "identifier", "comparison", "multi_chunk", "citation"
    }
    missing_categories = sorted(required_categories - category_counts.keys())
    if missing_categories:
        errors.append(f"missing categories: {', '.join(missing_categories)}")
    if category_counts["identifier"] < 5:
        errors.append("at least 5 identifier samples are required")
    if category_counts["multi_chunk"] < 3:
        errors.append("at least 3 multi_chunk samples are required")
    structured_count = sum(row.tests_structured_chunking for row in rows)
    if structured_count < 5:
        errors.append("at least 5 structured-chunking samples are required")

    suffixes = {Path(row.source).suffix.lower() for row in rows}
    if ".pdf" not in suffixes or not suffixes.intersection({".md", ".markdown"}):
        errors.append("dataset must cover both PDF and Markdown sources")

    chunk_cache: dict[str, dict[str, list]] = {}
    for row in rows:
        try:
            if row.source not in chunk_cache:
                chunk_cache[row.source] = build_chunks(
                    row.source, repo_root=repo_root
                )
            chunks_by_strategy = chunk_cache[row.source]
            expected = resolve_annotation(row, chunks_by_strategy)
        except (OSError, DatasetResolutionError, ValueError) as exc:
            errors.append(f"{row.id}: {exc}")
            continue

        actual_strategies = set(row.relevant_chunk_ids_by_strategy)
        expected_strategies = set(chunks_by_strategy)
        if actual_strategies != expected_strategies:
            errors.append(
                f"{row.id}: strategies {sorted(actual_strategies)} do not match "
                f"{sorted(expected_strategies)}"
            )
        for strategy, chunk_ids in row.relevant_chunk_ids_by_strategy.items():
            real_ids = {chunk.chunk_id for chunk in chunks_by_strategy.get(strategy, [])}
            dangling = sorted(set(chunk_ids) - real_ids)
            if dangling:
                errors.append(f"{row.id}: nonexistent {strategy} chunk IDs: {dangling}")
        if row.relevant_chunk_ids_by_strategy != expected.relevant_chunk_ids_by_strategy:
            errors.append(f"{row.id}: chunk IDs do not match its annotated evidence")
        if row.relevant_chunk_ids != expected.relevant_chunk_ids:
            errors.append(f"{row.id}: relevant_chunk_ids is not the optimized mapping")
        if row.category == "multi_chunk":
            for strategy, chunk_ids in row.relevant_chunk_ids_by_strategy.items():
                if len(chunk_ids) < 2:
                    errors.append(
                        f"{row.id}: multi_chunk requires at least 2 IDs for {strategy}"
                    )

    if errors:
        raise DatasetValidationError("\n".join(f"- {error}" for error in errors))
    return rows


def main() -> int:
    """Run dataset validation from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", nargs="?", type=Path, default=RESOLVED_DATASET)
    args = parser.parse_args()
    try:
        rows = validate_dataset(args.dataset.resolve())
    except (OSError, DatasetResolutionError, DatasetValidationError, ValueError) as exc:
        parser.exit(1, f"validation failed:\n{exc}\n")
    counts = Counter(row.category for row in rows)
    summary = ", ".join(f"{key}={counts[key]}" for key in sorted(counts))
    print(f"Validated {len(rows)} samples ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
