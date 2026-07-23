"""Resolve manual evidence annotations to deterministic chunk IDs."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from evaluation.models import EvaluationAnnotation, ResolvedEvaluationSample
from src.rag.chunking.factory import get_chunker
from src.rag.parsers.factory import get_parser
from src.rag.schemas import Chunk, ParsedDocument


SOURCE_DATASET = Path(__file__).with_name("dataset.source.jsonl")
RESOLVED_DATASET = Path(__file__).with_name("dataset.jsonl")
_WHITESPACE = re.compile(r"\s+")


class DatasetResolutionError(ValueError):
    """Raised when an annotation cannot be mapped to source chunks."""


def _normalized(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def read_jsonl(path: Path, model_type: type[EvaluationAnnotation]) -> list:
    """Parse a JSONL file with line-aware syntax and model errors."""
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise DatasetResolutionError(f"{path}:{line_number}: blank line")
            try:
                payload = json.loads(line)
                rows.append(model_type.model_validate(payload))
            except (json.JSONDecodeError, ValueError) as exc:
                raise DatasetResolutionError(
                    f"{path}:{line_number}: invalid evaluation row: {exc}"
                ) from exc
    return rows


def strategies_for(document: ParsedDocument) -> tuple[str, str]:
    """Return baseline and source-optimized strategies for a document."""
    optimized = (
        "markdown_heading" if document.source_type == "markdown" else "pdf_page_aware"
    )
    return "recursive", optimized


def build_chunks(source: str, *, repo_root: Path = REPO_ROOT) -> dict[str, list[Chunk]]:
    """Parse one source and build all applicable strategy chunks."""
    source_path = (repo_root / source).resolve()
    knowledge_root = (repo_root / "knowledge").resolve()
    if knowledge_root not in source_path.parents or not source_path.is_file():
        raise DatasetResolutionError(
            f"source must be an existing file under knowledge/: {source}"
        )
    document = get_parser(source_path).parse(source_path)
    return {
        strategy: get_chunker(strategy, source_type=document.source_type).chunk(document)
        for strategy in strategies_for(document)
    }


def _matching_chunks(
    sample: EvaluationAnnotation,
    strategy: str,
    chunks: list[Chunk],
) -> list[Chunk]:
    matched: dict[str, Chunk] = {}
    for evidence_index, evidence in enumerate(sample.evidence, start=1):
        quote = _normalized(evidence.quote)
        candidates = chunks
        if evidence.page is not None:
            candidates = [chunk for chunk in candidates if chunk.page == evidence.page]
        if strategy == "markdown_heading":
            candidates = [
                chunk
                for chunk in candidates
                if chunk.section == evidence.section
                and chunk.heading_path == evidence.heading_path
            ]
        quote_matches = [
            chunk for chunk in candidates if quote in _normalized(chunk.text)
        ]
        if not quote_matches:
            raise DatasetResolutionError(
                f"{sample.id}: evidence {evidence_index} is not locatable in "
                f"{sample.source} using {strategy}: {evidence.quote!r}"
            )
        for chunk in quote_matches:
            matched[chunk.chunk_id] = chunk
    return sorted(matched.values(), key=lambda chunk: chunk.chunk_index)


def resolve_annotations(
    annotations: Iterable[EvaluationAnnotation],
    *,
    repo_root: Path = REPO_ROOT,
) -> list[ResolvedEvaluationSample]:
    """Resolve human evidence to IDs without using retrieval rankings."""
    chunk_cache: dict[str, dict[str, list[Chunk]]] = {}
    resolved: list[ResolvedEvaluationSample] = []
    for annotation in annotations:
        if annotation.source not in chunk_cache:
            chunk_cache[annotation.source] = build_chunks(
                annotation.source, repo_root=repo_root
            )
        resolved.append(resolve_annotation(annotation, chunk_cache[annotation.source]))
    return resolved


def resolve_annotation(
    annotation: EvaluationAnnotation,
    chunks_by_strategy: dict[str, list[Chunk]],
) -> ResolvedEvaluationSample:
    """Resolve one annotation against prebuilt strategy chunks."""
    ids_by_strategy = {
        strategy: [
            chunk.chunk_id
            for chunk in _matching_chunks(annotation, strategy, chunks)
        ]
        for strategy, chunks in chunks_by_strategy.items()
    }
    optimized_strategy = next(
        strategy for strategy in ids_by_strategy if strategy != "recursive"
    )
    payload = annotation.model_dump()
    payload["relevant_chunk_ids"] = ids_by_strategy[optimized_strategy]
    payload["relevant_chunk_ids_by_strategy"] = ids_by_strategy
    return ResolvedEvaluationSample.model_validate(payload)


def write_jsonl(path: Path, rows: Iterable[ResolvedEvaluationSample]) -> None:
    """Write stable UTF-8 JSONL with one compact object per line."""
    content = "".join(
        json.dumps(
            row.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
        for row in rows
    )
    path.write_text(content, encoding="utf-8", newline="\n")


def resolve_dataset(
    source_path: Path = SOURCE_DATASET,
    output_path: Path = RESOLVED_DATASET,
    *,
    repo_root: Path = REPO_ROOT,
) -> list[ResolvedEvaluationSample]:
    """Resolve a source JSONL file and write its generated dataset."""
    annotations = read_jsonl(source_path, EvaluationAnnotation)
    rows = resolve_annotations(annotations, repo_root=repo_root)
    write_jsonl(output_path, rows)
    return rows


def main() -> int:
    """Run the evidence resolver from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", type=Path, default=SOURCE_DATASET)
    parser.add_argument("output", nargs="?", type=Path, default=RESOLVED_DATASET)
    args = parser.parse_args()
    try:
        rows = resolve_dataset(args.source.resolve(), args.output.resolve())
    except (OSError, DatasetResolutionError, ValueError) as exc:
        parser.exit(1, f"resolution failed: {exc}\n")
    print(f"Resolved {len(rows)} samples to {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
