"""In-memory BM25 corpus construction with stable Chunk position mapping."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from threading import Lock

from rank_bm25 import BM25Okapi

from src.rag.retrieval.tokenizer import JiebaTokenizer, Tokenizer
from src.rag.schemas import Chunk


class DuplicateChunkIDError(ValueError):
    """Raised when a corpus contains more than one Chunk with the same ID."""


@dataclass(frozen=True, slots=True)
class BM25IndexSnapshot:
    """One immutable, internally consistent BM25 corpus generation."""

    chunks: tuple[Chunk, ...] = ()
    chunk_ids: tuple[str, ...] = ()
    tokenized_corpus: tuple[tuple[str, ...], ...] = ()
    model: BM25Okapi | None = None
    generation: int = 0
    is_built: bool = False

    @property
    def is_empty(self) -> bool:
        """Return whether this generation has no chunks."""
        return not self.chunks

    def get_chunk(self, position: int) -> Chunk:
        """Map one score position to the Chunk from this generation."""
        return self.chunks[position]

    def get_scores(self, query_tokens: Sequence[str]) -> list[float]:
        """Return scores aligned with this generation's corpus positions."""
        if self.model is None or not query_tokens:
            return [0.0] * len(self.chunks)
        return [float(score) for score in self.model.get_scores(query_tokens)]


class BM25Index:
    """Own a tokenized corpus, BM25 model, and stable source Chunk mapping."""

    FORMAT_VERSION = 1

    def __init__(self, tokenizer: Tokenizer | None = None) -> None:
        """Create an empty index with an injectable shared tokenizer."""
        self.tokenizer = tokenizer or JiebaTokenizer()
        self._snapshot = BM25IndexSnapshot()
        self._publish_lock = Lock()
        self._needs_rebuild = False

    @classmethod
    def from_chunks(
        cls,
        chunks: Sequence[Chunk],
        *,
        tokenizer: Tokenizer | None = None,
    ) -> BM25Index:
        """Build a new index from Chunks in their existing ranked order."""
        return cls(tokenizer=tokenizer).rebuild(chunks)

    def rebuild(self, chunks: Sequence[Chunk]) -> BM25Index:
        """Atomically replace the complete corpus and position mapping."""
        materialized = tuple(chunks)
        self._ensure_unique_chunk_ids(materialized)
        tokenized = tuple(
            tuple(self.tokenizer.tokenize(chunk.text)) for chunk in materialized
        )
        model = (
            BM25Okapi([list(tokens) for tokens in tokenized])
            if any(tokenized)
            else None
        )

        with self._publish_lock:
            self._snapshot = BM25IndexSnapshot(
                chunks=materialized,
                chunk_ids=tuple(chunk.chunk_id for chunk in materialized),
                tokenized_corpus=tokenized,
                model=model,
                generation=self._snapshot.generation + 1,
                is_built=True,
            )
            self._needs_rebuild = False
        return self

    def snapshot(self) -> BM25IndexSnapshot:
        """Capture one complete corpus generation for a query."""
        return self._snapshot

    def mark_needs_rebuild(self) -> None:
        """Mark the in-memory index stale after vector persistence changed."""
        with self._publish_lock:
            self._needs_rebuild = True

    @property
    def chunks(self) -> tuple[Chunk, ...]:
        """Return source Chunks in corpus-position order."""
        return self._snapshot.chunks

    @property
    def chunk_ids(self) -> tuple[str, ...]:
        """Return the stable Chunk ID mapped to every corpus position."""
        return self._snapshot.chunk_ids

    @property
    def tokenized_corpus(self) -> tuple[tuple[str, ...], ...]:
        """Return the immutable token sequence for every corpus position."""
        return self._snapshot.tokenized_corpus

    @property
    def generation(self) -> int:
        """Return the number of successful full index builds."""
        return self._snapshot.generation

    @property
    def is_built(self) -> bool:
        """Return whether rebuild has completed at least once."""
        return self._snapshot.is_built

    @property
    def is_empty(self) -> bool:
        """Return whether the current corpus contains no Chunks."""
        return self._snapshot.is_empty

    @property
    def needs_rebuild(self) -> bool:
        """Return whether persisted chunks may be newer than this index."""
        with self._publish_lock:
            return self._needs_rebuild

    def get_chunk(self, position: int) -> Chunk:
        """Map one BM25 corpus position back to its original Chunk."""
        return self._snapshot.get_chunk(position)

    def get_scores(self, query_tokens: Sequence[str]) -> list[float]:
        """Return scores aligned with corpus positions without ranking hits."""
        return self._snapshot.get_scores(query_tokens)

    def __len__(self) -> int:
        """Return the number of indexed corpus positions."""
        return len(self._snapshot.chunks)

    @staticmethod
    def _ensure_unique_chunk_ids(chunks: Sequence[Chunk]) -> None:
        """Reject ambiguous mappings before mutating current index state."""
        seen: set[str] = set()
        for chunk in chunks:
            if chunk.chunk_id in seen:
                raise DuplicateChunkIDError(
                    f"Duplicate chunk_id in BM25 corpus: {chunk.chunk_id}"
                )
            seen.add(chunk.chunk_id)
