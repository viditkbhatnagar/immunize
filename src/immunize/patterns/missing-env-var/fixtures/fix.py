"""Fix for missing-env-var.

Same interface as repro. Reads ``os.environ.get`` and raises
``ConfigError`` with an actionable message when the value is
missing or empty. Callers see a specific signal, not an opaque
KeyError.
"""

from __future__ import annotations

import os


class ConfigError(Exception):
    """Raised when required configuration is missing."""


def get_api_key() -> str:
    value = os.environ.get("APP_API_KEY")
    if not value:
        raise ConfigError("APP_API_KEY is not set. Export it before running.")
    return value
