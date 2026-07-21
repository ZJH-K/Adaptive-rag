"""Tests for Markdown/PDF parsers and parser selection."""

from pathlib import Path

import pymupdf
import pytest

from src.rag.parsers import (
    DocumentParseError,
    MarkdownParser,
    PDFParser,
    ParserFactory,
    UnsupportedDocumentTypeError,
    parse_document,
)


def _create_pdf(path: Path, page_texts: list[str | None]) -> None:
    document = pymupdf.open()
    try:
        for text in page_texts:
            page = document.new_page()
            if text is not None:
                page.insert_text((72, 72), text)
        document.save(path)
    finally:
        document.close()


def test_markdown_parser_normalizes_text_and_extracts_headings(
    tmp_path: Path,
) -> None:
    path = tmp_path / "guide.md"
    path.write_bytes(
        b"# Introduction\r\n\r\n\r\nBody\x00 text.\r\n## Usage ##\r\nDetails"
    )

    parsed = MarkdownParser().parse(path)

    assert parsed.source_type == "markdown"
    assert parsed.filename == "guide.md"
    assert len(parsed.pages) == 1
    assert parsed.pages[0].page_number is None
    assert parsed.pages[0].headings == ["Introduction", "Usage"]
    assert parsed.pages[0].text == (
        "# Introduction\n\nBody text.\n## Usage ##\nDetails"
    )


@pytest.mark.parametrize("extension", [".md", ".markdown", ".MARKDOWN"])
def test_factory_selects_markdown_extensions(
    tmp_path: Path, extension: str
) -> None:
    path = tmp_path / f"document{extension}"
    path.write_text("# Title", encoding="utf-8")

    assert isinstance(ParserFactory.get_parser(path), MarkdownParser)
    assert parse_document(path).source_type == "markdown"


def test_empty_markdown_raises_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "empty.md"
    path.write_bytes(b"")

    with pytest.raises(DocumentParseError, match="empty"):
        MarkdownParser().parse(path)


def test_markdown_with_only_unusable_text_raises_error(tmp_path: Path) -> None:
    path = tmp_path / "empty.md"
    path.write_bytes(b"\x00\r\n\r\n")

    with pytest.raises(DocumentParseError, match="no usable text"):
        MarkdownParser().parse(path)


def test_two_page_pdf_retains_one_based_page_numbers(tmp_path: Path) -> None:
    path = tmp_path / "guide.pdf"
    _create_pdf(path, ["First page", "Second page"])

    parsed = PDFParser().parse(path)

    assert parsed.source_type == "pdf"
    assert parsed.filename == "guide.pdf"
    assert parsed.metadata == {"total_pages": 2}
    assert [page.page_number for page in parsed.pages] == [1, 2]
    assert [page.text for page in parsed.pages] == ["First page", "Second page"]


def test_pdf_retains_original_number_when_blank_page_is_skipped(
    tmp_path: Path,
) -> None:
    path = tmp_path / "partially-blank.pdf"
    _create_pdf(path, [None, "Text on page two"])

    parsed = PDFParser().parse(path)

    assert len(parsed.pages) == 1
    assert parsed.pages[0].page_number == 2


def test_pdf_without_extractable_text_raises_error(tmp_path: Path) -> None:
    path = tmp_path / "image-only.pdf"
    _create_pdf(path, [None, None])

    with pytest.raises(DocumentParseError, match="no extractable text"):
        PDFParser().parse(path)


def test_factory_rejects_unsupported_extension(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("text", encoding="utf-8")

    with pytest.raises(UnsupportedDocumentTypeError, match=r"\.txt"):
        ParserFactory.get_parser(path)


@pytest.mark.parametrize(
    ("filename", "content"),
    [("guide.md", b"# Same content"), ("guide.markdown", b"# Same content")],
)
def test_document_id_is_stable_for_same_markdown_content(
    tmp_path: Path, filename: str, content: bytes
) -> None:
    first_path = tmp_path / filename
    second_path = tmp_path / f"copy-{filename}"
    first_path.write_bytes(content)
    second_path.write_bytes(content)

    first = MarkdownParser().parse(first_path)
    second = MarkdownParser().parse(second_path)

    assert first.document_id == second.document_id
    assert len(first.document_id) == 64


def test_document_id_is_stable_for_same_pdf_content(tmp_path: Path) -> None:
    first_path = tmp_path / "guide.pdf"
    second_path = tmp_path / "copy.pdf"
    _create_pdf(first_path, ["Stable content"])
    second_path.write_bytes(first_path.read_bytes())

    first = PDFParser().parse(first_path)
    second = PDFParser().parse(second_path)

    assert first.document_id == second.document_id

