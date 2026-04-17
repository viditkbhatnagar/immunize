"""Behavioral verification for import-not-found-python.

Imports the fixture module (which itself loads cleanly — all bad
imports are deferred into the helper's body), then calls the public
API the way a consumer would: one positional string. The repro's
helper hits ``from _ghost_utils import slugify`` at call time and
raises ModuleNotFoundError; the fix resolves via stdlib ``re`` and
returns the slug.

Commandment #2 applies: no args are passed that override what the
fix is meant to change. Commandment #3: same call, different
outcome.
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


def test_make_slug_resolves_imports() -> None:
    fixture = _load_fixture()
    # Consumer call. Repro raises ModuleNotFoundError on the lazy
    # import; fix returns a hyphenated lowercase slug.
    result = fixture.make_slug("Hello World")
    assert result == "hello-world", f"expected 'hello-world', got {result!r}"
