"""Parser selection by document extension."""

from __future__ import annotations

from pathlib import Path

from src.rag.parsers.base import DocumentParser
from src.rag.parsers.exceptions import UnsupportedDocumentTypeError
from src.rag.parsers.markdown import MarkdownParser
from src.rag.parsers.pdf import PDFParser
from src.rag.schemas import ParsedDocument


class ParserFactory:
    """Select the parser registered for a document's file extension."""

    _parsers: tuple[DocumentParser, ...] = (MarkdownParser(), PDFParser())

    @classmethod
    def get_parser(cls, file_path: str | Path) -> DocumentParser:
        """Return the matching parser or raise an explicit type error."""
        suffix = Path(file_path).suffix.lower()
        for parser in cls._parsers:
            if suffix in parser.supported_extensions:
                return parser

        display_suffix = suffix or "<none>"
        raise UnsupportedDocumentTypeError(
            f"Unsupported document extension: {display_suffix}"
        )

    @classmethod
    def parse(cls, file_path: str | Path) -> ParsedDocument:
        """Select a parser and parse the supplied document."""
        return cls.get_parser(file_path).parse(file_path)


def get_parser(file_path: str | Path) -> DocumentParser:
    """Return the parser selected for ``file_path``."""
    return ParserFactory.get_parser(file_path)


def parse_document(file_path: str | Path) -> ParsedDocument:
    """Parse a supported document using the factory-selected parser."""
    return ParserFactory.parse(file_path)

