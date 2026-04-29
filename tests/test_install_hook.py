"""Tests for ``immunize install-hook`` and the underlying merge logic.

Covers the six scenarios spec'd in the v0.2.0 plan:

1. Fresh project with no .claude/settings.json.
2. Existing settings.json with no `hooks` key.
3. Existing settings.json with hooks on unrelated events (PreToolUse, etc.).
4. Idempotent re-run: second invocation is a no-op, reports already_installed.
5. Stale / non-canonical command already present: --force rewrites; no flag errors out.
6. Read-only target returns a clean InstallResult(status="error").
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from immunize.cli import app
from immunize.hook_installer import (
    HOOK_COMMAND,
    InstallResult,
    install_claude_code_hook,
)

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for k in [k for k in os.environ if k.startswith("IMMUNIZE_")]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.chdir(tmp_path)


def _settings(tmp_path: Path) -> dict:
    path = tmp_path / ".claude" / "settings.json"
    return json.loads(path.read_text())


# --- unit: install_claude_code_hook ----------------------------------------


def test_fresh_project_creates_settings_with_hook(tmp_path: Path) -> None:
    result = install_claude_code_hook(tmp_path)
    assert result.status == "installed"
    assert result.settings_path == tmp_path / ".claude" / "settings.json"

    data = _settings(tmp_path)
    events = data["hooks"]["PostToolUseFailure"]
    assert len(events) == 1
    assert events[0]["matcher"] == "Bash"
    assert events[0]["hooks"][0]["command"] == HOOK_COMMAND
    assert events[0]["hooks"][0]["type"] == "command"


def test_existing_settings_without_hooks_gets_hook_added(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir()
    settings_path.write_text(json.dumps({"theme": "dark", "spinnerStyle": "dots"}))

    result = install_claude_code_hook(tmp_path)
    assert result.status == "installed"

    data = _settings(tmp_path)
    assert data["theme"] == "dark"  # preserved
    assert data["spinnerStyle"] == "dots"
    assert data["hooks"]["PostToolUseFailure"][0]["hooks"][0]["command"] == HOOK_COMMAND


def test_preserves_other_hook_events(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir()
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Write",
                            "hooks": [{"type": "command", "command": "prettier --write"}],
                        }
                    ],
                    "PostToolUse": [
                        {
                            "matcher": "Edit",
                            "hooks": [{"type": "command", "command": "eslint --fix"}],
                        }
                    ],
                }
            }
        )
    )

    result = install_claude_code_hook(tmp_path)
    assert result.status == "installed"

    data = _settings(tmp_path)
    assert data["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "prettier --write"
    assert data["hooks"]["PostToolUse"][0]["hooks"][0]["command"] == "eslint --fix"
    events = data["hooks"]["PostToolUseFailure"]
    assert len(events) == 1
    assert events[0]["hooks"][0]["command"] == HOOK_COMMAND


def test_preserves_unrelated_entries_in_same_event(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir()
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PostToolUseFailure": [
                        {
                            "matcher": "Edit",
                            "hooks": [{"type": "command", "command": "notify-send 'edit failed'"}],
                        }
                    ]
                }
            }
        )
    )

    result = install_claude_code_hook(tmp_path)
    assert result.status == "installed"

    events = _settings(tmp_path)["hooks"]["PostToolUseFailure"]
    assert len(events) == 2
    # Original user hook untouched.
    assert events[0]["matcher"] == "Edit"
    assert events[0]["hooks"][0]["command"] == "notify-send 'edit failed'"
    # Ours appended.
    assert events[1]["matcher"] == "Bash"
    assert events[1]["hooks"][0]["command"] == HOOK_COMMAND


def test_idempotent_second_run_is_noop(tmp_path: Path) -> None:
    first = install_claude_code_hook(tmp_path)
    assert first.status == "installed"
    before = (tmp_path / ".claude" / "settings.json").read_text()

    second = install_claude_code_hook(tmp_path)
    assert second.status == "already_installed"
    after = (tmp_path / ".claude" / "settings.json").read_text()
    assert before == after


def test_stale_command_without_force_errors(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir()
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PostToolUseFailure": [
                        {
                            "matcher": "Bash",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "immunize capture --source legacy-flag",
                                }
                            ],
                        }
                    ]
                }
            }
        )
    )

    result = install_claude_code_hook(tmp_path, force=False)
    assert result.status == "error"
    assert result.error is not None
    assert "--force" in result.error


def test_stale_command_with_force_overwrites(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir()
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PostToolUseFailure": [
                        {
                            "matcher": "Bash",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "immunize capture --source legacy-flag",
                                }
                            ],
                        }
                    ]
                }
            }
        )
    )

    result = install_claude_code_hook(tmp_path, force=True)
    assert result.status == "overwritten"

    events = _settings(tmp_path)["hooks"]["PostToolUseFailure"]
    assert len(events) == 1
    assert events[0]["hooks"][0]["command"] == HOOK_COMMAND


def test_read_only_target_returns_error_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    original_mkdir = Path.mkdir

    def _broken_mkdir(self: Path, *args, **kwargs):
        # Block the .claude parent mkdir only; everything else still works.
        if self.name == ".claude":
            raise OSError("read-only filesystem")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", _broken_mkdir)
    result = install_claude_code_hook(tmp_path)
    assert result.status == "error"
    assert "read-only" in (result.error or "")


def test_malformed_existing_settings_surfaces_error(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir()
    settings_path.write_text("{not valid json")

    result = install_claude_code_hook(tmp_path)
    assert result.status == "error"
    assert result.error is not None


def test_non_object_existing_settings_errors_out(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir()
    settings_path.write_text(json.dumps([1, 2, 3]))

    result = install_claude_code_hook(tmp_path)
    assert result.status == "error"
    assert "object" in (result.error or "")


def test_writes_gitignore_for_hook_payloads(tmp_path: Path) -> None:
    install_claude_code_hook(tmp_path)
    gitignore = tmp_path / ".immunize" / ".gitignore"
    assert gitignore.is_file()
    assert "hook_payloads/" in gitignore.read_text()


def test_returns_dataclass_shape(tmp_path: Path) -> None:
    result = install_claude_code_hook(tmp_path)
    assert isinstance(result, InstallResult)
    assert result.status in {"installed", "already_installed", "overwritten", "error"}


# --- CLI integration --------------------------------------------------------


def test_cli_install_hook_succeeds_on_fresh_project(tmp_path: Path) -> None:
    result = runner.invoke(app, ["install-hook"])
    assert result.exit_code == 0
    assert "Installed Claude Code hook" in result.output
    assert (tmp_path / ".claude" / "settings.json").is_file()


def test_cli_install_hook_reports_already_installed(tmp_path: Path) -> None:
    runner.invoke(app, ["install-hook"])
    result = runner.invoke(app, ["install-hook"])
    assert result.exit_code == 0
    assert "already installed" in result.output


def test_cli_install_hook_accepts_project_dir_flag(tmp_path: Path) -> None:
    other = tmp_path / "other-repo"
    other.mkdir()
    result = runner.invoke(app, ["install-hook", "--project-dir", str(other)])
    assert result.exit_code == 0
    assert (other / ".claude" / "settings.json").is_file()
    # cwd untouched.
    assert not (tmp_path / ".claude").exists()


def test_cli_install_hook_warns_when_immunize_not_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the canonical hook command isn't reachable on PATH, install-hook
    must surface a warning so the user knows the hook will silently fail
    when Claude Code spawns it. Common on Windows after `pip install --user`,
    where the Scripts dir isn't on PATH by default.
    """
    import shutil

    monkeypatch.setattr(shutil, "which", lambda _name: None)
    result = runner.invoke(app, ["install-hook"])
    assert result.exit_code == 0
    assert "not found on PATH" in result.output


def test_cli_install_hook_no_warning_when_immunize_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The PATH warning must NOT fire when `immunize` is reachable — happy
    path under venv installs and PATH-extended user installs.
    """
    import shutil

    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/local/bin/immunize")
    result = runner.invoke(app, ["install-hook"])
    assert result.exit_code == 0
    assert "not found on PATH" not in result.output


def test_cli_install_hook_force_overwrites_stale(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir()
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PostToolUseFailure": [
                        {
                            "matcher": "Bash",
                            "hooks": [{"type": "command", "command": "immunize capture --stale"}],
                        }
                    ]
                }
            }
        )
    )
    no_force = runner.invoke(app, ["install-hook"])
    assert no_force.exit_code == 1

    with_force = runner.invoke(app, ["install-hook", "--force"])
    assert with_force.exit_code == 0
    assert "Overwrote" in with_force.output
    events = _settings(tmp_path)["hooks"]["PostToolUseFailure"]
    assert events[0]["hooks"][0]["command"] == HOOK_COMMAND
