"""Factory for configured document chunking strategies."""

from __future__ import annotations

from src.rag.chunking.exceptions import UnsupportedChunkingStrategyError
from src.rag.chunking.recursive import RecursiveChunker


class ChunkerFactory:
    """Create the chunker registered for a strategy name."""

    @staticmethod
    def create(
        strategy: str = "recursive",
        *,
        chunk_size: int = 800,
        chunk_overlap: int = 100,
    ) -> RecursiveChunker:
        """Create a configured chunker or reject an unknown strategy."""
        normalized_strategy = strategy.strip().lower()
        if normalized_strategy != "recursive":
            raise UnsupportedChunkingStrategyError(
                f"Unsupported chunking strategy: {strategy}"
            )
        return RecursiveChunker(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )


def get_chunker(
    strategy: str = "recursive",
    *,
    chunk_size: int = 800,
    chunk_overlap: int = 100,
) -> RecursiveChunker:
    """Return a configured chunker for ``strategy``."""
    return ChunkerFactory.create(
        strategy,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

