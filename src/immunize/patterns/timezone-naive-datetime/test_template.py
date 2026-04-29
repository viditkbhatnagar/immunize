"""Behavioral verification for timezone-naive-datetime.

Imports the fixture module and calls its public API with an offset-aware
``expiry`` — the canonical shape of a token timestamp returned by any
modern HTTP API (RFC 3339 / ISO 8601 with ``Z`` or ``+00:00``).

Commandment #2 applies: test defaults, not knobs. The consumer simply
calls ``is_token_expired(future)`` with an aware datetime; the bug lives
in the body's use of ``datetime.now()`` (naive), and the fix swaps it for
``datetime.now(timezone.utc)`` (aware). The interface is unchanged.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "repro.py"


def _load_fixture():
    spec = importlib.util.spec_from_file_location("_immunize_repro_fixture", FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_is_token_expired_with_aware_input() -> None:
    fixture = _load_fixture()
    future_aware = datetime.now(timezone.utc) + timedelta(hours=1)
    # Repro: datetime.now() is naive → TypeError on `>`. Fix: aware → returns False.
    result = fixture.is_token_expired(future_aware)
    assert result is False, f"expected future token to be unexpired, got {result!r}"


def test_is_token_expired_with_past_aware_input() -> None:
    fixture = _load_fixture()
    past_aware = datetime.now(timezone.utc) - timedelta(hours=1)
    result = fixture.is_token_expired(past_aware)
    assert result is True, f"expected past token to be expired, got {result!r}"
