"""Shared fixtures. Tests run fully offline using the mock providers."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.models.schemas import TravelRequest  # noqa: E402
from app.runtime.manager import WorkflowManager  # noqa: E402


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        llm_provider="mock",
        web_search_provider="mock",
        weather_provider="mock",
        storage_dir=str(tmp_path),
        database_path=str(tmp_path / "test-planner.sqlite"),
        request_timeout_seconds=60.0,
    )


@pytest.fixture
def manager(settings) -> WorkflowManager:
    return WorkflowManager(settings)


def sample_request() -> TravelRequest:
    start = date(2026, 6, 10)
    return TravelRequest(
        destination="Paris",
        start_date=start,
        end_date=start + timedelta(days=3),
        budget={"min_amount": 1500.0, "max_amount": 3200.0, "currency": "USD"},
        interests=["art", "food", "culture"],
        travelers=2,
        travel_style="cultural",
        notes="Love museums and walking.",
    )


@pytest.fixture
def request_payload() -> TravelRequest:
    return sample_request()