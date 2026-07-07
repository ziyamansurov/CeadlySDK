"""Public SDK exception types."""

from __future__ import annotations


class CeadlyError(Exception):
    """Base exception for all Ceadly SDK errors."""

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class CeadlyServiceUnavailable(CeadlyError):
    """API unreachable, misconfigured, or returned a non-recoverable server error."""


class CeadlyActionRejected(CeadlyError):
    """Human reviewer rejected the action, or the agent is suspended."""


class CeadlyActionTimedOut(CeadlyError):
    """Review window elapsed without approval (TIMED_OUT or ESCALATED)."""


class CeadlyConfigurationError(CeadlyError):
    """SDK or decorator configuration is invalid."""
