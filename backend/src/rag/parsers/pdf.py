"""Page-preserving parser for born-digital PDF documents."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from src.rag.parsers.base import create_document_id, read_document_bytes
from src.rag.parsers.exceptions import DocumentParseError
from src.rag.schemas import ParsedDocument, ParsedPage


def _normalize_pdf_text(text: str) -> str:
    """Normalize extracted page text without reconstructing its layout."""
    return (
        text.replace("\x00", "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .strip()
    )


class PDFParser:
    """Extract text from each valid PDF page while retaining page numbers."""

    supported_extensions = frozenset({".pdf"})

    def parse(self, file_path: str | Path) -> ParsedDocument:
        """Parse a digital PDF into one ``ParsedPage`` per text-bearing page."""
        path, content = read_document_bytes(file_path)
        try:
            document = pymupdf.open(stream=content, filetype="pdf")
        except (pymupdf.FileDataError, RuntimeError, ValueError) as exc:
            raise DocumentParseError(f"Unable to open PDF document '{path}'") from exc

        pages: list[ParsedPage] = []
        try:
            total_pages = document.page_count
            for page_index, page in enumerate(document):
                text = _normalize_pdf_text(page.get_text("text") or "")
                if text:
                    pages.append(
                        ParsedPage(text=text, page_number=page_index + 1)
                    )
        except (RuntimeError, ValueError) as exc:
            raise DocumentParseError(
                f"Unable to extract text from PDF document '{path}'"
            ) from exc
        finally:
            document.close()

        if not pages:
            raise DocumentParseError(
                f"PDF document '{path}' contains no extractable text"
            )

        return ParsedDocument(
            document_id=create_document_id(content),
            filename=path.name,
            source_type="pdf",
            pages=pages,
            metadata={"total_pages": total_pages},
        )
