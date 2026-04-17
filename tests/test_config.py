from __future__ import annotations

import os
from pathlib import Path

import pytest

from immunize.config import load_settings


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip IMMUNIZE_* and point XDG at a fresh dir so tests are hermetic."""
    for key in list(os.environ):
        if key.startswith("IMMUNIZE_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))


def test_defaults_when_nothing_set(tmp_path: Path) -> None:
    settings = load_settings(cwd=tmp_path)
    assert settings.model == "claude-sonnet-4-6"
    assert settings.generate_semgrep is False
    assert settings.verify_timeout_seconds == 30
    assert settings.verify_retry_count == 1
    assert settings.project_dir == tmp_path.resolve()
    assert settings.state_db_path == tmp_path.resolve() / ".immunize" / "state.db"


def test_semgrep_stays_off_with_no_config(tmp_path: Path) -> None:
    """Guards Refinement 1: no config = semgrep off, always."""
    assert load_settings(cwd=tmp_path).generate_semgrep is False


def test_env_overrides_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMMUNIZE_MODEL", "claude-opus-4-7")
    monkeypatch.setenv("IMMUNIZE_VERIFY_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("IMMUNIZE_GENERATE_SEMGREP", "true")

    settings = load_settings(cwd=tmp_path)
    assert settings.model == "claude-opus-4-7"
    assert settings.verify_timeout_seconds == 60
    assert settings.generate_semgrep is True


def test_cli_overrides_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMMUNIZE_MODEL", "model-from-env")
    settings = load_settings(cwd=tmp_path, cli_overrides={"model": "model-from-cli"})
    assert settings.model == "model-from-cli"


def test_project_toml_overrides_user_toml(tmp_path: Path) -> None:
    user = tmp_path / "xdg" / "immunize" / "config.toml"
    user.parent.mkdir(parents=True, exist_ok=True)
    user.write_text('model = "user-model"\n')

    project = tmp_path / ".immunize" / "config.toml"
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_text('model = "project-model"\n[verify]\ntimeout_seconds = 45\n')

    settings = load_settings(cwd=tmp_path)
    assert settings.model == "project-model"
    assert settings.verify_timeout_seconds == 45


def test_env_overrides_project_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / ".immunize" / "config.toml"
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_text('model = "project-model"\n')
    monkeypatch.setenv("IMMUNIZE_MODEL", "env-model")

    settings = load_settings(cwd=tmp_path)
    assert settings.model == "env-model"


def test_nested_toml_keys(tmp_path: Path) -> None:
    project = tmp_path / ".immunize" / "config.toml"
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_text('[generate]\nsemgrep = true\n[verify]\nretry_count = 3\n')

    settings = load_settings(cwd=tmp_path)
    assert settings.generate_semgrep is True
    assert settings.verify_retry_count == 3


