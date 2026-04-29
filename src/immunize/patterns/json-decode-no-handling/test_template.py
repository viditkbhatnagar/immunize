"""Behavioral verification for json-decode-no-handling.

Imports the fixture module and calls ``parse_config`` with a malformed
JSON string the way a production consumer would. The repro re-raises
``json.JSONDecodeError`` — a low-level decoder exception that leaks
implementation detail across the API boundary. The fix translates that
into the module's own ``ConfigError`` (or any non-decoder exception)
with an actionable message.

Commandment #2 applies: test defaults, not knobs. The consumer just
calls ``parse_config(text)`` with whatever bytes they have; the bug is
in the body's missing ``try/except``, not the interface. The test does
not pass any error-handling parameter — that would hide the bug.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "repro.py"


def _load_fixture():
    spec = importlib.util.spec_from_file_location("_immunize_repro_fixture", FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parse_config_does_not_leak_jsondecodeerror() -> None:
    fixture = _load_fixture()
    # Truncated object — `json.loads` fails fast at column 1.
    bad_text = "{not valid"
    with pytest.raises(Exception) as exc_info:
        fixture.parse_config(bad_text)

    leaked = isinstance(exc_info.value, json.JSONDecodeError)
    assert not leaked, (
        f"parse_config leaked a raw json.JSONDecodeError "
        f"({exc_info.value!r}); wrap json.loads() in try/except and "
        "re-raise as a typed module exception so callers can handle "
        "bad input without coupling to the decoder."
    )
