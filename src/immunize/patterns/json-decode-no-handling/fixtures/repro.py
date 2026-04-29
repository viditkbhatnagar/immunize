"""Repro for json-decode-no-handling.

``parse_config`` calls ``json.loads`` directly on whatever the caller
hands it — a config string read from disk, a request body, the text of
an HTTP response. There is no ``try/except``, so a malformed payload
escapes as a raw ``json.decoder.JSONDecodeError``. The interface gives
the caller no way to distinguish "bad input" from a programming bug.
"""

from __future__ import annotations

import json
from typing import Any


class ConfigError(Exception):
    """Raised when configuration cannot be parsed."""


def parse_config(text: str) -> dict[str, Any]:
    return json.loads(text)
