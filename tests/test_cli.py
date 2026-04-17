from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from immunize.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for k in [k for k in os.environ if k.startswith("IMMUNIZE_")]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.chdir(tmp_path)


def test_capture_bad_json_exits_zero_with_message(tmp_path: Path) -> None:
    result = runner.invoke(app, ["capture"], input="not-valid-json")
    assert result.exit_code == 0  # capture always exits 0
    assert "invalid capture payload" in (result.stderr or result.output)


def test_list_empty(tmp_path: Path) -> None:
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "No immunities" in result.output


def test_remove_unknown_id_exits_nonzero(tmp_path: Path) -> None:
    result = runner.invoke(app, ["remove", "42", "--yes"])
    assert result.exit_code == 1


def test_verify_empty_is_noop(tmp_path: Path) -> None:
    result = runner.invoke(app, ["verify"])
    assert result.exit_code == 0
    assert "No immunities" in result.output


@pytest.mark.skipif(not hasattr(os, "sys"), reason="placeholder to note guard coverage")
def test_windows_guard_documented() -> None:
    pass
