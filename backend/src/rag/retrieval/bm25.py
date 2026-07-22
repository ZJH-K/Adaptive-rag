"""Keyword retrieval over a prebuilt in-memory BM25 index."""

from __future__ import annotations

from src.rag.retrieval.bm25_index import BM25Index
from src.rag.schemas import Chunk, SearchHit


class BM25RetrievalConfigurationError(ValueError):
    """Raised when BM25 retrieval parameters are invalid."""


class BM25RetrievalInputError(ValueError):
    """Raised when a BM25 query has an invalid runtime type."""


class BM25Retriever:
    """Return non-zero SearchHits ordered by raw BM25 relevance."""

    def __init__(self, index: BM25Index, *, top_n: int = 20) -> None:
        """Configure a fixed maximum result count for one shared index."""
        if not isinstance(top_n, int) or isinstance(top_n, bool) or top_n <= 0:
            raise BM25RetrievalConfigurationError(
                "BM25Retriever top_n must be a positive integer"
            )
        self.index = index
        self.top_n = top_n

    def retrieve(self, query: str) -> list[SearchHit]:
        """Return raw BM25 scores in descending order; higher is better."""
        if not isinstance(query, str):
            raise BM25RetrievalInputError("BM25 query must be a string")
        if not query.strip() or self.index.is_empty:
            return []

        query_tokens = self.index.tokenizer.tokenize(query)
        if not query_tokens:
            return []

        scores = self.index.get_scores(query_tokens)
        ranked_positions = sorted(
            (
                (position, score)
                for position, score in enumerate(scores)
                if score != 0.0
            ),
            key=lambda item: (-item[1], item[0]),
        )[: self.top_n]
        return [
            self._to_search_hit(self.index.get_chunk(position), score)
            for position, score in ranked_positions
        ]

    @staticmethod
    def _to_search_hit(chunk: Chunk, score: float) -> SearchHit:
        """Copy one Chunk into the shared retrieval result contract."""
        return SearchHit(
            chunk_id=chunk.chunk_id,
            text=chunk.text,
            metadata=chunk.model_dump(exclude={"chunk_id", "text"}),
            bm25_score=score,
        )
