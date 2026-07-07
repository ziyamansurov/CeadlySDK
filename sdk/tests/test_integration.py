"""Live API integration tests — skipped unless CEADLY_INTEGRATION=1.

Run with:

    CEADLY_INTEGRATION=1 uv run pytest sdk/tests/test_integration.py -m integration -v

Requires docker compose up (API + Postgres + Redis). Escalation worker is NOT
required for client-timeout TIMED_OUT paths (reject policy applied inline by /await).
"""

from __future__ import annotations

import os

import pytest

from ceadly import guard
from ceadly.exceptions import CeadlyActionTimedOut

pytestmark = pytest.mark.integration

SEED_AGENT_ID = "00000000-0000-0000-0000-000000000002"


@pytest.fixture(autouse=True)
def _require_integration_flag() -> None:
    if os.environ.get("CEADLY_INTEGRATION") != "1":
        pytest.skip("Set CEADLY_INTEGRATION=1 to run live SDK integration tests.")


def test_live_high_checkpoint_times_out() -> None:
    """POST creates PENDING; /await with no reviewer returns TIMED_OUT."""

    @guard(
        agent_id=SEED_AGENT_ID,
        legal_responsible_person="john.doe@company.com",
        legal_responsible_title="VP Finance",
        action_type="send_email",
        timeout_seconds=2,
    )
    def send_mass_email(*, recipient_count: str) -> dict[str, bool]:
        return {"sent": True}

    with pytest.raises(CeadlyActionTimedOut):
        send_mass_email(recipient_count="5000")
