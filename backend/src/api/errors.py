"""Known API failures with safe public representations."""

from fastapi import status


class APIError(RuntimeError):
    """A known API failure with a safe public representation."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.status_code = status_code


class ServiceUnavailableError(APIError):
    """A required lifespan-owned service is not available."""

    def __init__(
        self,
        code: str = "service_unavailable",
        message: str = "The requested service is temporarily unavailable.",
    ) -> None:
        super().__init__(
            code,
            message,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
