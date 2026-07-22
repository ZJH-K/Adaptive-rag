"""Public document chunking interface."""

from src.rag.chunking.exceptions import (
    ChunkerConfigurationError,
    IncompatibleChunkingStrategyError,
    UnsupportedChunkingStrategyError,
)
from src.rag.chunking.factory import (
    DEFAULT_CHUNKING_STRATEGY,
    Chunker,
    ChunkerFactory,
    ChunkingStrategy,
    get_chunker,
)
from src.rag.chunking.markdown_heading import MarkdownHeadingChunker
from src.rag.chunking.pdf_page_aware import PDFPageAwareChunker
from src.rag.chunking.recursive import RecursiveChunker

__all__ = [
    "ChunkerConfigurationError",
    "Chunker",
    "ChunkerFactory",
    "ChunkingStrategy",
    "DEFAULT_CHUNKING_STRATEGY",
    "IncompatibleChunkingStrategyError",
    "MarkdownHeadingChunker",
    "PDFPageAwareChunker",
    "RecursiveChunker",
    "UnsupportedChunkingStrategyError",
    "get_chunker",
]
