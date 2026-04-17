"""Behavioral verification for missing-env-var.

Two scenarios exercise the pattern's breadth: env var unset and env
var set. The missing case must raise the fixture's own
``ConfigError`` — a raw ``KeyError`` from direct ``os.environ[...]``
indexing is the bug we are catching.

Commandment #2: both tests call ``get_api_key()`` with no args; the
bug sits in the body, not the signature. Commandment #3: same call
shape, different outcome depending on repro vs fix.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "repro.py"
ENV_VAR = "APP_API_KEY"


def _load_fixture():
    spec = importlib.util.spec_from_file_location("_immunize_repro_fixture", FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_missing_env_var_raises_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)
    fixture = _load_fixture()
    # Repro raises raw KeyError from os.environ[...]; fix raises
    # the module's ConfigError with an actionable message.
    with pytest.raises(fixture.ConfigError):
        fixture.get_api_key()


def test_set_env_var_returns_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_VAR, "sk-test-value")
    fixture = _load_fixture()
    assert fixture.get_api_key() == "sk-test-value"
