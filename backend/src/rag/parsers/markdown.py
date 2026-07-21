"""Parser for UTF-8 Markdown documents."""

from __future__ import annotations

import re
from pathlib import Path

from src.rag.parsers.base import create_document_id, read_document_bytes
from src.rag.parsers.exceptions import DocumentParseError
from src.rag.schemas import ParsedDocument, ParsedPage


_HEADING_PATTERN = re.compile(
    r"^\s{0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE
)
_EXCESS_NEWLINES_PATTERN = re.compile(r"\n(?:[ \t]*\n){2,}")


def _normalize_markdown(text: str) -> str:
    """Remove invalid nulls and normalize line and paragraph breaks."""
    text = text.lstrip("\ufeff").replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return _EXCESS_NEWLINES_PATTERN.sub("\n\n", text).strip()


def _extract_headings(text: str) -> list[str]:
    """Extract ATX heading text in document order."""
    return [match.group(1).strip() for match in _HEADING_PATTERN.finditer(text)]


class MarkdownParser:
    """Parse a Markdown file into one logical, heading-aware page."""

    supported_extensions = frozenset({".md", ".markdown"})

    def parse(self, file_path: str | Path) -> ParsedDocument:
        """Parse a UTF-8 Markdown file while preserving its body syntax."""
        path, content = read_document_bytes(file_path)
        try:
            decoded = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DocumentParseError(
                f"Markdown document '{path}' is not valid UTF-8"
            ) from exc

        text = _normalize_markdown(decoded)
        if not text:
            raise DocumentParseError(
                f"Markdown document '{path}' contains no usable text"
            )

        return ParsedDocument(
            document_id=create_document_id(content),
            filename=path.name,
            source_type="markdown",
            pages=[ParsedPage(text=text, headings=_extract_headings(text))],
        )

