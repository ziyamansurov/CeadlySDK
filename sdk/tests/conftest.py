"""Shared fixtures for SDK tests."""

from __future__ import annotations

import pytest

CHECKPOINT_ID = "11111111-1111-1111-1111-111111111111"
AGENT_ID = "00000000-0000-0000-0000-000000000002"
API_URL = "http://localhost:8000"


@pytest.fixture(autouse=True)
def _ceadly_api_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin API URL so httpx_mock URLs are deterministic."""
    monkeypatch.setenv("CEADLY_API_URL", API_URL)


@pytest.fixture
def valid_guard_kwargs() -> dict[str, str]:
    return {
        "agent_id": AGENT_ID,
        "legal_responsible_person": "john.doe@company.com",
        "legal_responsible_title": "VP Finance",
    }
