"""Run isolated real-service Day 2 baseline and optimized RAG comparisons."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.config import Settings
from src.llm import DeepSeekClient
from src.rag.context_builder import ContextBuilder
from src.rag.embeddings import EmbeddingClient
from src.rag.ingestion import IngestionPipeline
from src.rag.retrieval import DenseRetriever
from src.rag.service import BasicRAGService
from src.rag.vectorstore import ChromaVectorStore


KNOWLEDGE_ROOT = PROJECT_ROOT / "knowledge"
DEFAULT_QUESTION_IDS = ("d2-q01", "d2-q10")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunk-size", type=int, default=350)
    parser.add_argument("--chunk-overlap", type=int, default=40)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument(
        "--question-id",
        action="append",
        dest="question_ids",
        help="Question ID to run; repeat for multiple questions.",
    )
    parser.add_argument(
        "--with-answers",
        action="store_true",
        help="Call the configured LLM and include answers in the output.",
    )
    return parser.parse_args()


def _documents() -> list[Path]:
    return sorted((KNOWLEDGE_ROOT / "markdown").glob("*.md")) + sorted(
        (KNOWLEDGE_ROOT / "pdf").glob("*.pdf")
    )


def _questions(selected_ids: set[str]) -> list[dict[str, Any]]:
    path = KNOWLEDGE_ROOT / "day2_questions.jsonl"
    questions = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    selected = [item for item in questions if item["id"] in selected_ids]
    missing = selected_ids - {item["id"] for item in selected}
    if missing:
        raise ValueError(f"Unknown question IDs: {', '.join(sorted(missing))}")
    return selected


def _strategy(variant: str, suffix: str) -> str:
    if variant == "recursive":
        return "recursive"
    return "markdown_heading" if suffix == ".md" else "pdf_page_aware"


def _hit_summary(hit, rank: int) -> dict[str, Any]:
    metadata = hit.metadata
    return {
        "rank": rank,
        "chunk_id": hit.chunk_id,
        "source": metadata.get("source"),
        "page": metadata.get("page"),
        "section": metadata.get("section"),
        "heading_path": metadata.get("heading_path", []),
        "chunk_strategy": metadata.get("chunk_strategy"),
        "dense_score": hit.dense_score,
        "text_length": len(hit.text),
        "preview": hit.text[:160].replace("\n", " "),
    }


def _run_variant(
    variant: str,
    *,
    settings: Settings,
    questions: list[dict[str, Any]],
    chunk_size: int,
    chunk_overlap: int,
    top_k: int,
    with_answers: bool,
) -> dict[str, Any]:
    embedding_client = EmbeddingClient(settings)
    llm_client = DeepSeekClient(settings) if with_answers else None

    with TemporaryDirectory(prefix=f"adaptive-rag-day2-{variant}-") as directory:
        with ChromaVectorStore(
            settings,
            persist_dir=directory,
            collection_name=f"day2_{variant}",
        ) as store:
            pipeline = IngestionPipeline(
                embedding_client,
                store,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
            ingestion = []
            for path in _documents():
                strategy = _strategy(variant, path.suffix.lower())
                result = pipeline.ingest(path, chunk_strategy=strategy)
                ingestion.append(
                    {
                        "document": path.name,
                        "strategy": strategy,
                        "chunks_count": result.chunks_count,
                    }
                )

            retriever = DenseRetriever(embedding_client, store, top_k=top_k)
            question_results = []
            for item in questions:
                hits = retriever.retrieve(item["question"])
                context = ContextBuilder().build(hits)
                result: dict[str, Any] = {
                    "id": item["id"],
                    "question": item["question"],
                    "expected_document": item["document"],
                    "hits": [
                        _hit_summary(hit, rank)
                        for rank, hit in enumerate(hits, start=1)
                    ],
                    "context_length": len(context.context),
                    "used_chunk_ids": context.used_chunk_ids,
                }
                if llm_client is not None:
                    answer = BasicRAGService(
                        retriever,
                        llm_client,
                    ).answer(item["question"])
                    result["answer"] = answer.answer
                    result["sources"] = [
                        source.model_dump() for source in answer.sources
                    ]
                question_results.append(result)

            return {
                "variant": variant,
                "collection_chunks": store.count(),
                "ingestion": ingestion,
                "questions": question_results,
            }


def main() -> None:
    """Run both variants with identical models and print a JSON report."""
    args = _arguments()
    settings = Settings()
    selected_ids = set(args.question_ids or DEFAULT_QUESTION_IDS)
    questions = _questions(selected_ids)
    report = {
        "configuration": {
            "embedding_model": settings.embedding_model,
            "embedding_dimension": settings.embedding_dimension,
            "llm_model": settings.llm_model if args.with_answers else None,
            "chunk_size": args.chunk_size,
            "chunk_overlap": args.chunk_overlap,
            "top_k": args.top_k,
        },
        "variants": [
            _run_variant(
                variant,
                settings=settings,
                questions=questions,
                chunk_size=args.chunk_size,
                chunk_overlap=args.chunk_overlap,
                top_k=args.top_k,
                with_answers=args.with_answers,
            )
            for variant in ("recursive", "optimized")
        ],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
