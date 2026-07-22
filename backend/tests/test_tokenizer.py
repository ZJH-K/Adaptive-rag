"""Tests for Chinese and technical-text token normalization."""

import pytest

from src.rag.retrieval.tokenizer import JiebaTokenizer


@pytest.fixture(scope="module")
def tokenizer() -> JiebaTokenizer:
    """Share one initialized jieba engine across deterministic tests."""
    return JiebaTokenizer()


def test_chinese_sentence_is_segmented_without_punctuation(
    tokenizer: JiebaTokenizer,
) -> None:
    tokens = tokenizer.tokenize("LangGraph 使用 thread_id 配置 checkpoint。")

    assert "langgraph" in tokens
    assert "使用" in tokens
    assert "thread_id" in tokens
    assert "配置" in tokens
    assert "checkpoint" in tokens
    assert "。" not in tokens


def test_mixed_technical_text_preserves_identifiers_and_top_k(
    tokenizer: JiebaTokenizer,
) -> None:
    tokens = tokenizer.tokenize(
        "调用 Chroma similarity_search 返回 Top-K 结果。"
    )

    assert "chroma" in tokens
    assert "similarity_search" in tokens
    assert "top-k" in tokens
    assert "返回" in tokens


def test_model_name_and_version_are_searchable_tokens(
    tokenizer: JiebaTokenizer,
) -> None:
    tokens = tokenizer.tokenize("BAAI/bge-reranker-v2-m3 用于重排 v1.2.3。")

    assert tokens[:2] == ["baai", "bge-reranker-v2-m3"]
    assert "v1.2.3" in tokens
    assert "重排" in tokens


def test_case_whitespace_and_punctuation_are_normalized(
    tokenizer: JiebaTokenizer,
) -> None:
    tokens = tokenizer.tokenize("  LangGraph,\tLANGGRAPH!!! thread_id  ")

    assert tokens == ["langgraph", "langgraph", "thread_id"]


@pytest.mark.parametrize("text", ["", "   \n\t", "，。！？"])
def test_empty_or_punctuation_only_text_returns_no_tokens(
    tokenizer: JiebaTokenizer,
    text: str,
) -> None:
    assert tokenizer.tokenize(text) == []


def test_non_string_input_is_rejected(tokenizer: JiebaTokenizer) -> None:
    with pytest.raises(TypeError, match="string"):
        tokenizer.tokenize(None)  # type: ignore[arg-type]
