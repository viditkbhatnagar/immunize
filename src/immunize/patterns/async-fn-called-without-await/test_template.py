"""Behavioral verification for async-fn-called-without-await.

Drives the fixture's ``compute_total`` coroutine via
``asyncio.run``. Repro never awaits ``fetch_value()`` and tries
arithmetic on the coroutine object, raising TypeError at runtime.
Fix awaits, returns the resolved int, and the test asserts the
doubled value.

Commandment #2: no knobs are passed — the bug sits entirely in the
coroutine body. Commandment #3: identical call shape, different
outcomes across repro and fix.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "repro.py"


def _load_fixture():
    spec = importlib.util.spec_from_file_location("_immunize_repro_fixture", FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_compute_total_resolves_coroutine() -> None:
    fixture = _load_fixture()
    # Consumer call: asyncio.run drives the coroutine to completion.
    # Repro raises TypeError on ``coroutine * 2``; fix awaits
    # fetch_value() and returns 42.
    result = asyncio.run(fixture.compute_total())
    assert result == 42, f"expected 42, got {result!r}"
