"""Stable, secret-free exception contracts for retrieval failures."""

from __future__ import annotations

from typing import Literal


RetrievalPath = Literal["dense", "bm25", "vector_store", "hybrid"]


class RetrievalError(RuntimeError):
    """Base exception carrying fields safe for workflow and API consumers."""

    code: str
    path: RetrievalPath
    recoverable: bool
    safe_message: str

    def __init__(
        self,
        *,
        code: str,
        path: RetrievalPath,
        recoverable: bool,
        safe_message: str,
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.path = path
        self.recoverable = recoverable
        self.safe_message = safe_message


class RetrievalPathUnavailableError(RetrievalError):
    """A known runtime failure for which another retrieval path may be used."""

    def __init__(
        self,
        *,
        code: str,
        path: Literal["dense", "bm25", "vector_store"],
        safe_message: str,
    ) -> None:
        super().__init__(
            code=code,
            path=path,
            recoverable=True,
            safe_message=safe_message,
        )


class DenseRetrievalUnavailableError(RetrievalPathUnavailableError):
    """The dense/embedding retrieval path is temporarily unavailable."""

    def __init__(
        self,
        *,
        code: str = "dense_retrieval_unavailable",
        safe_message: str = "Dense retrieval is temporarily unavailable.",
    ) -> None:
        super().__init__(code=code, path="dense", safe_message=safe_message)


class BM25RetrievalUnavailableError(RetrievalPathUnavailableError):
    """The BM25 index or tokenizer path is temporarily unavailable."""

    def __init__(
        self,
        *,
        code: str = "bm25_retrieval_unavailable",
        safe_message: str = "BM25 retrieval is temporarily unavailable.",
    ) -> None:
        super().__init__(code=code, path="bm25", safe_message=safe_message)


class VectorStoreUnavailableError(RetrievalPathUnavailableError):
    """The vector-store service is temporarily unavailable."""

    def __init__(
        self,
        *,
        code: str = "vector_store_unavailable",
        safe_message: str = "Vector store is temporarily unavailable.",
    ) -> None:
        super().__init__(code=code, path="vector_store", safe_message=safe_message)


class RetrievalUnavailableError(RetrievalError):
    """All configured paths failed, so this request cannot continue."""

    def __init__(self) -> None:
        super().__init__(
            code="retrieval_unavailable",
            path="hybrid",
            recoverable=True,
            safe_message="Document retrieval is temporarily unavailable.",
        )


class RetrievalContractError(RetrievalError):
    """An invalid retrieval datum or response that must never be degraded."""

    def __init__(
        self,
        *,
        code: str = "retrieval_contract_invalid",
        path: RetrievalPath = "hybrid",
        safe_message: str = "Retrieval data violated its contract.",
    ) -> None:
        super().__init__(
            code=code,
            path=path,
            recoverable=False,
            safe_message=safe_message,
        )
