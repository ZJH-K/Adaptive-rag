"""Tests for BM25 ranking and unified SearchHit output."""

from __future__ import annotations

import pytest

from src.rag.retrieval import (
    BM25Index,
    BM25RetrievalConfigurationError,
    BM25RetrievalInputError,
    BM25Retriever,
)
from src.rag.retrieval.tokenizer import JiebaTokenizer
from src.rag.schemas import Chunk, SearchHit, SourceType


class RecordingWhitespaceTokenizer:
    """Deterministic tokenizer that records indexing and query calls."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def tokenize(self, text: str) -> list[str]:
        """Record and split lowercase text on whitespace."""
        self.calls.append(text)
        return [token.casefold() for token in text.split() if token]


def _chunk(
    chunk_id: str,
    text: str,
    index: int,
    *,
    source: str = "guide.md",
    source_type: SourceType = "markdown",
    page: int | None = None,
    section: str | None = None,
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id="doc-1",
        text=text,
        chunk_index=index,
        source=source,
        source_type=source_type,
        page=page,
        section=section,
        heading_path=["API", section] if section else [],
        chunk_strategy="recursive",
        content_hash=f"hash-{chunk_id}",
    )


def _technical_chunks() -> list[Chunk]:
    return [
        _chunk("thread", "使用 thread_id 配置 checkpoint", 0),
        _chunk("chroma", "调用 Chroma similarity_search 返回结果", 1),
        _chunk("rrf", "RRF 用于融合多个排名", 2),
        _chunk("bge", "BAAI/bge-m3 生成文本向量", 3),
        _chunk("generic", "普通的技术文档说明", 4),
    ]


@pytest.mark.parametrize(
    ("query", "expected_chunk_id"),
    [
        ("thread_id", "thread"),
        ("similarity_search", "chroma"),
        ("RRF", "rrf"),
        ("BAAI/bge-m3", "bge"),
    ],
)
def test_exact_technical_terms_rank_the_matching_chunk_first(
    query: str,
    expected_chunk_id: str,
) -> None:
    index = BM25Index.from_chunks(
        _technical_chunks(), tokenizer=JiebaTokenizer()
    )

    hits = BM25Retriever(index).retrieve(query)

    assert hits
    assert hits[0].chunk_id == expected_chunk_id
    assert hits[0].bm25_score is not None
    assert hits[0].bm25_score > 0


def test_retriever_uses_the_same_tokenizer_as_the_index() -> None:
    tokenizer = RecordingWhitespaceTokenizer()
    index = BM25Index.from_chunks(
        [
            _chunk("match", "needle unique", 0),
            _chunk("other-a", "alpha", 1),
            _chunk("other-b", "beta", 2),
        ],
        tokenizer=tokenizer,
    )

    hits = BM25Retriever(index).retrieve("NEEDLE")

    assert tokenizer.calls == ["needle unique", "alpha", "beta", "NEEDLE"]
    assert [hit.chunk_id for hit in hits] == ["match"]


def test_search_hit_preserves_text_metadata_and_score_contract() -> None:
    chunk = _chunk(
        "pdf",
        "special_term configuration",
        7,
        source="manual.pdf",
        source_type="pdf",
        page=4,
        section="Configuration",
    )
    index = BM25Index.from_chunks(
        [
            chunk,
            _chunk("a", "alpha", 0),
            _chunk("b", "beta", 1),
        ],
        tokenizer=RecordingWhitespaceTokenizer(),
    )
    before = chunk.model_dump()

    hit = BM25Retriever(index, top_n=1).retrieve("special_term")[0]

    assert isinstance(hit, SearchHit)
    assert hit.chunk_id == "pdf"
    assert hit.text == "special_term configuration"
    assert hit.metadata == {
        "document_id": "doc-1",
        "chunk_index": 7,
        "source": "manual.pdf",
        "source_type": "pdf",
        "page": 4,
        "section": "Configuration",
        "heading_path": ["API", "Configuration"],
        "chunk_strategy": "recursive",
        "content_hash": "hash-pdf",
    }
    assert hit.bm25_score is not None
    assert hit.dense_score is None
    assert hit.fused_score is None
    assert hit.rerank_score is None
    assert chunk.model_dump() == before


def test_top_n_limits_results_and_larger_limit_is_safe() -> None:
    chunks = [
        _chunk(f"chunk-{index}", f"shared token{index}", index)
        for index in range(5)
    ]
    index = BM25Index.from_chunks(
        chunks, tokenizer=RecordingWhitespaceTokenizer()
    )

    limited = BM25Retriever(index, top_n=2).retrieve("shared")
    oversized = BM25Retriever(index, top_n=100).retrieve("shared")

    assert len(limited) == 2
    assert len(oversized) == len(chunks)


def test_equal_scores_keep_original_corpus_position_order() -> None:
    index = BM25Index.from_chunks(
        [
            _chunk("first", "tie alpha", 0),
            _chunk("second", "tie beta", 1),
            _chunk("third", "unrelated", 2),
            _chunk("fourth", "other", 3),
            _chunk("fifth", "content", 4),
        ],
        tokenizer=RecordingWhitespaceTokenizer(),
    )

    hits = BM25Retriever(index).retrieve("tie")

    assert [hit.chunk_id for hit in hits] == ["first", "second"]
    assert hits[0].bm25_score == pytest.approx(hits[1].bm25_score)


@pytest.mark.parametrize("query", ["", "   \n\t", "，。！？"])
def test_blank_or_tokenless_query_returns_empty(query: str) -> None:
    index = BM25Index.from_chunks(
        _technical_chunks(), tokenizer=JiebaTokenizer()
    )

    assert BM25Retriever(index).retrieve(query) == []


def test_empty_index_returns_empty_without_tokenizing_query() -> None:
    tokenizer = RecordingWhitespaceTokenizer()
    index = BM25Index.from_chunks([], tokenizer=tokenizer)

    assert BM25Retriever(index).retrieve("query") == []
    assert tokenizer.calls == []


def test_all_zero_scores_return_no_irrelevant_hits() -> None:
    index = BM25Index.from_chunks(
        [
            _chunk("a", "alpha", 0),
            _chunk("b", "beta", 1),
            _chunk("c", "gamma", 2),
        ],
        tokenizer=RecordingWhitespaceTokenizer(),
    )

    assert BM25Retriever(index).retrieve("missing") == []


def test_negative_raw_scores_are_preserved_for_matching_common_terms() -> None:
    index = BM25Index.from_chunks(
        [
            _chunk("first", "common", 0),
            _chunk("second", "common", 1),
        ],
        tokenizer=RecordingWhitespaceTokenizer(),
    )

    hits = BM25Retriever(index).retrieve("common")

    assert [hit.chunk_id for hit in hits] == ["first", "second"]
    assert all(
        hit.bm25_score is not None and hit.bm25_score < 0 for hit in hits
    )


@pytest.mark.parametrize("top_n", [0, -1, 1.5, True])
def test_invalid_top_n_is_rejected(top_n: int) -> None:
    with pytest.raises(BM25RetrievalConfigurationError, match="top_n"):
        BM25Retriever(  # type: ignore[arg-type]
            BM25Index(tokenizer=RecordingWhitespaceTokenizer()),
            top_n=top_n,
        )


def test_non_string_query_is_rejected() -> None:
    retriever = BM25Retriever(
        BM25Index.from_chunks([], tokenizer=RecordingWhitespaceTokenizer())
    )

    with pytest.raises(BM25RetrievalInputError, match="string"):
        retriever.retrieve(None)  # type: ignore[arg-type]
