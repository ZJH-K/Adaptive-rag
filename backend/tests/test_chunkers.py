"""Tests for the baseline recursive chunker and its factory."""

from hashlib import sha256

import pytest

from src.rag.chunking import (
    ChunkerConfigurationError,
    ChunkerFactory,
    IncompatibleChunkingStrategyError,
    MarkdownHeadingChunker,
    PDFPageAwareChunker,
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


@pytest.mark.parametrize(
    ("strategy", "source_type", "expected_type"),
    [
        ("recursive", "markdown", RecursiveChunker),
        ("markdown_heading", "markdown", MarkdownHeadingChunker),
        ("pdf_page_aware", "pdf", PDFPageAwareChunker),
    ],
)
def test_factory_creates_each_compatible_strategy(
    strategy: str, source_type: str, expected_type: type[object]
) -> None:
    chunker = ChunkerFactory.create(
        strategy,
        source_type=source_type,  # type: ignore[arg-type]
        chunk_size=256,
        chunk_overlap=32,
    )

    assert isinstance(chunker, expected_type)
    assert chunker.chunk_size == 256
    assert chunker.chunk_overlap == 32


@pytest.mark.parametrize(
    ("strategy", "source_type"),
    [
        ("markdown_heading", "pdf"),
        ("pdf_page_aware", "markdown"),
    ],
)
def test_factory_rejects_incompatible_document_types(
    strategy: str, source_type: str
) -> None:
    with pytest.raises(
        IncompatibleChunkingStrategyError,
        match=rf"{strategy}.*{source_type}",
    ):
        ChunkerFactory.create(
            strategy,
            source_type=source_type,  # type: ignore[arg-type]
        )


def test_factory_rejects_unknown_strategy() -> None:
    with pytest.raises(UnsupportedChunkingStrategyError, match="semantic"):
        ChunkerFactory.create("semantic")


def test_markdown_heading_chunker_merges_paragraphs_under_one_heading() -> None:
    chunks = MarkdownHeadingChunker(chunk_size=100, chunk_overlap=0).chunk(
        _document("# Install\n\nFirst paragraph.\n\nSecond paragraph.")
    )

    assert len(chunks) == 1
    assert chunks[0].text == "First paragraph.\n\nSecond paragraph."
    assert chunks[0].section == "Install"
    assert chunks[0].heading_path == ["Install"]
    assert chunks[0].chunk_strategy == "markdown_heading"
    assert chunks[0].document_id == "document-sha256"
    assert chunks[0].source == "guide.md"
    assert chunks[0].source_type == "markdown"


def test_markdown_heading_chunker_tracks_nested_and_returned_paths() -> None:
    text = """# Install
intro
## Environment
environment body
### Python
python body
## Verify
verify body
# Usage
usage body"""

    chunks = MarkdownHeadingChunker(chunk_size=100, chunk_overlap=0).chunk(
        _document(text)
    )

    assert [chunk.heading_path for chunk in chunks] == [
        ["Install"],
        ["Install", "Environment"],
        ["Install", "Environment", "Python"],
        ["Install", "Verify"],
        ["Usage"],
    ]
    assert [chunk.section for chunk in chunks] == [
        "Install",
        "Environment",
        "Python",
        "Verify",
        "Usage",
    ]


def test_oversized_markdown_section_retains_heading_metadata() -> None:
    chunks = MarkdownHeadingChunker(chunk_size=45, chunk_overlap=5).chunk(
        _document("## Configuration\n\n" + "Long configuration sentence. " * 8)
    )

    assert len(chunks) > 1
    assert all(len(chunk.text) <= 45 for chunk in chunks)
    assert all(chunk.section == "Configuration" for chunk in chunks)
    assert all(chunk.heading_path == ["Configuration"] for chunk in chunks)


def test_headingless_markdown_uses_stable_recursive_fallback() -> None:
    document = _document("First paragraph.\n\n" + "Second paragraph. " * 5)
    chunker = MarkdownHeadingChunker(chunk_size=50, chunk_overlap=5)

    chunks = chunker.chunk(document)

    assert chunks
    assert all(chunk.section is None for chunk in chunks)
    assert all(chunk.heading_path == [] for chunk in chunks)
    assert "First paragraph." in chunks[0].text


def test_blank_content_consecutive_headings_and_no_final_newline_are_safe() -> None:
    text = "\n\n# Empty\n## Actual\n\nBody without final newline"

    chunks = MarkdownHeadingChunker(chunk_size=100, chunk_overlap=0).chunk(
        _document(text)
    )

    assert len(chunks) == 1
    assert chunks[0].text == "Body without final newline"
    assert chunks[0].heading_path == ["Empty", "Actual"]


def test_markdown_heading_chunks_have_stable_identity_and_continuous_indexes() -> None:
    document = _document("# One\nBody one.\n## Two\n" + "Body two. " * 10)
    chunker = MarkdownHeadingChunker(chunk_size=40, chunk_overlap=5)

    first = chunker.chunk(document)
    second = chunker.chunk(document)

    assert [chunk.chunk_index for chunk in first] == list(range(len(first)))
    assert [chunk.chunk_id for chunk in first] == [
        chunk.chunk_id for chunk in second
    ]
    assert [chunk.content_hash for chunk in first] == [
        chunk.content_hash for chunk in second
    ]
    assert all(len(chunk.chunk_id) == 64 for chunk in first)
    assert all(
        chunk.content_hash == sha256(chunk.text.encode("utf-8")).hexdigest()
        for chunk in first
    )


def test_markdown_heading_lines_are_metadata_not_chunk_text() -> None:
    chunks = MarkdownHeadingChunker(chunk_size=100, chunk_overlap=0).chunk(
        _document("# API Reference ###\nEndpoint details.")
    )

    assert chunks[0].text == "Endpoint details."
    assert chunks[0].heading_path == ["API Reference"]


def _pdf_document(pages: list[ParsedPage]) -> ParsedDocument:
    return ParsedDocument(
        document_id="pdf-document-sha256",
        filename="manual.pdf",
        source_type="pdf",
        pages=pages,
    )


def test_pdf_page_aware_chunker_preserves_each_parsed_page_number() -> None:
    document = _pdf_document(
        [
            ParsedPage(text="First page content.", page_number=1),
            ParsedPage(text="Second page content.", page_number=2),
        ]
    )

    chunks = PDFPageAwareChunker(chunk_size=100, chunk_overlap=0).chunk(document)

    assert [(chunk.page, chunk.text) for chunk in chunks] == [
        (1, "First page content."),
        (2, "Second page content."),
    ]
    assert all(chunk.source == "manual.pdf" for chunk in chunks)
    assert all(chunk.source_type == "pdf" for chunk in chunks)
    assert all(chunk.document_id == "pdf-document-sha256" for chunk in chunks)
    assert all(chunk.chunk_strategy == "pdf_page_aware" for chunk in chunks)


def test_pdf_page_aware_chunker_merges_short_same_page_paragraphs() -> None:
    document = _pdf_document(
        [ParsedPage(text="First paragraph.\n\nSecond paragraph.", page_number=4)]
    )

    chunks = PDFPageAwareChunker(chunk_size=100, chunk_overlap=0).chunk(document)

    assert len(chunks) == 1
    assert chunks[0].text == "First paragraph.\n\nSecond paragraph."
    assert chunks[0].page == 4


def test_pdf_page_aware_chunker_splits_oversized_page_locally() -> None:
    document = _pdf_document(
        [ParsedPage(text="Long page sentence. " * 12, page_number=7)]
    )

    chunks = PDFPageAwareChunker(chunk_size=45, chunk_overlap=5).chunk(document)

    assert len(chunks) > 1
    assert all(len(chunk.text) <= 45 for chunk in chunks)
    assert all(chunk.page == 7 for chunk in chunks)


def test_pdf_page_aware_chunker_skips_blank_pages_without_renumbering() -> None:
    document = _pdf_document(
        [
            ParsedPage(text="Page one.", page_number=1),
            ParsedPage(text=" \n\n\t", page_number=2),
            ParsedPage(text="Page three.", page_number=3),
        ]
    )

    chunks = PDFPageAwareChunker(chunk_size=100, chunk_overlap=0).chunk(document)

    assert [chunk.page for chunk in chunks] == [1, 3]
    assert [chunk.chunk_index for chunk in chunks] == [0, 1]


def test_pdf_page_aware_chunker_handles_a_single_page() -> None:
    document = _pdf_document(
        [ParsedPage(text="Only page.\n\nFinal paragraph.", page_number=1)]
    )

    chunks = PDFPageAwareChunker(chunk_size=100, chunk_overlap=0).chunk(document)

    assert len(chunks) == 1
    assert chunks[0].page == 1
    assert chunks[0].section is None
    assert chunks[0].heading_path == []


def test_pdf_page_aware_chunks_never_mix_page_content() -> None:
    document = _pdf_document(
        [
            ParsedPage(text="PAGE_ONE_TOKEN " * 8, page_number=10),
            ParsedPage(text="PAGE_TWO_TOKEN " * 8, page_number=11),
        ]
    )

    chunks = PDFPageAwareChunker(chunk_size=35, chunk_overlap=5).chunk(document)

    assert all(
        (chunk.page == 10 and "PAGE_TWO_TOKEN" not in chunk.text)
        or (chunk.page == 11 and "PAGE_ONE_TOKEN" not in chunk.text)
        for chunk in chunks
    )


def test_pdf_page_aware_chunks_have_stable_hashes_ids_and_indexes() -> None:
    document = _pdf_document(
        [
            ParsedPage(text="Stable first page. " * 5, page_number=2),
            ParsedPage(text="Stable last page. " * 5, page_number=8),
        ]
    )
    chunker = PDFPageAwareChunker(chunk_size=45, chunk_overlap=5)

    first = chunker.chunk(document)
    second = chunker.chunk(document)

    assert [chunk.chunk_index for chunk in first] == list(range(len(first)))
    assert [chunk.chunk_id for chunk in first] == [
        chunk.chunk_id for chunk in second
    ]
    assert [chunk.content_hash for chunk in first] == [
        chunk.content_hash for chunk in second
    ]
    assert all(len(chunk.chunk_id) == 64 for chunk in first)
    assert all(
        chunk.content_hash == sha256(chunk.text.encode("utf-8")).hexdigest()
        for chunk in first
    )
