"""Step 7a wiring tests for ``immunize author-pattern``.

These exercise only the CLI-level wiring: the subcommand is registered, the
Typer option validators (``exists=True``) fire as expected, and the stub
rejects invocations without ``ANTHROPIC_API_KEY``. The full drafting flow
lands in Step 7b along with the mocked-anthropic scenarios.
"""

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


def test_missing_api_key_exits_1_with_clear_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    err = tmp_path / "error.json"
    err.write_text('{"source": "manual"}')
    out = tmp_path / "patterns"
    out.mkdir()

    result = runner.invoke(
        app,
        ["author-pattern", "--from-error", str(err), "--output", str(out)],
    )
    assert result.exit_code == 1
    # stderr is captured in result.output under typer's CliRunner default mix.
    assert "ANTHROPIC_API_KEY" in result.output


def test_missing_input_file_exits_with_typer_validation_error(tmp_path: Path) -> None:
    out = tmp_path / "patterns"
    out.mkdir()
    result = runner.invoke(
        app,
        [
            "author-pattern",
            "--from-error",
            str(tmp_path / "does-not-exist.json"),
            "--output",
            str(out),
        ],
    )
    # Typer emits exit code 2 for Option(exists=True) validation failures.
    assert result.exit_code == 2
