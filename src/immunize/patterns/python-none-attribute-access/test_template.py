"""Behavioral verification for python-none-attribute-access.

Imports the fixture module, calls its public API with defaults only —
no parameter that the fix is meant to introduce is passed explicitly.
If the implementation dereferences an Optional without checking, the
test hits AttributeError and fails. The fix returns a sensible fallback
("unknown"), passing the test.

Commandment #2 applies: test defaults, not knobs. The consumer just
calls lookup_display_name(registry, user_id); the bug is in the body's
dereference, not in the interface.
"""

from __future__ import annotations

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


def test_lookup_display_name_handles_missing_user() -> None:
    fixture = _load_fixture()
    # Consumer call — empty registry, missing key. No extra args.
    result = fixture.lookup_display_name({}, "missing")
    # Fix returns "unknown"; buggy repro raises AttributeError on .name.
    assert isinstance(result, str), f"expected str fallback, got {result!r}"
    assert result != "", "expected non-empty fallback string"
