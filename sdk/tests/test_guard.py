"""Unit tests for the @guard decorator and HTTP client (mocked HTTP)."""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import httpx
import pytest

from ceadly import guard
from ceadly.exceptions import (
    CeadlyActionRejected,
    CeadlyActionTimedOut,
    CeadlyConfigurationError,
    CeadlyServiceUnavailable,
)

CHECKPOINT_ID = "11111111-1111-1111-1111-111111111111"
AGENT_ID = "00000000-0000-0000-0000-000000000002"
API_URL = "http://localhost:8000"

_ROUTING: dict[str, Any] = {
    "criticality": "HIGH",
    "matched_rule_index": 0,
    "reviewer_group": "finance-team-leads",
    "on_timeout": "reject",
    "require_dual_approval": False,
    "log_only": False,
    "policy_version_id": "00000000-0000-0000-0000-000000000003",
}


def _pending_create() -> dict[str, Any]:
    return {
        "id": CHECKPOINT_ID,
        "status": "PENDING",
        "pre_decision_hash": "a" * 64,
        "routing": _ROUTING,
    }


def _await_url(timeout_seconds: float = 30.0) -> str:
    return (
        f"{API_URL}/v1/checkpoints/{CHECKPOINT_ID}/await?timeout={int(timeout_seconds)}"
    )


def _await_response(status: str) -> dict[str, Any]:
    return {
        "id": CHECKPOINT_ID,
        "status": status,
        "criticality": "HIGH",
        "pre_decision_hash": "a" * 64,
        "policy_rule": "rule[0]|reject",
        "policy_version_id": "00000000-0000-0000-0000-000000000003",
        "routing": _ROUTING,
        "created_at": "2026-06-10T12:00:00Z",
    }


class TestDecorationValidation:
    def test_decoration_without_legal_person_raises(
        self, valid_guard_kwargs: dict[str, str]
    ) -> None:
        with pytest.raises(CeadlyConfigurationError, match="legal_responsible_person"):
            guard(
                legal_responsible_person="",
                legal_responsible_title=valid_guard_kwargs["legal_responsible_title"],
                agent_id=valid_guard_kwargs["agent_id"],
            )(lambda: None)

    def test_decoration_without_legal_title_raises(
        self, valid_guard_kwargs: dict[str, str]
    ) -> None:
        with pytest.raises(CeadlyConfigurationError, match="legal_responsible_title"):
            guard(
                legal_responsible_person=valid_guard_kwargs["legal_responsible_person"],
                legal_responsible_title="",
                agent_id=valid_guard_kwargs["agent_id"],
            )(lambda: None)

    def test_empty_string_raises(self, valid_guard_kwargs: dict[str, str]) -> None:
        with pytest.raises(CeadlyConfigurationError):
            guard(
                legal_responsible_person="   ",
                legal_responsible_title=valid_guard_kwargs["legal_responsible_title"],
                agent_id=valid_guard_kwargs["agent_id"],
            )(lambda: None)

    def test_valid_decoration_succeeds(
        self, valid_guard_kwargs: dict[str, str]
    ) -> None:
        @guard(**valid_guard_kwargs)
        def ok() -> str:
            return "fine"

        assert ok.__name__ == "ok"


