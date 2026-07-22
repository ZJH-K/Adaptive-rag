"""Integration tests for the synchronous ingestion pipeline."""

from pathlib import Path

import pymupdf
import pytest

from src.rag.chunking import IncompatibleChunkingStrategyError, RecursiveChunker
from src.rag.embeddings import EmbeddingRequestError
from src.rag.ingestion import IngestionPipeline
from src.rag.parsers import DocumentParseError
from src.rag.retrieval import BM25Index
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


def test_markdown_heading_strategy_persists_section_metadata(tmp_path: Path) -> None:
    document_path = tmp_path / "structured.md"
    document_path.write_text(
        "# Install\n\nOverview.\n\n## Configure\n\nConfiguration details.",
        encoding="utf-8",
    )

    with _store(tmp_path / "chroma") as store:
        result = IngestionPipeline(FakeEmbeddingClient(), store).ingest(
            document_path,
            chunk_strategy="markdown_heading",
        )
        stored_chunks = store.get_chunks_by_document_id(result.document_id)

        assert result.chunks_count == 2
        assert [chunk.section for chunk in stored_chunks] == [
            "Install",
            "Configure",
        ]
        assert [chunk.heading_path for chunk in stored_chunks] == [
            ["Install"],
            ["Install", "Configure"],
        ]
        assert all(
            chunk.chunk_strategy == "markdown_heading"
            for chunk in stored_chunks
        )


def test_pdf_page_aware_strategy_persists_page_metadata(tmp_path: Path) -> None:
    document_path = tmp_path / "page-aware.pdf"
    _create_pdf(document_path, ["First parsed page", "Second parsed page"])

    with _store(tmp_path / "chroma") as store:
        result = IngestionPipeline(FakeEmbeddingClient(), store).ingest(
            document_path,
            chunk_strategy="pdf_page_aware",
        )
        stored_chunks = store.get_chunks_by_document_id(result.document_id)

        assert result.chunks_count == 2
        assert [chunk.page for chunk in stored_chunks] == [1, 2]
        assert all(
            chunk.chunk_strategy == "pdf_page_aware" for chunk in stored_chunks
        )


def test_default_ingestion_strategy_remains_recursive(tmp_path: Path) -> None:
    document_path = tmp_path / "default.md"
    document_path.write_text("# Heading\n\nDefault body.", encoding="utf-8")

    with _store(tmp_path / "chroma") as store:
        result = IngestionPipeline(FakeEmbeddingClient(), store).ingest(
            document_path
        )
        stored_chunks = store.get_chunks_by_document_id(result.document_id)

        assert stored_chunks
        assert all(chunk.chunk_strategy == "recursive" for chunk in stored_chunks)


def test_same_strategy_reingestion_remains_idempotent(tmp_path: Path) -> None:
    document_path = tmp_path / "repeat-structured.md"
    document_path.write_text("# Stable\n\nStable body.", encoding="utf-8")

    with _store(tmp_path / "chroma") as store:
        pipeline = IngestionPipeline(FakeEmbeddingClient(), store)
        first = pipeline.ingest(
            document_path,
            chunk_strategy="markdown_heading",
        )
        count_after_first = store.count()
        second = pipeline.ingest(
            document_path,
            chunk_strategy="markdown_heading",
        )

        assert second.document_id == first.document_id
        assert second.chunks_count == first.chunks_count
        assert store.count() == count_after_first


def test_ingestion_rebuilds_bm25_index_from_complete_chroma_corpus(
    tmp_path: Path,
) -> None:
    first_path = tmp_path / "first.md"
    second_path = tmp_path / "second.md"
    first_path.write_text("First document thread_id.", encoding="utf-8")
    second_path.write_text("Second document similarity_search.", encoding="utf-8")

    with _store(tmp_path / "chroma") as store:
        bm25_index = BM25Index()
        pipeline = IngestionPipeline(
            FakeEmbeddingClient(),
            store,
            bm25_index=bm25_index,
        )
        first = pipeline.ingest(first_path)
        second = pipeline.ingest(second_path)

        assert len(bm25_index) == store.count() == 2
        assert {chunk.document_id for chunk in bm25_index.chunks} == {
            first.document_id,
            second.document_id,
        }
        assert bm25_index.generation == 2

        restarted_index = BM25Index.from_chunks(store.get_all_chunks())
        assert restarted_index.chunk_ids == bm25_index.chunk_ids


def test_different_strategies_create_distinct_document_representations(
    tmp_path: Path,
) -> None:
    document_path = tmp_path / "comparison.md"
    document_path.write_text(
        "# Comparison\n\nStructured comparison body.",
        encoding="utf-8",
    )

    with _store(tmp_path / "chroma") as store:
        pipeline = IngestionPipeline(FakeEmbeddingClient(), store)
        recursive = pipeline.ingest(document_path, chunk_strategy="recursive")
        count_after_recursive = store.count()
        structured = pipeline.ingest(
            document_path,
            chunk_strategy="markdown_heading",
        )
        stored_chunks = store.get_chunks_by_document_id(recursive.document_id)

        assert structured.document_id == recursive.document_id
        assert store.count() == count_after_recursive + structured.chunks_count
        assert {chunk.chunk_strategy for chunk in stored_chunks} == {
            "recursive",
            "markdown_heading",
        }


@pytest.mark.parametrize(
    ("suffix", "content", "strategy", "source_type"),
    [
        (".md", "Markdown body.", "pdf_page_aware", "markdown"),
        (".pdf", None, "markdown_heading", "pdf"),
    ],
)
def test_incompatible_ingestion_strategy_fails_before_embedding_or_write(
    tmp_path: Path,
    suffix: str,
    content: str | None,
    strategy: str,
    source_type: str,
) -> None:
    document_path = tmp_path / f"incompatible{suffix}"
    if content is None:
        _create_pdf(document_path, ["PDF body"])
    else:
        document_path.write_text(content, encoding="utf-8")
    embedder = FakeEmbeddingClient()

    with _store(tmp_path / "chroma") as store:
        pipeline = IngestionPipeline(embedder, store)

        with pytest.raises(
            IncompatibleChunkingStrategyError,
            match=rf"{strategy}.*{source_type}",
        ):
            pipeline.ingest(document_path, chunk_strategy=strategy)

        assert embedder.document_calls == []
        assert store.count() == 0
