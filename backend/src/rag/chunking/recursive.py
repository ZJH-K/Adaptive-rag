"""Baseline recursive character chunker."""

from __future__ import annotations

import re
from hashlib import sha256

from src.rag.chunking.exceptions import ChunkerConfigurationError
from src.rag.schemas import Chunk, ParsedDocument


_PARAGRAPH_BOUNDARY = re.compile(r"\n[ \t]*\n")
_SENTENCE_BOUNDARY = re.compile(r"[.!?。！？]")
_EXCESS_PARAGRAPH_BREAKS = re.compile(r"\n(?:[ \t]*\n){2,}")


def _normalize_text(text: str) -> str:
    """Normalize line endings and redundant blank lines before chunking."""
    text = text.replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return _EXCESS_PARAGRAPH_BREAKS.sub("\n\n", text).strip()


def _sha256_text(text: str) -> str:
    """Return the SHA-256 hex digest of UTF-8 text."""
    return sha256(text.encode("utf-8")).hexdigest()


class RecursiveChunker:
    """Split parsed pages at paragraph, sentence, then character boundaries."""

    strategy = "recursive"

    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 100) -> None:
        """Configure maximum chunk length and trailing character overlap."""
        if not isinstance(chunk_size, int) or isinstance(chunk_size, bool):
            raise ChunkerConfigurationError("chunk_size must be an integer")
        if not isinstance(chunk_overlap, int) or isinstance(chunk_overlap, bool):
            raise ChunkerConfigurationError("chunk_overlap must be an integer")
        if chunk_size <= 0:
            raise ChunkerConfigurationError("chunk_size must be greater than zero")
        if chunk_overlap < 0:
            raise ChunkerConfigurationError(
                "chunk_overlap must be greater than or equal to zero"
            )
        if chunk_overlap >= chunk_size:
            raise ChunkerConfigurationError(
                "chunk_overlap must be smaller than chunk_size"
            )

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk(self, document: ParsedDocument) -> list[Chunk]:
        """Convert a parsed document into stable, page-scoped chunks."""
        chunks: list[Chunk] = []

        for page in document.pages:
            page_chunks = self.split_text(page.text)
            for text in page_chunks:
                chunk_index = len(chunks)
                content_hash = _sha256_text(text)
                chunks.append(
                    Chunk(
                        chunk_id=self._create_chunk_id(
                            document_id=document.document_id,
                            page=page.page_number,
                            chunk_index=chunk_index,
                            text=text,
                        ),
                        document_id=document.document_id,
                        text=text,
                        chunk_index=chunk_index,
                        source=document.filename,
                        source_type=document.source_type,
                        page=page.page_number,
                        section=None,
                        heading_path=[],
                        chunk_strategy=self.strategy,
                        content_hash=content_hash,
                    )
                )

        return chunks

    def split_text(self, text: str) -> list[str]:
        """Split text with the configured paragraph-to-character strategy."""
        return self._split_text(text)

    def _split_text(self, text: str) -> list[str]:
        """Split one page without allowing chunks to cross its boundary."""
        normalized = _normalize_text(text)
        if not normalized:
            return []
        if len(normalized) <= self.chunk_size:
            return [normalized]

        chunks: list[str] = []
        start = 0
        text_length = len(normalized)

        while start < text_length:
            maximum_end = min(start + self.chunk_size, text_length)
            if maximum_end == text_length:
                end = text_length
            else:
                end = self._find_boundary(normalized, start, maximum_end)

            chunk_text = normalized[start:end].strip()
            if chunk_text:
                chunks.append(chunk_text)

            if end >= text_length:
                break

            next_start = end - self.chunk_overlap
            while next_start < text_length and normalized[next_start].isspace():
                next_start += 1
            if next_start <= start:
                next_start = end
            start = next_start

        return chunks

    def _find_boundary(self, text: str, start: int, maximum_end: int) -> int:
        """Choose the latest useful paragraph or sentence boundary."""
        minimum_end = start + max(self.chunk_overlap + 1, self.chunk_size // 2)
        minimum_end = min(minimum_end, maximum_end)
        window = text[start:maximum_end]
        relative_minimum = minimum_end - start

        paragraph_ends = [
            match.end()
            for match in _PARAGRAPH_BOUNDARY.finditer(window)
            if match.end() >= relative_minimum
        ]
        if paragraph_ends:
            return start + paragraph_ends[-1]

        sentence_ends = [
            match.end()
            for match in _SENTENCE_BOUNDARY.finditer(window)
            if match.end() >= relative_minimum
        ]
        if sentence_ends:
            return start + sentence_ends[-1]

        return maximum_end

    def _create_chunk_id(
        self,
        *,
        document_id: str,
        page: int | None,
        chunk_index: int,
        text: str,
    ) -> str:
        """Create a deterministic ID from document, position, and content."""
        identity = "\x1f".join(
            (
                document_id,
                self.strategy,
                "" if page is None else str(page),
                str(chunk_index),
                text,
            )
        )
        return _sha256_text(identity)
