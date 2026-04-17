"""Behavioral verification for rate-limit-no-backoff.

Mocks an HTTP client whose first response is 429 and second is 200.
Repro calls ``raise_for_status()`` on the 429 and dies immediately;
fix observes the 429, sleeps (mocked to a no-op), retries, and
returns the 200 payload.

Commandment #2: the consumer call passes only ``client`` and
``user_id`` — retry behavior belongs inside the function body, not
in caller-provided knobs. Commandment #3: identical call shape,
different outcomes depending on repro vs fix.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "repro.py"


class _HTTPError(Exception):
    """Duck-typed HTTP error raised by the fake response on 4xx/5xx."""


class _FakeResponse:
    """Minimal duck-typed response covering the fixture's surface."""

    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise _HTTPError(f"{self.status_code} response")

    def json(self) -> dict:
        return self._payload


def _load_fixture():
    spec = importlib.util.spec_from_file_location("_immunize_repro_fixture", FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_fetch_user_retries_on_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    # Neutralize the fix's real exponential sleep so the test is fast.
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)

    fixture = _load_fixture()
    client = Mock()
    client.get.side_effect = [
        _FakeResponse(429, {"error": "rate limit"}),
        _FakeResponse(200, {"id": "u1", "name": "Ada"}),
    ]

    # Consumer call — no retry knobs.
    result = fixture.fetch_user(client, "u1")
    assert result == {"id": "u1", "name": "Ada"}
    assert client.get.call_count == 2
