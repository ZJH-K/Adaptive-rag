"""Tests for environment-based application configuration."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.config import Settings


def test_settings_use_expected_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.embedding_model == "BAAI/bge-m3"
    assert settings.embedding_dimension == 1024
    assert settings.embedding_api_key is None
    assert settings.llm_base_url == "https://api.deepseek.com"
    assert settings.llm_api_key is None
    assert isinstance(settings.llm_model, str) and settings.llm_model
    assert settings.llm_timeout_seconds == 60.0
    assert settings.llm_temperature == 0.1
    assert settings.llm_json_mode_enabled is True
    assert settings.reranker_enabled is False
    assert settings.reranker_base_url == "https://api.siliconflow.cn/v1"
    assert settings.reranker_api_key is None
    assert isinstance(settings.reranker_model, str) and settings.reranker_model
    assert settings.reranker_timeout_seconds == 30.0
    assert settings.rerank_top_k == 5
    assert settings.hybrid_retrieval_enabled is True
    assert settings.dense_top_n == 20
    assert settings.bm25_top_n == 20
    assert settings.retrieve_top_n == 20
    assert settings.rrf_k == 60
    assert settings.langfuse_enabled is False
    assert settings.langfuse_base_url == "https://cloud.langfuse.com"
    assert settings.langfuse_public_key is None
    assert settings.langfuse_secret_key is None
    assert settings.langfuse_environment == "development"
    assert settings.langfuse_capture_question is False
    assert settings.langfuse_capture_answer is False
    assert settings.langfuse_max_text_chars == 200
    assert settings.chroma_persist_dir == Path("./data/chroma")
    assert settings.chroma_collection == "technical_docs"
    assert settings.knowledge_base_id == "technical_docs"
    assert settings.knowledge_root.name == "knowledge"
    assert settings.upload_max_bytes == 10 * 1024 * 1024
    assert settings.upload_temp_dir is None


def test_environment_variables_override_defaults(monkeypatch) -> None:
    monkeypatch.setenv("EMBEDDING_MODEL", "example/custom-embedding")
    monkeypatch.setenv("EMBEDDING_DIMENSION", "768")
    monkeypatch.setenv("EMBEDDING_BATCH_SIZE", "16")
    monkeypatch.setenv("EMBEDDING_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "configured-test-key")
    monkeypatch.setenv("LLM_MODEL", "example-chat")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "45.5")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.25")
    monkeypatch.setenv("LLM_JSON_MODE_ENABLED", "false")
    monkeypatch.setenv("RERANKER_ENABLED", "false")
    monkeypatch.setenv("RERANKER_BASE_URL", "https://rerank.example/v1")
    monkeypatch.setenv("RERANKER_API_KEY", "rerank-test-key")
    monkeypatch.setenv("RERANKER_MODEL", "example-reranker")
    monkeypatch.setenv("RERANKER_TIMEOUT_SECONDS", "9.5")
    monkeypatch.setenv("RERANK_TOP_K", "6")
    monkeypatch.setenv("HYBRID_RETRIEVAL_ENABLED", "false")
    monkeypatch.setenv("DENSE_TOP_N", "12")
    monkeypatch.setenv("BM25_TOP_N", "13")
    monkeypatch.setenv("RETRIEVE_TOP_N", "7")
    monkeypatch.setenv("RRF_K", "42")
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://langfuse.example")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_ENVIRONMENT", "test")
    monkeypatch.setenv("LANGFUSE_CAPTURE_QUESTION", "true")
    monkeypatch.setenv("LANGFUSE_CAPTURE_ANSWER", "true")
    monkeypatch.setenv("LANGFUSE_MAX_TEXT_CHARS", "500")
    monkeypatch.setenv("CHROMA_PERSIST_DIR", "./tmp/chroma")
    monkeypatch.setenv("CHROMA_COLLECTION", "test_docs")
    monkeypatch.setenv("KNOWLEDGE_BASE_ID", "test_kb")
    monkeypatch.setenv("KNOWLEDGE_ROOT", "./fixtures/knowledge")
    monkeypatch.setenv("UPLOAD_MAX_BYTES", "2048")
    monkeypatch.setenv("UPLOAD_TEMP_DIR", "./tmp/uploads")

    settings = Settings(_env_file=None)

    assert settings.embedding_model == "example/custom-embedding"
    assert settings.embedding_dimension == 768
    assert settings.embedding_batch_size == 16
    assert settings.embedding_timeout_seconds == 12.5
    assert settings.llm_base_url == "https://llm.example/v1"
    assert settings.llm_api_key == "configured-test-key"
    assert settings.llm_model == "example-chat"
    assert settings.llm_timeout_seconds == 45.5
    assert settings.llm_temperature == 0.25
    assert settings.llm_json_mode_enabled is False
    assert settings.reranker_enabled is False
    assert settings.reranker_base_url == "https://rerank.example/v1"
    assert settings.reranker_api_key == "rerank-test-key"
    assert settings.reranker_model == "example-reranker"
    assert settings.reranker_timeout_seconds == 9.5
    assert settings.rerank_top_k == 6
    assert settings.hybrid_retrieval_enabled is False
    assert settings.dense_top_n == 12
    assert settings.bm25_top_n == 13
    assert settings.retrieve_top_n == 7
    assert settings.rrf_k == 42
    assert settings.langfuse_enabled is True
    assert settings.langfuse_base_url == "https://langfuse.example"
    assert settings.langfuse_public_key == "pk-test"
    assert settings.langfuse_secret_key == "sk-test"
    assert settings.langfuse_environment == "test"
    assert settings.langfuse_capture_question is True
    assert settings.langfuse_capture_answer is True
    assert settings.langfuse_max_text_chars == 500
    assert settings.chroma_persist_dir == Path("./tmp/chroma")
    assert settings.chroma_collection == "test_docs"
    assert settings.knowledge_base_id == "test_kb"
    assert settings.knowledge_root == Path("./fixtures/knowledge")
    assert settings.upload_max_bytes == 2048
    assert settings.upload_temp_dir == Path("./tmp/uploads")


@pytest.mark.parametrize(
    "field",
    [
        "dense_top_n",
        "bm25_top_n",
        "retrieve_top_n",
        "rrf_k",
        "rerank_top_k",
        "upload_max_bytes",
    ],
)
def test_retrieval_integer_settings_must_be_positive(field: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: 0})


def test_legacy_candidate_limit_environment_names_remain_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RETRIEVE_TOP_N", raising=False)
    monkeypatch.delenv("RERANK_TOP_K", raising=False)
    monkeypatch.setenv("FUSION_TOP_N", "11")
    monkeypatch.setenv("RERANKER_TOP_N", "4")

    settings = Settings(_env_file=None)

    assert settings.retrieve_top_n == 11
    assert settings.rerank_top_k == 4
