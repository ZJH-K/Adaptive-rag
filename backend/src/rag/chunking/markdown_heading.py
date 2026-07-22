"""Heading-aware chunking for Markdown technical documents."""

from __future__ import annotations

import re
from hashlib import sha256
from typing import Iterator

from src.rag.chunking.recursive import RecursiveChunker
from src.rag.schemas import Chunk, ParsedDocument


_HEADING_PATTERN = re.compile(
    r"^ {0,3}(#{1,3})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$"
)


def _sha256_text(text: str) -> str:
    """Return the SHA-256 hex digest of UTF-8 text."""
    return sha256(text.encode("utf-8")).hexdigest()


class MarkdownHeadingChunker:
    """Split Markdown within heading boundaries while retaining its hierarchy.

    Heading lines define metadata and are intentionally omitted from chunk text.
    Body text is split by the baseline recursive strategy, so oversized sections
    retain safe paragraph, sentence, and character fallbacks.
    """

    strategy = "markdown_heading"

    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 100) -> None:
        """Configure target chunk length and overlap for oversized sections."""
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._text_splitter = RecursiveChunker(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    def chunk(self, document: ParsedDocument) -> list[Chunk]:
        """Convert a parsed Markdown document into stable heading-aware chunks."""
        chunks: list[Chunk] = []

        for page in document.pages:
            for heading_path, section_text in self._iter_sections(page.text):
                for text in self._text_splitter.split_text(section_text):
                    chunk_index = len(chunks)
                    chunks.append(
                        Chunk(
                            chunk_id=self._create_chunk_id(
                                document_id=document.document_id,
                                page=page.page_number,
                                chunk_index=chunk_index,
                                heading_path=heading_path,
                                text=text,
                            ),
                            document_id=document.document_id,
                            text=text,
                            chunk_index=chunk_index,
                            source=document.filename,
                            source_type=document.source_type,
                            page=page.page_number,
                            section=heading_path[-1] if heading_path else None,
                            heading_path=heading_path,
                            chunk_strategy=self.strategy,
                            content_hash=_sha256_text(text),
                        )
                    )

        return chunks

    def _iter_sections(self, text: str) -> Iterator[tuple[list[str], str]]:
        """Yield body regions paired with a snapshot of their heading path."""
        heading_path: list[str] = []
        body_lines: list[str] = []

        for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines(
            keepends=True
        ):
            heading = _HEADING_PATTERN.match(line.rstrip("\n"))
            if heading is None:
                body_lines.append(line)
                continue

            if body_lines:
                yield heading_path.copy(), "".join(body_lines)
                body_lines.clear()

            level = len(heading.group(1))
            title = heading.group(2).strip()
            heading_path = heading_path[: level - 1]
            heading_path.append(title)

        if body_lines:
            yield heading_path.copy(), "".join(body_lines)

    def _create_chunk_id(
        self,
        *,
        document_id: str,
        page: int | None,
        chunk_index: int,
        heading_path: list[str],
        text: str,
    ) -> str:
        """Create a deterministic ID from document, position, metadata, and text."""
        identity = "\x1f".join(
            (
                document_id,
                self.strategy,
                "" if page is None else str(page),
                str(chunk_index),
                "\x1e".join(heading_path),
                text,
            )
        )
        return _sha256_text(identity)
