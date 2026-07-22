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
    assert settings.llm_model == "deepseek-chat"
    assert settings.llm_timeout_seconds == 60.0
    assert settings.llm_temperature == 0.1
    assert settings.llm_json_mode_enabled is True
    assert settings.hybrid_retrieval_enabled is True
    assert settings.dense_top_n == 20
    assert settings.bm25_top_n == 20
    assert settings.fusion_top_n == 20
    assert settings.rrf_k == 60
    assert settings.chroma_persist_dir == Path("./data/chroma")
    assert settings.chroma_collection == "technical_docs"


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
    monkeypatch.setenv("HYBRID_RETRIEVAL_ENABLED", "false")
    monkeypatch.setenv("DENSE_TOP_N", "12")
    monkeypatch.setenv("BM25_TOP_N", "13")
    monkeypatch.setenv("FUSION_TOP_N", "7")
    monkeypatch.setenv("RRF_K", "42")
    monkeypatch.setenv("CHROMA_PERSIST_DIR", "./tmp/chroma")
    monkeypatch.setenv("CHROMA_COLLECTION", "test_docs")

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
    assert settings.hybrid_retrieval_enabled is False
    assert settings.dense_top_n == 12
    assert settings.bm25_top_n == 13
    assert settings.fusion_top_n == 7
    assert settings.rrf_k == 42
    assert settings.chroma_persist_dir == Path("./tmp/chroma")
    assert settings.chroma_collection == "test_docs"


@pytest.mark.parametrize(
    "field",
    ["dense_top_n", "bm25_top_n", "fusion_top_n", "rrf_k"],
)
def test_retrieval_integer_settings_must_be_positive(field: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: 0})
