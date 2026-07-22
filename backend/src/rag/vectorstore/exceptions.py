"""Exceptions raised by vector store adapters."""


class VectorStoreError(RuntimeError):
    """Base class for vector store failures."""


class VectorStoreConfigurationError(VectorStoreError):
    """Raised when vector store configuration is invalid."""


class VectorStoreInputError(ValueError, VectorStoreError):
    """Raised when supplied chunks or vectors violate the input contract."""


class VectorStoreResponseError(VectorStoreError):
    """Raised when stored data cannot be reconstructed safely."""
