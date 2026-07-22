"""Project-level exceptions raised by LLM clients."""


class LLMError(RuntimeError):
    """Base class for language-model failures."""


class LLMConfigurationError(LLMError):
    """Raised when required LLM configuration is invalid or missing."""


class LLMInputError(ValueError, LLMError):
    """Raised when chat messages violate the client input contract."""


class LLMRequestError(LLMError):
    """Raised when the upstream LLM request fails."""


class LLMTimeoutError(LLMRequestError):
    """Raised when the upstream LLM request times out."""


class LLMResponseError(LLMError):
    """Raised when an upstream response has no usable assistant text."""
