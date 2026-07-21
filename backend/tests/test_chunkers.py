"""Tests for the baseline recursive chunker and its factory."""

from hashlib import sha256

import pytest

from src.rag.chunking import (
    ChunkerConfigurationError,
    ChunkerFactory,
    RecursiveChunker,
    UnsupportedChunkingStrategyError,
)
from src.rag.schemas import ParsedDocument, ParsedPage


def _document(
    text: str,
    *,
    source_type: str = "markdown",
    filename: str = "guide.md",
    page_number: int | None = None,
) -> ParsedDocument:
    return ParsedDocument(
        document_id="document-sha256",
        filename=filename,
        source_type=source_type,  # type: ignore[arg-type]
        pages=[ParsedPage(text=text, page_number=page_number)],
    )


def test_short_text_produces_one_complete_chunk() -> None:
    chunks = RecursiveChunker(chunk_size=100, chunk_overlap=10).chunk(
        _document("Short technical note.")
    )

    assert len(chunks) == 1
    assert chunks[0].text == "Short technical note."
    assert chunks[0].chunk_index == 0
    assert chunks[0].chunk_strategy == "recursive"


def test_long_paragraph_prefers_sentence_boundaries() -> None:
    text = "First sentence is here. Second sentence is here. Third sentence ends."
    chunks = RecursiveChunker(chunk_size=45, chunk_overlap=0).chunk(_document(text))

    assert len(chunks) >= 2
    assert chunks[0].text.endswith(".")
    assert all(len(chunk.text) <= 45 for chunk in chunks)


def test_oversized_sentence_uses_character_fallback_with_overlap() -> None:
    text = "0123456789" * 9
    chunks = RecursiveChunker(chunk_size=30, chunk_overlap=6).chunk(_document(text))

    assert len(chunks) > 1
    assert all(len(chunk.text) <= 30 for chunk in chunks)
    assert chunks[0].text[-6:] == chunks[1].text[:6]


def test_whitespace_only_pages_do_not_generate_chunks() -> None:
    document = ParsedDocument(
        document_id="empty-pages",
        filename="empty.md",
        source_type="markdown",
        pages=[ParsedPage(text=" \n\n\t"), ParsedPage(text="\r\n")],
    )

    assert RecursiveChunker().chunk(document) == []


@pytest.mark.parametrize(
    ("chunk_size", "chunk_overlap", "message"),
    [
        (0, 0, "chunk_size"),
        (-1, 0, "chunk_size"),
        (100, -1, "chunk_overlap"),
        (100, 100, "smaller"),
        (100, 101, "smaller"),
        (100.0, 10, "integer"),
        (100, True, "integer"),
    ],
)
def test_invalid_configuration_is_rejected(
    chunk_size: int, chunk_overlap: int, message: str
) -> None:
    with pytest.raises(ChunkerConfigurationError, match=message):
        RecursiveChunker(  # type: ignore[arg-type]
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )


def test_pdf_pages_never_merge_and_retain_page_numbers() -> None:
    document = ParsedDocument(
        document_id="pdf-document",
        filename="manual.pdf",
        source_type="pdf",
        pages=[
            ParsedPage(text="Page one " * 12, page_number=1),
            ParsedPage(text="Page two " * 12, page_number=2),
        ],
    )

    chunks = RecursiveChunker(chunk_size=40, chunk_overlap=5).chunk(document)

    assert {chunk.page for chunk in chunks} == {1, 2}
    assert all(
        ("Page one" in chunk.text) != ("Page two" in chunk.text)
        for chunk in chunks
    )


def test_markdown_chunks_retain_source_and_baseline_metadata() -> None:
    chunks = RecursiveChunker(chunk_size=25, chunk_overlap=5).chunk(
        _document("Markdown content. " * 5, filename="reference.markdown")
    )

    assert chunks
    assert all(chunk.source == "reference.markdown" for chunk in chunks)
    assert all(chunk.source_type == "markdown" for chunk in chunks)
    assert all(chunk.page is None for chunk in chunks)
    assert all(chunk.section is None for chunk in chunks)
    assert all(chunk.heading_path == [] for chunk in chunks)


def test_repeated_chunking_has_stable_ids_hashes_and_order() -> None:
    document = _document("Stable sentence. " * 20)
    chunker = RecursiveChunker(chunk_size=60, chunk_overlap=10)

    first = chunker.chunk(document)
    second = chunker.chunk(document)

    assert [chunk.chunk_id for chunk in first] == [
        chunk.chunk_id for chunk in second
    ]
    assert [chunk.text for chunk in first] == [chunk.text for chunk in second]
    assert [chunk.chunk_index for chunk in first] == list(range(len(first)))
    assert all(len(chunk.chunk_id) == 64 for chunk in first)
    assert all(
        chunk.content_hash == sha256(chunk.text.encode("utf-8")).hexdigest()
        for chunk in first
    )


def test_factory_creates_configured_recursive_chunker() -> None:
    chunker = ChunkerFactory.create(
        " ReCuRsIvE ", chunk_size=256, chunk_overlap=32
    )

    assert isinstance(chunker, RecursiveChunker)
    assert chunker.chunk_size == 256
    assert chunker.chunk_overlap == 32


def test_factory_rejects_unknown_strategy() -> None:
    with pytest.raises(UnsupportedChunkingStrategyError, match="semantic"):
        ChunkerFactory.create("semantic")