class TestGuardRuntime:
    def test_approved_path_runs_function(
        self, httpx_mock: Any, valid_guard_kwargs: dict[str, str]
    ) -> None:
        httpx_mock.add_response(
            method="POST",
            url=f"{API_URL}/v1/checkpoints",
            json=_pending_create(),
        )
        httpx_mock.add_response(
            method="GET",
            url=_await_url(5.0),
            json=_await_response("APPROVED"),
        )
        spy = Mock(return_value={"sent": True})

        @guard(**valid_guard_kwargs, timeout_seconds=5)
        def send_email(to: str) -> dict[str, bool]:
            return spy(to)

        result = send_email("user@example.com")
        assert result == {"sent": True}
        spy.assert_called_once_with("user@example.com")

    def test_rejected_never_runs_function(
        self, httpx_mock: Any, valid_guard_kwargs: dict[str, str]
    ) -> None:
        httpx_mock.add_response(
            method="POST",
            url=f"{API_URL}/v1/checkpoints",
            json=_pending_create(),
        )
        httpx_mock.add_response(
            method="GET",
            url=_await_url(30.0),
            json=_await_response("REJECTED"),
        )
        spy = Mock()

        @guard(**valid_guard_kwargs)
        def send_email(to: str) -> None:
            spy(to)

        with pytest.raises(CeadlyActionRejected, match="REJECTED"):
            send_email("user@example.com")
        spy.assert_not_called()

    def test_timed_out_raises(
        self, httpx_mock: Any, valid_guard_kwargs: dict[str, str]
    ) -> None:
        httpx_mock.add_response(
            method="POST",
            url=f"{API_URL}/v1/checkpoints",
            json=_pending_create(),
        )
        httpx_mock.add_response(
            method="GET",
            url=_await_url(30.0),
            json=_await_response("TIMED_OUT"),
        )
        spy = Mock()

        @guard(**valid_guard_kwargs)
        def send_email(to: str) -> None:
            spy(to)

        with pytest.raises(CeadlyActionTimedOut):
            send_email("user@example.com")
        spy.assert_not_called()

    def test_escalated_raises_timed_out(
        self, httpx_mock: Any, valid_guard_kwargs: dict[str, str]
    ) -> None:
        httpx_mock.add_response(
            method="POST",
            url=f"{API_URL}/v1/checkpoints",
            json=_pending_create(),
        )
        httpx_mock.add_response(
            method="GET",
            url=_await_url(30.0),
            json=_await_response("ESCALATED"),
        )
        spy = Mock()

        @guard(**valid_guard_kwargs)
        def send_email(to: str) -> None:
            spy(to)

        with pytest.raises(CeadlyActionTimedOut):
            send_email("user@example.com")
        spy.assert_not_called()

    def test_auto_approved_skips_await(
        self, httpx_mock: Any, valid_guard_kwargs: dict[str, str]
    ) -> None:
        httpx_mock.add_response(
            method="POST",
            url=f"{API_URL}/v1/checkpoints",
            json={
                "id": CHECKPOINT_ID,
                "status": "AUTO_APPROVED",
                "pre_decision_hash": "b" * 64,
                "routing": {**_ROUTING, "log_only": True},
            },
        )
        spy = Mock(return_value="done")

        @guard(**valid_guard_kwargs)
        def read_only() -> str:
            return spy()

        assert read_only() == "done"
        spy.assert_called_once()
        await_calls = [r for r in httpx_mock.get_requests() if "/await" in str(r.url)]
        assert await_calls == []

    def test_agent_suspended_raises_rejected(
        self, httpx_mock: Any, valid_guard_kwargs: dict[str, str]
    ) -> None:
        httpx_mock.add_response(
            method="POST",
            url=f"{API_URL}/v1/checkpoints",
            status_code=403,
            json={"code": "agent_suspended", "message": "Agent is suspended."},
        )
        spy = Mock()

        @guard(**valid_guard_kwargs)
        def send_email(to: str) -> None:
            spy(to)

        with pytest.raises(CeadlyActionRejected, match="suspended"):
            send_email("user@example.com")
        spy.assert_not_called()

    def test_policy_unavailable_raises_service_unavailable(
        self, httpx_mock: Any, valid_guard_kwargs: dict[str, str]
    ) -> None:
        httpx_mock.add_response(
            method="POST",
            url=f"{API_URL}/v1/checkpoints",
            status_code=503,
            json={"code": "policy_unavailable", "message": "No active policy."},
        )
        spy = Mock()

        @guard(**valid_guard_kwargs)
        def send_email(to: str) -> None:
            spy(to)

        with pytest.raises(CeadlyServiceUnavailable, match="policy"):
            send_email("user@example.com")
        spy.assert_not_called()

    def test_api_unreachable_raises_service_unavailable(
        self, httpx_mock: Any, valid_guard_kwargs: dict[str, str]
    ) -> None:
        httpx_mock.add_exception(httpx.ConnectError("Connection refused"))
        spy = Mock()

        @guard(**valid_guard_kwargs)
        def send_email(to: str) -> None:
            spy(to)

        with pytest.raises(CeadlyServiceUnavailable, match=API_URL):
            send_email("user@example.com")
        spy.assert_not_called()

    def test_modified_runs_function(
        self, httpx_mock: Any, valid_guard_kwargs: dict[str, str]
    ) -> None:
        httpx_mock.add_response(
            method="POST",
            url=f"{API_URL}/v1/checkpoints",
            json=_pending_create(),
        )
        httpx_mock.add_response(
            method="GET",
            url=_await_url(30.0),
            json=_await_response("MODIFIED"),
        )
        spy = Mock(return_value={"ok": True})

        @guard(**valid_guard_kwargs)
        def send_email(to: str) -> dict[str, bool]:
            return spy(to)

        assert send_email("user@example.com") == {"ok": True}
        spy.assert_called_once()

    def test_api_key_param_sends_authorization_header(
        self, httpx_mock: Any, valid_guard_kwargs: dict[str, str]
    ) -> None:
        httpx_mock.add_response(
            method="POST",
            url=f"{API_URL}/v1/checkpoints",
            json={
                "id": CHECKPOINT_ID,
                "status": "AUTO_APPROVED",
                "pre_decision_hash": "c" * 64,
                "routing": _ROUTING,
            },
        )
        spy = Mock(return_value="ok")

        @guard(**valid_guard_kwargs, api_key="cead_sk_test")
        def send_email(to: str) -> str:
            return spy(to)

        send_email("user@example.com")
        post_request = httpx_mock.get_requests()[0]
        assert post_request.headers["Authorization"] == "Bearer cead_sk_test"

    def test_ceadly_api_key_env_sends_authorization_header(
        self,
        httpx_mock: Any,
        valid_guard_kwargs: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("CEADLY_API_KEY", "cead_sk_env")
        httpx_mock.add_response(
            method="POST",
            url=f"{API_URL}/v1/checkpoints",
            json={
                "id": CHECKPOINT_ID,
                "status": "AUTO_APPROVED",
                "pre_decision_hash": "d" * 64,
                "routing": _ROUTING,
            },
        )
        spy = Mock(return_value="ok")

        @guard(**valid_guard_kwargs)
        def send_email(to: str) -> str:
            return spy(to)

        send_email("user@example.com")
        post_request = httpx_mock.get_requests()[0]
        assert post_request.headers["Authorization"] == "Bearer cead_sk_env"
