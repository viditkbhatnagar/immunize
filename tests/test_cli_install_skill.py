from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from immunize.cli import app
from immunize.skill_install import SKILL_REL_PATH, bundled_skill_bytes

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for k in [k for k in os.environ if k.startswith("IMMUNIZE_")]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.chdir(tmp_path)


def test_install_skill_happy_path(tmp_path: Path) -> None:
    result = runner.invoke(app, ["install-skill"])
    assert result.exit_code == 0, result.output
    dest = tmp_path / SKILL_REL_PATH
    assert dest.is_file()
    assert dest.read_bytes() == bundled_skill_bytes()
    assert "Installed immunize-manager skill" in result.output


def test_install_skill_idempotent_identical(tmp_path: Path) -> None:
    first = runner.invoke(app, ["install-skill"])
    assert first.exit_code == 0, first.output

    second = runner.invoke(app, ["install-skill"])
    assert second.exit_code == 0, second.output
    assert "already installed" in second.output
    dest = tmp_path / SKILL_REL_PATH
    assert dest.read_bytes() == bundled_skill_bytes()


def test_install_skill_refuses_overwrite(tmp_path: Path) -> None:
    dest = tmp_path / SKILL_REL_PATH
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"stale user content")

    result = runner.invoke(app, ["install-skill"])
    assert result.exit_code == 1
    combined = (result.stderr or "") + result.output
    assert "--force" in combined
    # File must remain unchanged.
    assert dest.read_bytes() == b"stale user content"


def test_install_skill_force_overwrites(tmp_path: Path) -> None:
    dest = tmp_path / SKILL_REL_PATH
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"stale user content")

    result = runner.invoke(app, ["install-skill", "--force"])
    assert result.exit_code == 0, result.output
    assert dest.read_bytes() == bundled_skill_bytes()
    assert "Overwrote" in result.output


def test_install_skill_force_rewrites_identical(tmp_path: Path) -> None:
    """--force always writes, even if bytes already match — plan spec."""
    first = runner.invoke(app, ["install-skill"])
    assert first.exit_code == 0, first.output

    second = runner.invoke(app, ["install-skill", "--force"])
    assert second.exit_code == 0, second.output
    assert "Overwrote" in second.output


def test_install_skill_creates_parent_dirs(tmp_path: Path) -> None:
    assert not (tmp_path / ".claude").exists()
    result = runner.invoke(app, ["install-skill"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / SKILL_REL_PATH).is_file()


def test_install_skill_custom_project_dir(tmp_path: Path) -> None:
    other = tmp_path / "elsewhere"
    other.mkdir()
    result = runner.invoke(app, ["install-skill", "--project-dir", str(other)])
    assert result.exit_code == 0, result.output
    assert (other / SKILL_REL_PATH).is_file()
    # cwd (tmp_path) must NOT have been touched.
    assert not (tmp_path / SKILL_REL_PATH).exists()


def test_install_skill_missing_project_dir(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    result = runner.invoke(app, ["install-skill", "--project-dir", str(missing)])
    assert result.exit_code == 1
    combined = (result.stderr or "") + result.output
    assert "does not exist" in combined
