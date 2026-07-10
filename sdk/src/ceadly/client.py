"""Synchronous HTTP client for the Ceadly checkpoint API."""

from __future__ import annotations

import logging
import math
import os
import sys
import time
import uuid
from typing import Any

import httpx

from ceadly.exceptions import (
    CeadlyActionRejected,
    CeadlyActionTimedOut,
    CeadlyServiceUnavailable,
)

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "https://api.ceadly.me"

# Server error codes that map to CeadlyServiceUnavailable (all except agent_suspended).
_SERVICE_UNAVAILABLE_CODES = frozenset(
    {
        "not_found",
        "invalid_transition",
        "adequacy_required",
        "configuration_error",
        "policy_unavailable",
    }
)

_TERMINAL_AWAIT_STATUSES = frozenset(
    {
        "APPROVED",
        "MODIFIED",
        "REJECTED",
        "TIMED_OUT",
        "ESCALATED",
        "TIMED_OUT_REJECTED",
    }
)


def _default_api_url() -> str:
    return os.environ.get("CEADLY_API_URL", DEFAULT_API_URL).rstrip("/")


def _parse_error_body(response: httpx.Response) -> tuple[str | None, str]:
    try:
        body = response.json()
    except ValueError:
        return None, response.text or f"HTTP {response.status_code}"
    if isinstance(body, dict):
        code = body.get("code")
        message = body.get("message", f"HTTP {response.status_code}")
        return str(code) if code is not None else None, str(message)
    return None, f"HTTP {response.status_code}"


def raise_for_response(response: httpx.Response) -> None:
    """Map a non-success HTTP response to the appropriate SDK exception."""
    code, message = _parse_error_body(response)
    if code == "agent_suspended":
        raise CeadlyActionRejected(message, code=code)
    if code in _SERVICE_UNAVAILABLE_CODES or response.status_code >= 500:
        raise CeadlyServiceUnavailable(message, code=code)
    if response.status_code == 403:
        raise CeadlyActionRejected(message, code=code)
    raise CeadlyServiceUnavailable(message, code=code)


def _log_unreachable(url: str) -> None:
    msg = (
        f"Ceadly API unreachable at {url}. Action blocked. "
        "Check CEADLY_API_URL and ensure the Ceadly service is running."
    )
    logger.warning(msg)
    print(f"WARNING: {msg}", file=sys.stderr)  # noqa: T201


class CeadlyClient:
    """Thin synchronous client for checkpoint create and await endpoints."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 120.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = (base_url or _default_api_url()).rstrip("/")
        self.api_key = api_key or os.environ.get("CEADLY_API_KEY")
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> CeadlyClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        read_timeout: float | None = None,
    ) -> dict[str, Any]:
        request_timeout = (
            httpx.Timeout(read_timeout) if read_timeout is not None else None
        )
        try:
            response = self._client.request(
                method,
                path,
                headers=self._headers(),
                params=params,
                json=json_body,
                timeout=request_timeout,
            )
        except httpx.HTTPError as exc:
            _log_unreachable(self.base_url)
            raise CeadlyServiceUnavailable(
                f"Ceadly API unreachable at {self.base_url}. "
                "Action blocked. Check CEADLY_API_URL and ensure "
                "the Ceadly service is running.",
                code="connection_error",
            ) from exc

        if response.status_code >= 400:
            raise_for_response(response)

        data = response.json()
        if not isinstance(data, dict):
            raise CeadlyServiceUnavailable(
                "Unexpected response format from Ceadly API.",
                code="invalid_response",
            )
        return data

    def create_checkpoint(
        self,
        *,
        agent_id: str,
        action_attributes: dict[str, Any],
        before_state: dict[str, Any],
        triggering_context: str,
        after_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST /v1/checkpoints."""
        body: dict[str, Any] = {
            "agent_id": agent_id,
            "action_attributes": action_attributes,
            "before_state": before_state,
            "triggering_context": triggering_context,
        }
        if after_state is not None:
            body["after_state"] = after_state
        return self._request("POST", "/v1/checkpoints", json_body=body)

    def await_decision(
        self,
        checkpoint_id: str | uuid.UUID,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        """GET /v1/checkpoints/{id}/await — long-poll until decision or timeout."""
        deadline = time.monotonic() + timeout_seconds
        last_response: dict[str, Any] | None = None

        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            chunk = min(max(1, math.ceil(remaining)), 30)
            last_response = self._request(
                "GET",
                f"/v1/checkpoints/{checkpoint_id}/await",
                params={"timeout": chunk},
                read_timeout=float(chunk) + 5.0,
            )
            status = str(last_response.get("status", ""))

            if status in _TERMINAL_AWAIT_STATUSES:
                return last_response
            if status == "PENDING":
                # Server returned without blocking — retry with remaining budget.
                time.sleep(0.5)
                continue

            raise CeadlyServiceUnavailable(
                f"Unexpected checkpoint status: {status}",
                code=status,
            )

        if last_response is not None:
            status = str(last_response.get("status", ""))
            if status in _TERMINAL_AWAIT_STATUSES:
                return last_response

        # Final short poll to force server-side timeout resolution.
        return self._request(
            "GET",
            f"/v1/checkpoints/{checkpoint_id}/await",
            params={"timeout": 0.2},
            read_timeout=10.0,
        )


def map_await_status(status: str, message: str | None = None) -> None:
    """Raise the SDK exception that corresponds to a terminal await status."""
    msg = message or f"Checkpoint resolved with status {status}"
    if status == "REJECTED":
        raise CeadlyActionRejected(msg, code="REJECTED")
    if status in ("TIMED_OUT", "ESCALATED"):
        raise CeadlyActionTimedOut(msg, code=status)
    if status in ("APPROVED", "MODIFIED"):
        return
    raise CeadlyServiceUnavailable(
        f"Unexpected checkpoint status: {status}",
        code=status,
    )


__all__ = [
    "CeadlyClient",
    "map_await_status",
    "raise_for_response",
]
