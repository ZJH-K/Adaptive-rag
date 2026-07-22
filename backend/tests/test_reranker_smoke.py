"""Opt-in real reranker provider smoke test."""

import os
from datetime import date

import pytest

from src.config import Settings
from src.rag.retrieval import RerankerClient


@pytest.mark.external_reranker
def test_real_reranker_scores_all_candidates() -> None:
    """Call the configured provider once without printing candidate contents."""
    if os.getenv("RUN_EXTERNAL_RERANKER_SMOKE") != "1":
        pytest.skip(
            "Set RUN_EXTERNAL_RERANKER_SMOKE=1 to call the reranker provider"
        )

    settings = Settings()
    if not settings.reranker_api_key:
        pytest.skip("RERANKER_API_KEY is not configured")

    candidates = [
        "A checkpointer stores graph state by thread_id.",
        "A thread pool schedules concurrent operating-system work.",
        "Markdown headings preserve technical document structure.",
    ]
    scores = RerankerClient(settings).score(
        "Where does LangGraph store thread state?",
        candidates,
    )

    assert {score.index for score in scores} == {0, 1, 2}
    after = [item.index for item in sorted(scores, key=lambda item: -item.score)]
    print(
        "reranker smoke:",
        {
            "date": date.today().isoformat(),
            "model": settings.reranker_model,
            "before": [0, 1, 2],
            "after": after,
        },
    )
