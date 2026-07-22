"""Documents application service backed by the shared retrieval runtime."""

from __future__ import annotations

import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, cast

from src.api.errors import APIError
from src.api.models import (
    BM25Health,
    ChromaHealth,
    DocumentStatsResponse,
    DocumentUploadResponse,
    LoadDefaultItem,
    LoadDefaultRequest,
    LoadDefaultResponse,
)
from src.config import Settings
from src.rag.chunking.exceptions import (
    IncompatibleChunkingStrategyError,
    UnsupportedChunkingStrategyError,
)
from src.rag.chunking.factory import ChunkingStrategy
from src.rag.embeddings.exceptions import EmbeddingError
from src.rag.ingestion import IngestionError, IngestionResult
from src.rag.parsers.base import create_document_id
from src.rag.parsers.exceptions import DocumentParseError
from src.rag.runtime import RetrievalRuntime
from src.rag.vectorstore.exceptions import VectorStoreError


logger = logging.getLogger(__name__)
DocumentStatus = Literal["done", "degraded"]
_SUPPORTED_EXTENSIONS = frozenset({".pdf", ".md", ".markdown"})
_STRATEGIES = frozenset({"recursive", "markdown_heading", "pdf_page_aware"})
_MIME_TYPES = {
    ".pdf": frozenset({"application/pdf"}),
    ".md": frozenset({"text/markdown", "text/plain", "text/x-markdown"}),
    ".markdown": frozenset({"text/markdown", "text/plain", "text/x-markdown"}),
}
_GENERIC_MIME_TYPES = frozenset({"", "application/octet-stream"})


