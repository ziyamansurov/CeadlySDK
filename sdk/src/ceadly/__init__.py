"""Ceadly public SDK — human-in-the-loop governance for AI agents."""

from ceadly.exceptions import (
    CeadlyActionRejected,
    CeadlyActionTimedOut,
    CeadlyConfigurationError,
    CeadlyError,
    CeadlyServiceUnavailable,
)
from ceadly.guard import guard

__version__ = "0.1.2"
__all__ = [
    "guard",
    "CeadlyError",
    "CeadlyServiceUnavailable",
    "CeadlyActionRejected",
    "CeadlyActionTimedOut",
    "CeadlyConfigurationError",
    "__version__",
]
