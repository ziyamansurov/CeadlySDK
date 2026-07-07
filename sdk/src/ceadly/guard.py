"""@guard decorator — synchronous human-in-the-loop checkpoint for agent actions."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, TypeVar

from ceadly.client import CeadlyClient, map_await_status
from ceadly.exceptions import (
    CeadlyConfigurationError,
    CeadlyError,
    CeadlyServiceUnavailable,
)

F = TypeVar("F", bound=Callable[..., Any])

LEGAL_PERSON_MESSAGE = (
    "legal_responsible_person is required on every @guard decorator. "
    "This is a platform constraint — agents without a declared legal "
    "responsible person are suspended. See: https://docs.ceadly.com/accountability"
)

LEGAL_TITLE_MESSAGE = (
    "legal_responsible_title is required on every @guard decorator. "
    "This is a platform constraint — agents without a declared legal "
    "responsible title are suspended. See: https://docs.ceadly.com/accountability"
)

# Routing policy attribute keys commonly matched by the server engine.
_POLICY_ATTRIBUTE_KEYS = frozenset(
    {
        "action_type",
        "recipient_count",
        "data_sensitivity",
        "amount",
        "destination",
        "currency",
        "record_count",
    }
)

_IMMEDIATE_CREATE_STATUSES = frozenset({"APPROVED", "AUTO_APPROVED"})


def _require_non_blank(value: str | None, message: str) -> str:
    if value is None or not value.strip():
        raise CeadlyConfigurationError(message)
    return value.strip()


def _build_action_attributes(
    fn: Callable[..., Any],
    *,
    action_type: str | None,
    criticality: str,
    agent_owner: str | None,
    agent_permissions: list[str] | None,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    attrs: dict[str, Any] = {
        "action_type": action_type or fn.__name__,
        "criticality": criticality,
    }
    if agent_owner is not None:
        attrs["agent_owner"] = agent_owner
    if agent_permissions is not None:
        attrs["agent_permissions"] = agent_permissions
    for key, value in kwargs.items():
        if key in _POLICY_ATTRIBUTE_KEYS:
            attrs[key] = value
    return attrs


def guard(
    agent_id: str,
    legal_responsible_person: str,
    legal_responsible_title: str,
    agent_owner: str | None = None,
    agent_permissions: list[str] | None = None,
    criticality: str = "medium",
    notify: str | None = None,
    timeout_seconds: int = 30,
    action_type: str | None = None,
    api_key: str | None = None,
) -> Callable[[F], F]:
    """Block until a human approves the guarded action (Phase 1 synchronous model).

    Phase 3 will add criticality-based fail-open/fail-closed behavior when the
    API is unreachable. In Phase 1 all unreachable-API scenarios raise
    ``CeadlyServiceUnavailable``.
    """
    _require_non_blank(legal_responsible_person, LEGAL_PERSON_MESSAGE)
    _require_non_blank(legal_responsible_title, LEGAL_TITLE_MESSAGE)
    _ = notify  # reserved for Step 8+ notification routing

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            before_state: dict[str, Any] = {"args": list(args), "kwargs": kwargs}
            action_attributes = _build_action_attributes(
                fn,
                action_type=action_type,
                criticality=criticality,
                agent_owner=agent_owner,
                agent_permissions=agent_permissions,
                kwargs=kwargs,
            )
            triggering_context = f"{agent_id}:{fn.__name__}"

            with CeadlyClient(api_key=api_key) as client:
                try:
                    created = client.create_checkpoint(
                        agent_id=agent_id,
                        action_attributes=action_attributes,
                        before_state=before_state,
                        triggering_context=triggering_context,
                    )
                except CeadlyError:
                    raise
                except Exception as exc:
                    raise CeadlyServiceUnavailable(str(exc)) from exc

                create_status = str(created.get("status", ""))
                if create_status in _IMMEDIATE_CREATE_STATUSES:
                    return fn(*args, **kwargs)

                checkpoint_id = created.get("id")
                if checkpoint_id is None:
                    raise CeadlyServiceUnavailable(
                        "Checkpoint created without an id.",
                        code="invalid_response",
                    )

                try:
                    resolved = client.await_decision(
                        checkpoint_id,
                        float(timeout_seconds),
                    )
                except CeadlyError:
                    raise
                except Exception as exc:
                    raise CeadlyServiceUnavailable(str(exc)) from exc

                final_status = str(resolved.get("status", ""))
                if final_status in ("APPROVED", "MODIFIED"):
                    return fn(*args, **kwargs)
                map_await_status(final_status)
                raise CeadlyServiceUnavailable(
                    f"Unexpected checkpoint status: {final_status}",
                    code=final_status,
                )

        return wrapper  # type: ignore[return-value]

    return decorator
