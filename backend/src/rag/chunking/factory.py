"""Factory for configured document chunking strategies."""

from __future__ import annotations

from typing import Literal, cast

from src.rag.chunking.exceptions import (
    IncompatibleChunkingStrategyError,
    UnsupportedChunkingStrategyError,
)
from src.rag.chunking.markdown_heading import MarkdownHeadingChunker
from src.rag.chunking.pdf_page_aware import PDFPageAwareChunker
from src.rag.chunking.recursive import RecursiveChunker
from src.rag.schemas import SourceType


ChunkingStrategy = Literal["recursive", "markdown_heading", "pdf_page_aware"]
Chunker = RecursiveChunker | MarkdownHeadingChunker | PDFPageAwareChunker
ChunkerType = (
    type[RecursiveChunker]
    | type[MarkdownHeadingChunker]
    | type[PDFPageAwareChunker]
)
DEFAULT_CHUNKING_STRATEGY: ChunkingStrategy = "recursive"

_CHUNKER_TYPES: dict[ChunkingStrategy, ChunkerType] = {
    "recursive": RecursiveChunker,
    "markdown_heading": MarkdownHeadingChunker,
    "pdf_page_aware": PDFPageAwareChunker,
}
_COMPATIBLE_SOURCE_TYPES: dict[ChunkingStrategy, frozenset[SourceType]] = {
    "recursive": frozenset({"markdown", "pdf"}),
    "markdown_heading": frozenset({"markdown"}),
    "pdf_page_aware": frozenset({"pdf"}),
}


class ChunkerFactory:
    """Create the chunker registered for a strategy name."""

    @staticmethod
    def create(
        strategy: str = DEFAULT_CHUNKING_STRATEGY,
        *,
        source_type: SourceType | None = None,
        chunk_size: int = 800,
        chunk_overlap: int = 100,
    ) -> Chunker:
        """Create a configured chunker after optional type compatibility checks."""
        normalized_strategy = strategy.strip().lower()
        if normalized_strategy not in _CHUNKER_TYPES:
            raise UnsupportedChunkingStrategyError(
                f"Unsupported chunking strategy '{strategy}'; expected one of: "
                f"{', '.join(_CHUNKER_TYPES)}"
            )
        controlled_strategy = cast(ChunkingStrategy, normalized_strategy)
        if (
            source_type is not None
            and source_type not in _COMPATIBLE_SOURCE_TYPES[controlled_strategy]
        ):
            raise IncompatibleChunkingStrategyError(
                f"Chunking strategy '{controlled_strategy}' is incompatible "
                f"with document type '{source_type}'"
            )

        chunker_type = _CHUNKER_TYPES[controlled_strategy]
        return chunker_type(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )


def get_chunker(
    strategy: str = DEFAULT_CHUNKING_STRATEGY,
    *,
    source_type: SourceType | None = None,
    chunk_size: int = 800,
    chunk_overlap: int = 100,
) -> Chunker:
    """Return a configured chunker for ``strategy``."""
    return ChunkerFactory.create(
        strategy,
        source_type=source_type,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
