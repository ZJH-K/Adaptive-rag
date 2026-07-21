"""Exceptions raised by chunking strategies and their factory."""


class ChunkerConfigurationError(ValueError):
    """Raised when a chunker is configured with invalid size parameters."""


class UnsupportedChunkingStrategyError(ValueError):
    """Raised when the chunker factory receives an unknown strategy."""


class IncompatibleChunkingStrategyError(ValueError):
    """Raised when a chunking strategy cannot process a document type."""
