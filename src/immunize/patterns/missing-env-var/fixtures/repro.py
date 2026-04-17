"""Repro for missing-env-var.

AI indexed ``os.environ`` directly. Missing config leaks as a raw
``KeyError`` with no hint about which variable was expected or why
the program needs it. ``ConfigError`` is defined but unused — the
fix is what actually raises it.
"""

from __future__ import annotations

import os


class ConfigError(Exception):
    """Raised when required configuration is missing."""


def get_api_key() -> str:
    return os.environ["APP_API_KEY"]
