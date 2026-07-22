"""Opt-in real reranker provider smoke test."""

import os

import pytest

from src.config import Settings
from src.rag.retrieval import RerankerClient


@pytest.mark.external_reranker
def test_real_reranker_scores_all_candidates() -> None:
    """Call the configured provider once without printing candidate contents."""
    if os.getenv("RUN_RERANKER_SMOKE") != "1":
        pytest.skip("Set RUN_RERANKER_SMOKE=1 to call the reranker provider")

    settings = Settings()
    if not settings.reranker_api_key:
        pytest.skip("RERANKER_API_KEY is not configured")

    scores = RerankerClient(settings).score(
        "Where does LangGraph store thread state?",
        [
            "A checkpointer stores graph state by thread_id.",
            "A thread pool schedules concurrent operating-system work.",
        ],
    )

    assert {score.index for score in scores} == {0, 1}
    print(
        "reranker smoke:",
        {"model": settings.reranker_model, "scores": [score.score for score in scores]},
    )
