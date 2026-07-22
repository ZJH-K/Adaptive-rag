"""Tests for BM25 corpus construction and stable Chunk mapping."""

from __future__ import annotations

from threading import Event, Thread

import pytest

from src.rag.retrieval.bm25_index import BM25Index, DuplicateChunkIDError
from src.rag.schemas import Chunk


class WhitespaceTokenizer:
    """Simple injectable tokenizer used to isolate index behavior."""

    def tokenize(self, text: str) -> list[str]:
        """Split lowercase text on whitespace."""
        return [token.casefold() for token in text.split() if token]


def _chunk(chunk_id: str, text: str, chunk_index: int = 0) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id="doc-1",
        text=text,
        chunk_index=chunk_index,
        source="guide.md",
        source_type="markdown",
        chunk_strategy="recursive",
        content_hash=f"hash-{chunk_id}",
    )


def test_build_preserves_tokenized_corpus_and_position_mapping() -> None:
    chunks = [
        _chunk("a", "alpha shared", 0),
        _chunk("b", "beta shared", 1),
        _chunk("c", "gamma", 2),
    ]

    index = BM25Index.from_chunks(chunks, tokenizer=WhitespaceTokenizer())

    assert index.tokenized_corpus == (
        ("alpha", "shared"),
        ("beta", "shared"),
        ("gamma",),
    )
    assert index.chunk_ids == ("a", "b", "c")
    assert [index.get_chunk(i).chunk_id for i in range(len(index))] == [
        "a",
        "b",
        "c",
    ]
    assert index.chunks == tuple(chunks)
    assert index.generation == 1
    assert index.is_built is True


def test_empty_corpus_builds_and_scores_as_empty() -> None:
    index = BM25Index.from_chunks([], tokenizer=WhitespaceTokenizer())

    assert len(index) == 0
    assert index.is_empty is True
    assert index.is_built is True
    assert index.tokenized_corpus == ()
    assert index.chunk_ids == ()
    assert index.get_scores(["query"]) == []


def test_all_empty_documents_keep_mapping_and_return_zero_scores() -> None:
    chunks = [_chunk("blank", ""), _chunk("space", "   ", 1)]

    index = BM25Index.from_chunks(chunks, tokenizer=WhitespaceTokenizer())

    assert index.chunk_ids == ("blank", "space")
    assert index.tokenized_corpus == ((), ())
    assert index.get_scores(["query"]) == [0.0, 0.0]


def test_duplicate_chunk_ids_are_rejected_without_mutating_existing_index() -> None:
    original = _chunk("stable", "original")
    index = BM25Index.from_chunks(
        [original], tokenizer=WhitespaceTokenizer()
    )

    with pytest.raises(DuplicateChunkIDError, match="duplicate"):
        index.rebuild(
            [_chunk("duplicate", "first"), _chunk("duplicate", "second")]
        )

    assert index.chunk_ids == ("stable",)
    assert index.get_chunk(0) is original
    assert index.generation == 1


def test_rebuild_replaces_corpus_and_mapping_in_new_order() -> None:
    index = BM25Index.from_chunks(
        [_chunk("old-a", "alpha"), _chunk("old-b", "beta", 1)],
        tokenizer=WhitespaceTokenizer(),
    )
    replacements = [
        _chunk("new-c", "charlie"),
        _chunk("new-a", "alpha", 1),
    ]

    returned = index.rebuild(replacements)

    assert returned is index
    assert index.chunk_ids == ("new-c", "new-a")
    assert index.tokenized_corpus == (("charlie",), ("alpha",))
    assert index.get_chunk(0) is replacements[0]
    assert index.get_chunk(1) is replacements[1]
    assert index.generation == 2


def test_scores_remain_aligned_with_chunk_positions() -> None:
    index = BM25Index.from_chunks(
        [
            _chunk("alpha", "alpha unique"),
            _chunk("beta", "beta beta unique", 1),
            _chunk("other", "unrelated", 2),
        ],
        tokenizer=WhitespaceTokenizer(),
    )

    scores = index.get_scores(["beta"])

    assert len(scores) == len(index)
    assert scores[1] > scores[0]
    assert index.get_chunk(scores.index(max(scores))).chunk_id == "beta"


def test_blank_query_tokens_return_aligned_zero_scores() -> None:
    index = BM25Index.from_chunks(
        [_chunk("a", "alpha"), _chunk("b", "beta", 1)],
        tokenizer=WhitespaceTokenizer(),
    )

    assert index.get_scores([]) == [0.0, 0.0]


def test_rebuild_publishes_one_complete_snapshot() -> None:
    rebuild_started = Event()
    allow_rebuild = Event()

    class BlockingTokenizer(WhitespaceTokenizer):
        def tokenize(self, text: str) -> list[str]:
            if text == "new corpus":
                rebuild_started.set()
                assert allow_rebuild.wait(timeout=5)
            return super().tokenize(text)

    index = BM25Index.from_chunks(
        [_chunk("old", "old corpus")],
        tokenizer=BlockingTokenizer(),
    )
    before = index.snapshot()
    worker = Thread(
        target=index.rebuild,
        args=([_chunk("new", "new corpus")],),
    )
    worker.start()
    assert rebuild_started.wait(timeout=5)

    during = index.snapshot()
    allow_rebuild.set()
    worker.join(timeout=5)
    after = index.snapshot()

    assert during is before
    assert during.chunk_ids == ("old",)
    assert after.chunk_ids == ("new",)
    assert after.generation == before.generation + 1
