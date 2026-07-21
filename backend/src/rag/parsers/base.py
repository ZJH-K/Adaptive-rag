"""Common parser protocol and file helpers."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Protocol

from src.rag.parsers.exceptions import DocumentParseError
from src.rag.schemas import ParsedDocument


class DocumentParser(Protocol):
    """Protocol implemented by document-format parsers."""

    supported_extensions: frozenset[str]

    def parse(self, file_path: str | Path) -> ParsedDocument:
        """Parse a file into the shared document representation."""
        ...


def read_document_bytes(file_path: str | Path) -> tuple[Path, bytes]:
    """Read a document and raise a parser-specific error on failure."""
    path = Path(file_path)
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise DocumentParseError(f"Unable to read document '{path}': {exc}") from exc

    if not content:
        raise DocumentParseError(f"Document '{path}' is empty")
    return path, content


def create_document_id(content: bytes) -> str:
    """Return a stable SHA-256 identifier for exact document content."""
    return sha256(content).hexdigest()

