"""Manual Day 1 smoke test using the configured real embedding service."""

from __future__ import annotations

import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.config import Settings  # noqa: E402
from src.rag.embeddings import (  # noqa: E402
    EmbeddingClient,
    EmbeddingConfigurationError,
    EmbeddingError,
)
from src.rag.ingestion import IngestionPipeline  # noqa: E402
from src.rag.retrieval import DenseRetriever  # noqa: E402
from src.rag.schemas import SearchHit  # noqa: E402
from src.rag.vectorstore import ChromaVectorStore  # noqa: E402


MARKDOWN_DOCUMENT = (
    PROJECT_ROOT / "knowledge" / "markdown" / "langgraph_checkpoint.md"
)
PDF_DOCUMENT = PROJECT_ROOT / "knowledge" / "pdf" / "dense_retrieval_guide.pdf"
QUESTIONS = (
    "文档中如何配置 LangGraph checkpoint？",
    "状态持久化需要使用哪个标识符？",
    "PDF 中提到的 Dense Retrieval 流程包含哪些步骤？",
)


def _print_hits(question: str, hits: list[SearchHit]) -> None:
    """Print concise, inspectable retrieval results without sensitive config."""
    print(f"\nQuestion: {question}")
    if not hits:
        print("  No results")
        return
    for rank, hit in enumerate(hits, start=1):
        metadata = hit.metadata
        preview = " ".join(hit.text.split())[:180]
        score = "n/a" if hit.dense_score is None else f"{hit.dense_score:.4f}"
        print(
            f"  {rank}. score={score} "
            f"source={metadata.get('source')} page={metadata.get('page')}"
        )
        print(f"     {preview}")


def run_smoke_test() -> int:
    """Run real ingestion, idempotency, persistence, and retrieval checks."""
    settings = Settings()
    if not settings.embedding_api_key or not settings.embedding_api_key.strip():
        print(
            "Smoke test not run: EMBEDDING_API_KEY is missing. "
            "Copy the project .env.example to .env, configure the embedding "
            "service, and run this command again.",
            file=sys.stderr,
        )
        return 2
    for document in (MARKDOWN_DOCUMENT, PDF_DOCUMENT):
        if not document.is_file():
            print(f"Smoke test failed: missing test document {document}", file=sys.stderr)
            return 1

    smoke_settings = settings.model_copy(
        update={
            "chroma_collection": f"{settings.chroma_collection}_day1_smoke"
        }
    )
    embedding_client = EmbeddingClient(settings=settings)
    first_store = ChromaVectorStore(settings=smoke_settings)
    try:
        pipeline = IngestionPipeline(embedding_client, first_store)
        markdown_result = pipeline.ingest(MARKDOWN_DOCUMENT)
        pdf_result = pipeline.ingest(PDF_DOCUMENT)
        count_after_first_ingestion = first_store.count()

        print(
            f"Markdown: document_id={markdown_result.document_id} "
            f"chunks={markdown_result.chunks_count}"
        )
        print(
            f"PDF: document_id={pdf_result.document_id} "
            f"chunks={pdf_result.chunks_count}"
        )

        repeated_markdown = pipeline.ingest(MARKDOWN_DOCUMENT)
        repeated_pdf = pipeline.ingest(PDF_DOCUMENT)
        count_after_repeated_ingestion = first_store.count()
        if repeated_markdown.document_id != markdown_result.document_id:
            raise RuntimeError("Markdown document_id changed across ingestion")
        if repeated_pdf.document_id != pdf_result.document_id:
            raise RuntimeError("PDF document_id changed across ingestion")
        if count_after_repeated_ingestion != count_after_first_ingestion:
            raise RuntimeError(
                "Repeated ingestion unexpectedly changed the Chroma chunk count"
            )
        print(
            "Idempotency: "
            f"count={count_after_first_ingestion} -> "
            f"{count_after_repeated_ingestion} (unchanged)"
        )
    finally:
        first_store.close()

    restarted_store = ChromaVectorStore(settings=smoke_settings)
    try:
        if restarted_store.count() != count_after_repeated_ingestion:
            raise RuntimeError("Persisted Chroma count changed after restart")
        if not restarted_store.contains_document(markdown_result.document_id):
            raise RuntimeError("Markdown document is missing after Chroma restart")
        if not restarted_store.contains_document(pdf_result.document_id):
            raise RuntimeError("PDF document is missing after Chroma restart")
        print(f"Persistence: restored {restarted_store.count()} chunks after restart")

        retriever = DenseRetriever(embedding_client, restarted_store, top_k=3)
        for question in QUESTIONS:
            hits = retriever.retrieve(question)
            if not hits:
                raise RuntimeError(f"No retrieval results for question: {question}")
            _print_hits(question, hits)
    finally:
        restarted_store.close()

    print("\nDay 1 real smoke test passed.")
    return 0


def main() -> int:
    """CLI entry point with safe, explicit configuration/request errors."""
    try:
        return run_smoke_test()
    except EmbeddingConfigurationError as exc:
        print(f"Smoke test configuration error: {exc}", file=sys.stderr)
        return 2
    except EmbeddingError as exc:
        print(f"Smoke test embedding error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
