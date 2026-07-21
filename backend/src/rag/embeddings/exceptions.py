"""Exceptions raised by the embedding client."""


class EmbeddingError(RuntimeError):
    """Base class for embedding failures."""


class EmbeddingConfigurationError(EmbeddingError):
    """Raised when required embedding configuration is invalid or missing."""


class EmbeddingInputError(ValueError, EmbeddingError):
    """Raised when text supplied for embedding is invalid."""


class EmbeddingRequestError(EmbeddingError):
    """Raised when the remote embedding request fails."""


class EmbeddingResponseError(EmbeddingError):
    """Raised when an embedding response violates the expected contract."""

