"""Offline end-to-end acceptance test for the complete Day 1 RAG chain."""

from pathlib import Path

from src.rag.ingestion import IngestionPipeline
from src.rag.retrieval import DenseRetriever
from src.rag.vectorstore import ChromaVectorStore
from tests.fakes import FakeEmbeddingClient


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MARKDOWN_DOCUMENT = (
    PROJECT_ROOT / "knowledge" / "markdown" / "langgraph_checkpoint.md"
)
PDF_DOCUMENT = PROJECT_ROOT / "knowledge" / "pdf" / "dense_retrieval_guide.pdf"


def _acceptance_embedder() -> FakeEmbeddingClient:
    return FakeEmbeddingClient(
        vectors_by_token={
            "checkpoint": [1.0, 0.0, 0.0],
            "thread_id": [1.0, 0.0, 0.0],
            "retrieval pipeline": [0.0, 1.0, 0.0],
            "metadata": [0.0, 0.0, 1.0],
            "检索流程": [0.0, 1.0, 0.0],
            "标识符": [1.0, 0.0, 0.0],
        },
        default_vector=[0.0, 0.0, 1.0],
    )


def test_day1_full_chain_is_idempotent_persistent_and_retrievable(
    tmp_path: Path,
) -> None:
    persist_dir = tmp_path / "day1-chroma"
    embedder = _acceptance_embedder()

    first_store = ChromaVectorStore(
        persist_dir=persist_dir,
        collection_name="day1_acceptance",
    )
    try:
        pipeline = IngestionPipeline(embedder, first_store)
        markdown_result = pipeline.ingest(MARKDOWN_DOCUMENT)
        pdf_result = pipeline.ingest(PDF_DOCUMENT)
        first_count = first_store.count()
        first_markdown_ids = [
            chunk.chunk_id
            for chunk in first_store.get_chunks_by_document_id(
                markdown_result.document_id
            )
        ]
        first_pdf_chunks = first_store.get_chunks_by_document_id(
            pdf_result.document_id
        )

        repeated_markdown = pipeline.ingest(MARKDOWN_DOCUMENT)
        repeated_pdf = pipeline.ingest(PDF_DOCUMENT)

        assert repeated_markdown.document_id == markdown_result.document_id
        assert repeated_pdf.document_id == pdf_result.document_id
        assert first_store.count() == first_count
        assert [
            chunk.chunk_id
            for chunk in first_store.get_chunks_by_document_id(
                markdown_result.document_id
            )
        ] == first_markdown_ids
        assert [chunk.page for chunk in first_pdf_chunks] == [1, 2]
        assert all(chunk.source == "langgraph_checkpoint.md" for chunk in (
            first_store.get_chunks_by_document_id(markdown_result.document_id)
        ))
    finally:
        first_store.close()

    restarted_store = ChromaVectorStore(
        persist_dir=persist_dir,
        collection_name="day1_acceptance",
    )
    try:
        assert restarted_store.count() == first_count
        assert restarted_store.contains_document(markdown_result.document_id)
        assert restarted_store.contains_document(pdf_result.document_id)

        retriever = DenseRetriever(embedder, restarted_store, top_k=2)
        checkpoint_hits = retriever.retrieve("How is checkpoint configured?")
        identifier_hits = retriever.retrieve("状态持久化使用哪个标识符？")
        pipeline_hits = retriever.retrieve("PDF 的检索流程有哪些步骤？")

        assert checkpoint_hits[0].metadata["source"] == "langgraph_checkpoint.md"
        assert "checkpointer" in checkpoint_hits[0].text.casefold()
        assert identifier_hits[0].metadata["source"] == "langgraph_checkpoint.md"
        assert "thread_id" in identifier_hits[0].text
        assert pipeline_hits[0].metadata["source"] == "dense_retrieval_guide.pdf"
        assert pipeline_hits[0].metadata["page"] == 1
        assert "retrieval pipeline" in pipeline_hits[0].text.casefold()
    finally:
        restarted_store.close()

