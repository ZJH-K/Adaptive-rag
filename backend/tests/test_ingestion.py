"""Integration tests for the synchronous ingestion pipeline."""

from pathlib import Path

import pymupdf
import pytest

from src.rag.chunking import RecursiveChunker
from src.rag.embeddings import EmbeddingRequestError
from src.rag.ingestion import IngestionPipeline
from src.rag.parsers import DocumentParseError
from src.rag.vectorstore import ChromaVectorStore
from tests.fakes import FakeEmbeddingClient


def _store(path: Path) -> ChromaVectorStore:
    return ChromaVectorStore(
        persist_dir=path,
        collection_name="ingestion_tests",
    )


def _create_pdf(path: Path, page_texts: list[str]) -> None:
    document = pymupdf.open()
    try:
        for text in page_texts:
            page = document.new_page()
            page.insert_text((72, 72), text)
        document.save(path)
    finally:
        document.close()


def test_markdown_complete_ingestion_preserves_source(tmp_path: Path) -> None:
    document_path = tmp_path / "guide.md"
    document_path.write_text(
        "# Dense Retrieval\n\n" + "Vector search content. " * 8,
        encoding="utf-8",
    )
    embedder = FakeEmbeddingClient()

    with _store(tmp_path / "chroma") as store:
        result = IngestionPipeline(
            embedder,
            store,
            chunker=RecursiveChunker(chunk_size=60, chunk_overlap=10),
        ).ingest(document_path)
        stored_chunks = store.get_chunks_by_document_id(result.document_id)

        assert result.filename == "guide.md"
        assert result.status == "done"
        assert result.chunks_count == len(stored_chunks) == store.count()
        assert embedder.document_calls == [
            [chunk.text for chunk in stored_chunks]
        ]
        assert all(chunk.source == "guide.md" for chunk in stored_chunks)
        assert all(chunk.source_type == "markdown" for chunk in stored_chunks)


def test_pdf_complete_ingestion_preserves_page_metadata(tmp_path: Path) -> None:
    document_path = tmp_path / "manual.pdf"
    _create_pdf(document_path, ["First PDF page", "Second PDF page"])

    with _store(tmp_path / "chroma") as store:
        result = IngestionPipeline(FakeEmbeddingClient(), store).ingest(
            document_path
        )
        stored_chunks = store.get_chunks_by_document_id(result.document_id)

        assert result.chunks_count == 2
        assert [chunk.page for chunk in stored_chunks] == [1, 2]
        assert all(chunk.source == "manual.pdf" for chunk in stored_chunks)
        assert all(chunk.source_type == "pdf" for chunk in stored_chunks)


def test_repeated_ingestion_is_idempotent(tmp_path: Path) -> None:
    document_path = tmp_path / "stable.md"
    document_path.write_text("Stable content. " * 15, encoding="utf-8")
    embedder = FakeEmbeddingClient()

    with _store(tmp_path / "chroma") as store:
        pipeline = IngestionPipeline(
            embedder,
            store,
            chunker=RecursiveChunker(chunk_size=50, chunk_overlap=10),
        )
        first = pipeline.ingest(document_path)
        first_chunks = store.get_chunks_by_document_id(first.document_id)
        first_count = store.count()

        second = pipeline.ingest(document_path)
        second_chunks = store.get_chunks_by_document_id(second.document_id)

        assert second.document_id == first.document_id
        assert second.chunks_count == first.chunks_count
        assert store.count() == first_count
        assert [chunk.chunk_id for chunk in second_chunks] == [
            chunk.chunk_id for chunk in first_chunks
        ]


def test_embedding_failure_does_not_write_partial_data(tmp_path: Path) -> None:
    document_path = tmp_path / "failure.md"
    document_path.write_text("Content that must not be stored.", encoding="utf-8")
    embedder = FakeEmbeddingClient(
        document_error=EmbeddingRequestError("synthetic failure")
    )

    with _store(tmp_path / "chroma") as store:
        pipeline = IngestionPipeline(embedder, store)

        with pytest.raises(EmbeddingRequestError, match="synthetic"):
            pipeline.ingest(document_path)

        assert store.count() == 0


def test_parser_error_propagates_without_embedding_or_write(tmp_path: Path) -> None:
    document_path = tmp_path / "empty.md"
    document_path.write_bytes(b"")
    embedder = FakeEmbeddingClient()

    with _store(tmp_path / "chroma") as store:
        pipeline = IngestionPipeline(embedder, store)

        with pytest.raises(DocumentParseError, match="empty"):
            pipeline.ingest(document_path)

        assert embedder.document_calls == []
        assert store.count() == 0

