"""Fix for json-decode-no-handling.

Same ``parse_config(text) -> dict`` interface as the repro, but
``json.loads`` is wrapped in a ``try/except`` that converts
``JSONDecodeError`` into the module's own ``ConfigError`` — preserving
the cause via ``raise ... from exc``. Callers now see one exception
type with an actionable message; the raw decoder error never escapes
this boundary.
"""

from __future__ import annotations

import json
from typing import Any


class ConfigError(Exception):
    """Raised when configuration cannot be parsed."""


def parse_config(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"invalid JSON config at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