class DocumentService:
    """Validate and ingest documents through one lifespan-owned runtime."""

    def __init__(self, settings: Settings, runtime: RetrievalRuntime) -> None:
        self.settings = settings
        self.runtime = runtime

    @property
    def max_upload_bytes(self) -> int:
        """Return the configured bounded upload size."""
        return self.settings.upload_max_bytes

    @property
    def knowledge_base_id(self) -> str:
        """Return the only knowledge base accepted by the MVP API."""
        return self.settings.knowledge_base_id

    def ingest_bytes(
        self,
        *,
        filename: str,
        content_type: str | None,
        content: bytes,
        knowledge_base_id: str,
        chunk_strategy: str,
    ) -> DocumentUploadResponse:
        """Validate bytes, ingest via the shared pipeline, and verify BM25."""
        self._validate_knowledge_base(knowledge_base_id)
        safe_name, suffix = self._validate_file(filename, content_type, content)
        strategy = self._validate_strategy(chunk_strategy, suffix)
        document_id = create_document_id(content)

        try:
            existing = [
                chunk
                for chunk in self.runtime.vector_store.get_chunks_by_document_id(
                    document_id
                )
                if chunk.chunk_strategy == strategy
            ]
        except VectorStoreError as exc:
            raise self._error(
                "vector_store_failed", "The document store is unavailable.", 503
            ) from exc
        if existing:
            return self._duplicate_response(
                document_id=document_id,
                filename=safe_name,
                chunks_count=len(existing),
            )

        temp_root = self.settings.upload_temp_dir
        try:
            if temp_root is not None:
                temp_root.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(
                prefix="adaptive-rag-upload-",
                dir=temp_root,
            ) as directory:
                path = Path(directory) / safe_name
                path.write_bytes(content)
                try:
                    result = self.runtime.ingestion_pipeline.ingest(path, strategy)
                except Exception as exc:
                    self._raise_ingestion_error(exc)
                    raise AssertionError("unreachable")
        except APIError:
            raise
        except OSError as exc:
            raise self._error(
                "temporary_file_failed",
                "The uploaded document could not be processed.",
                500,
            ) from exc
        return self._response_from_result(result)

    def load_default(
        self,
        request: LoadDefaultRequest | None = None,
    ) -> LoadDefaultResponse:
        """Idempotently load supported files from configured corpus folders."""
        options = request or LoadDefaultRequest()
        knowledge_base_id = (
            self.settings.knowledge_base_id
            if options.knowledge_base_id is None
            else options.knowledge_base_id
        )
        self._validate_knowledge_base(knowledge_base_id)
        paths = self._default_paths()
        items: list[LoadDefaultItem] = []
        processed = skipped = failed = chunks_count = 0

        for path in paths:
            strategy = (
                self._automatic_strategy(path.suffix.lower())
                if options.chunk_strategy == "auto"
                else options.chunk_strategy
            )
            try:
                result = self.ingest_bytes(
                    filename=path.name,
                    content_type=None,
                    content=path.read_bytes(),
                    knowledge_base_id=knowledge_base_id,
                    chunk_strategy=strategy,
                )
                if result.duplicate:
                    skipped += 1
                    item_status = "skipped"
                else:
                    processed += 1
                    chunks_count += result.chunks_count
                    item_status = result.status
                items.append(
                    LoadDefaultItem(
                        filename=path.name,
                        status=item_status,
                        chunks_count=result.chunks_count,
                        document_id=result.document_id,
                        error_code=result.error_code,
                    )
                )
            except APIError as exc:
                failed += 1
                items.append(
                    LoadDefaultItem(
                        filename=path.name,
                        status="failed",
                        error_code=exc.code,
                    )
                )
            except Exception:
                failed += 1
                logger.exception("Unexpected built-in document ingestion failure")
                items.append(
                    LoadDefaultItem(
                        filename=path.name,
                        status="failed",
                        error_code="ingestion_failed",
                    )
                )

        degraded_items = any(item.status == "degraded" for item in items)
        if failed == len(items):
            batch_status: Literal["done", "degraded", "failed"] = "failed"
        elif failed or degraded_items:
            batch_status = "degraded"
        else:
            batch_status = "done"
        return LoadDefaultResponse(
            status=batch_status,
            knowledge_base_id=knowledge_base_id,
            processed=processed,
            skipped=skipped,
            failed=failed,
            chunks_count=chunks_count,
            items=items,
        )

    def stats(self) -> DocumentStatsResponse:
        """Read counts from Chroma and consistency state from BM25."""
        try:
            chunks, index = self.runtime.get_corpus_snapshot()
            chunks_count = len(chunks)
        except Exception as exc:
            raise self._error(
                "document_stats_unavailable",
                "Document statistics are temporarily unavailable.",
                503,
            ) from exc
        bm25_status = (
            "rebuilding" if index.is_rebuilding
            else "degraded" if index.needs_rebuild
            else "ready"
        )
        return DocumentStatsResponse(
            knowledge_base_id=self.settings.knowledge_base_id,
            documents_count=len({chunk.document_id for chunk in chunks}),
            chunks_count=chunks_count,
            chroma=ChromaHealth(status="ready", chunk_count=chunks_count),
            bm25=BM25Health(
                status=bm25_status,
                generation=index.generation,
                chunk_count=index.chunk_count,
                needs_rebuild=index.needs_rebuild,
                last_successful_rebuild_at=(
                    index.last_successful_rebuild_at.isoformat()
                    if index.last_successful_rebuild_at is not None
                    else None
                ),
                last_error_code=index.last_failure_code,
            ),
        )

    def _duplicate_response(
        self,
        *,
        document_id: str,
        filename: str,
        chunks_count: int,
    ) -> DocumentUploadResponse:
        index = self.runtime.get_index_status()
        try:
            chunks, index = self.runtime.get_corpus_snapshot()
            store_count = len(chunks)
            if index.needs_rebuild or index.chunk_count != store_count:
                index = self.runtime.rebuild_from_store()
        except Exception:
            logger.exception("BM25 recovery failed for a duplicate document")
            return DocumentUploadResponse(
                document_id=document_id,
                filename=filename,
                chunks_count=chunks_count,
                status="degraded",
                duplicate=True,
                bm25_generation=index.generation,
                error_code="bm25_rebuild_failed",
            )
        return DocumentUploadResponse(
            document_id=document_id,
            filename=filename,
            chunks_count=chunks_count,
            status="done",
            duplicate=True,
            bm25_generation=index.generation,
        )

    def _response_from_result(
        self,
        result: IngestionResult,
    ) -> DocumentUploadResponse:
        try:
            chunks, index = self.runtime.get_corpus_snapshot()
        except Exception:
            logger.exception("Post-ingestion consistency verification failed")
            index = result.index_status or self.runtime.get_index_status()
            return DocumentUploadResponse(
                document_id=result.document_id,
                filename=result.filename,
                chunks_count=result.chunks_count,
                status="degraded",
                bm25_generation=index.generation,
                error_code=result.error_code or "index_verification_failed",
            )
        consistent = (
            result.status == "done"
            and not index.needs_rebuild
            and index.chunk_count == len(chunks)
        )
        response_status: DocumentStatus = "done" if consistent else "degraded"
        error_code = None if consistent else (result.error_code or "index_inconsistent")
        return DocumentUploadResponse(
            document_id=result.document_id,
            filename=result.filename,
            chunks_count=result.chunks_count,
            status=response_status,
            bm25_generation=index.generation,
            error_code=error_code,
        )

    def _validate_knowledge_base(self, value: str) -> None:
        if value != self.settings.knowledge_base_id:
            raise self._error(
                "invalid_knowledge_base",
                "Only the configured knowledge base is supported.",
                400,
            )

    def _validate_file(
        self,
        filename: str,
        content_type: str | None,
        content: bytes,
    ) -> tuple[str, str]:
        safe_name = Path(filename.replace("\\", "/")).name.strip()
        if not safe_name or safe_name in {".", ".."} or any(
            ord(character) < 32 for character in safe_name
        ):
            raise self._error("invalid_filename", "The filename is invalid.", 400)
        suffix = Path(safe_name).suffix.lower()
        if suffix not in _SUPPORTED_EXTENSIONS:
            raise self._error(
                "unsupported_file_type",
                "Only PDF and Markdown documents are supported.",
                415,
            )
        if not content:
            raise self._error("empty_file", "The uploaded file is empty.", 400)
        if len(content) > self.settings.upload_max_bytes:
            raise self._error(
                "file_too_large",
                "The uploaded file exceeds the configured size limit.",
                413,
            )
        normalized_mime = (content_type or "").split(";", 1)[0].strip().lower()
        if (
            normalized_mime not in _GENERIC_MIME_TYPES
            and normalized_mime not in _MIME_TYPES[suffix]
        ):
            raise self._error(
                "unsupported_media_type",
                "The file media type does not match its extension.",
                415,
            )
        if suffix == ".pdf" and b"%PDF-" not in content[:1024]:
            raise self._error(
                "invalid_pdf", "The uploaded file is not a valid PDF.", 422
            )
        return safe_name, suffix

    def _validate_strategy(self, strategy: str, suffix: str) -> ChunkingStrategy:
        normalized = strategy.strip().lower()
        if normalized not in _STRATEGIES:
            raise self._error(
                "unsupported_chunk_strategy",
                "The requested chunk strategy is not supported.",
                400,
            )
        source_type = "pdf" if suffix == ".pdf" else "markdown"
        incompatible = (
            normalized == "markdown_heading" and source_type != "markdown"
        ) or (normalized == "pdf_page_aware" and source_type != "pdf")
        if incompatible:
            raise self._error(
                "incompatible_chunk_strategy",
                "The chunk strategy is incompatible with the document type.",
                400,
            )
        return cast(ChunkingStrategy, normalized)

    def _default_paths(self) -> list[Path]:
        root = self.settings.knowledge_root
        if not root.is_dir():
            raise self._error(
                "knowledge_directory_missing",
                "The built-in knowledge directory is unavailable.",
                404,
            )
        directories = [root / "markdown", root / "pdf"]
        paths = sorted(
            path
            for directory in directories
            if directory.is_dir()
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in _SUPPORTED_EXTENSIONS
        )
        if not paths:
            raise self._error(
                "knowledge_directory_empty",
                "The built-in knowledge directory has no supported documents.",
                404,
            )
        return paths

    @staticmethod
    def _automatic_strategy(suffix: str) -> ChunkingStrategy:
        return "pdf_page_aware" if suffix == ".pdf" else "markdown_heading"

    def _raise_ingestion_error(self, exc: Exception) -> None:
        if isinstance(exc, UnsupportedChunkingStrategyError):
            raise self._error(
                "unsupported_chunk_strategy",
                "The requested chunk strategy is not supported.",
                400,
            ) from exc
        if isinstance(exc, IncompatibleChunkingStrategyError):
            raise self._error(
                "incompatible_chunk_strategy",
                "The chunk strategy is incompatible with the document type.",
                400,
            ) from exc
        if isinstance(exc, DocumentParseError):
            no_text = "no extractable text" in str(exc)
            raise self._error(
                "document_no_text" if no_text else "document_parse_failed",
                "The document does not contain usable text."
                if no_text
                else "The document could not be parsed.",
                422,
            ) from exc
        if isinstance(exc, EmbeddingError):
            raise self._error(
                "embedding_failed",
                "Document embeddings could not be generated.",
                502,
            ) from exc
        if isinstance(exc, VectorStoreError):
            raise self._error(
                "vector_store_failed", "The document store is unavailable.", 503
            ) from exc
        if isinstance(exc, IngestionError):
            raise self._error(
                "document_has_no_chunks",
                "The document did not produce any searchable content.",
                422,
            ) from exc
        raise exc

    @staticmethod
    def _error(code: str, message: str, status_code: int) -> APIError:
        return APIError(code, message, status_code=status_code)
