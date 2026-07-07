"""Unit tests for CeadlyClient await retry behavior."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from ceadly.client import CeadlyClient

CHECKPOINT_ID = "11111111-1111-1111-1111-111111111111"
API_URL = "http://localhost:8000"


def _await_body(status: str) -> dict[str, Any]:
    return {
        "id": CHECKPOINT_ID,
        "status": status,
        "criticality": "HIGH",
        "pre_decision_hash": "a" * 64,
        "policy_rule": "rule[0]|reject",
        "policy_version_id": "00000000-0000-0000-0000-000000000003",
        "routing": {
            "criticality": "HIGH",
            "matched_rule_index": 0,
            "reviewer_group": "finance-team-leads",
            "on_timeout": "reject",
            "require_dual_approval": False,
            "log_only": False,
            "policy_version_id": "00000000-0000-0000-0000-000000000003",
        },
        "created_at": "2026-06-10T12:00:00Z",
    }


def test_await_decision_retries_on_pending(httpx_mock: Any) -> None:
    """PENDING from /await must not raise — retry until a terminal status."""
    httpx_mock.add_response(json=_await_body("PENDING"))
    httpx_mock.add_response(json=_await_body("APPROVED"))

    with (
        patch("ceadly.client.time.sleep"),
        CeadlyClient(base_url=API_URL, timeout=60.0) as client,
    ):
        result = client.await_decision(CHECKPOINT_ID, timeout_seconds=10.0)

    assert result["status"] == "APPROVED"
    await_calls = [r for r in httpx_mock.get_requests() if "/await" in str(r.url)]
    assert len(await_calls) == 2
