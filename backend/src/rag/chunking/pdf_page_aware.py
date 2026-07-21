"""Page-aware chunking for born-digital PDF documents."""

from __future__ import annotations

from hashlib import sha256

from src.rag.chunking.recursive import RecursiveChunker
from src.rag.schemas import Chunk, ParsedDocument


def _sha256_text(text: str) -> str:
    """Return the SHA-256 hex digest of UTF-8 text."""
    return sha256(text.encode("utf-8")).hexdigest()


class PDFPageAwareChunker:
    """Split each PDF page independently and preserve its parsed page number.

    Cross-page merging is intentionally unsupported: every output chunk belongs
    to exactly one ``ParsedPage`` and copies that page's number without inference.
    Within a page, the baseline recursive strategy prefers paragraph and sentence
    boundaries before falling back to a safe character split.
    """

    strategy = "pdf_page_aware"

    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 100) -> None:
        """Configure the maximum page-local chunk length and overlap."""
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._text_splitter = RecursiveChunker(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    def chunk(self, document: ParsedDocument) -> list[Chunk]:
        """Convert parsed PDF pages into deterministic page-scoped chunks."""
        chunks: list[Chunk] = []

        for page in document.pages:
            for text in self._text_splitter.split_text(page.text):
                chunk_index = len(chunks)
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
                        content_hash=_sha256_text(text),
                    )
                )

        return chunks

    def _create_chunk_id(
        self,
        *,
        document_id: str,
        page: int | None,
        chunk_index: int,
        text: str,
    ) -> str:
        """Create a deterministic ID from document, page, position, and text."""
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
