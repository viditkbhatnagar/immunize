"""Tests for Claude Code PostToolUseFailure hook mode (``--source claude-code-hook``).

The hook payload schema differs from CapturePayload: top-level ``error``
(string), ``is_interrupt`` (bool), ``tool_name``, ``tool_input``, etc. The
translator in capture.py maps this onto CapturePayload; the CLI reads raw JSON
from stdin in this mode (bypassing CapturePayload validation) and dumps the
raw payload to ``.immunize/hook_payloads/`` as a v0.2.0 diagnostic so
contributors can see what Claude Code actually sends.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from immunize import capture
from immunize.capture import (
    dump_hook_payload,
    payload_from_claude_code_hook,
    read_hook_json_from_stdin,
)
from immunize.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for k in [k for k in os.environ if k.startswith("IMMUNIZE_")]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.chdir(tmp_path)


def _parse_stdout_json(stdout: str) -> dict:
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    raise AssertionError(f"no JSON line on stdout: {stdout!r}")


def _cors_hook_payload(cwd: Path) -> dict:
    # Matches both bundled anchors ("Access-Control-Allow-Credentials" + "credentials")
    # plus the "cors" error_class_hint, so fetch-missing-credentials clears its 0.75
    # threshold once translated.
    return {
        "session_id": "sess-abc-123",
        "transcript_path": "/tmp/transcript.jsonl",
        "cwd": str(cwd),
        "permission_mode": "default",
        "hook_event_name": "PostToolUseFailure",
        "tool_name": "Bash",
        "tool_input": {"command": "npm test", "description": "Run tests"},
        "tool_use_id": "toolu_01ABC",
        "error": (
            "Access to fetch at 'https://api.example.com/me' from origin "
            "'http://localhost:3000' has been blocked by CORS policy: Response "
            "to preflight request doesn't pass access control check: The value "
            "of the 'Access-Control-Allow-Credentials' header in the response "
            "is '' which must be 'true' when the request's credentials mode is "
            "'include'."
        ),
        "is_interrupt": False,
    }


# --- unit: translator -------------------------------------------------------


def test_translator_returns_none_for_non_bash_tools(tmp_path: Path) -> None:
    payload = payload_from_claude_code_hook(
        {"tool_name": "Edit", "error": "something", "cwd": str(tmp_path)},
        cwd=tmp_path,
    )
    assert payload is None


def test_translator_maps_bash_failure_fields(tmp_path: Path) -> None:
    hook = _cors_hook_payload(tmp_path)
    payload = payload_from_claude_code_hook(hook, cwd=tmp_path)
    assert payload is not None
    assert payload.source == "claude-code-hook"
    assert payload.tool_name == "Bash"
    assert payload.command == "npm test"
    assert payload.stdout == ""
    assert "Access-Control-Allow-Credentials" in payload.stderr
    assert payload.exit_code == 1
    assert payload.cwd == str(tmp_path)
    assert payload.session_id == "sess-abc-123"
    assert isinstance(payload.timestamp, datetime)
    assert payload.timestamp.tzinfo is timezone.utc
    assert payload.project_fingerprint.startswith("sha256-")


def test_translator_tolerates_missing_optional_fields(tmp_path: Path) -> None:
    # Only tool_name provided; everything else defaults.
    payload = payload_from_claude_code_hook({"tool_name": "Bash"}, cwd=tmp_path)
    assert payload is not None
    assert payload.stderr == ""
    assert payload.command is None
    assert payload.session_id is None
    assert payload.cwd == str(tmp_path)  # fell back to the cwd arg


def test_translator_ignores_non_string_command_and_session(tmp_path: Path) -> None:
    # Defensive: upstream schema drift could make these non-strings.
    hook = {
        "tool_name": "Bash",
        "tool_input": {"command": 42},
        "session_id": ["not", "a", "string"],
        "error": "x",
        "cwd": str(tmp_path),
    }
    payload = payload_from_claude_code_hook(hook, cwd=tmp_path)
    assert payload is not None
    assert payload.command is None
    assert payload.session_id is None


def test_read_hook_json_rejects_non_object() -> None:
    from io import StringIO

    with pytest.raises(capture.CapturePayloadError, match="must be a JSON object"):
        read_hook_json_from_stdin(StringIO("[1, 2, 3]"))


def test_read_hook_json_rejects_invalid_json() -> None:
    from io import StringIO

    with pytest.raises(capture.CapturePayloadError, match="not valid JSON"):
        read_hook_json_from_stdin(StringIO("not-json"))


# --- unit: dump -------------------------------------------------------------


def test_dump_writes_file_with_expected_name(tmp_path: Path) -> None:
    hook = {"session_id": "abcdefgh-xxxx", "tool_name": "Bash"}
    dest = dump_hook_payload(hook, tmp_path)
    assert dest is not None
    assert dest.parent == tmp_path / ".immunize" / "hook_payloads"
    assert dest.suffix == ".json"
    assert "abcdefgh" in dest.name  # first 8 chars of session_id are in the name
    assert json.loads(dest.read_text()) == hook


def test_dump_is_best_effort_on_permission_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Simulate a filesystem that refuses mkdir; dump must return None, not raise.
    def _broken_mkdir(self, *args, **kwargs):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(Path, "mkdir", _broken_mkdir)
    assert dump_hook_payload({"tool_name": "Bash"}, tmp_path) is None


# --- integration: end-to-end through the CLI --------------------------------


def test_cli_hook_source_matches_cors_pattern_and_injects(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("IMMUNIZE_DEBUG_HOOK", "1")
    hook = _cors_hook_payload(tmp_path)
    result = runner.invoke(
        app,
        ["capture", "--source", "claude-code-hook"],
        input=json.dumps(hook),
    )
    assert result.exit_code == 0
    payload = _parse_stdout_json(result.output)
    assert payload["outcome"] == "matched_and_verified"
    assert payload["pattern_id"] == "fetch-missing-credentials"
    assert payload["pattern_origin"] == "bundled"

    # Dump landed in the expected location (debug env was set).
    dumps = list((tmp_path / ".immunize" / "hook_payloads").glob("*.json"))
    assert len(dumps) == 1
    assert json.loads(dumps[0].read_text())["session_id"] == "sess-abc-123"


def test_cli_hook_source_skips_non_bash(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMMUNIZE_DEBUG_HOOK", "1")
    hook = {
        "session_id": "sess-xyz",
        "tool_name": "Edit",
        "tool_input": {"file_path": "/x/y.py"},
        "error": "file not found",
        "cwd": str(tmp_path),
    }
    result = runner.invoke(
        app,
        ["capture", "--source", "claude-code-hook"],
        input=json.dumps(hook),
    )
    assert result.exit_code == 0
    payload = _parse_stdout_json(result.output)
    assert payload["outcome"] == "skipped"
    assert payload["reason"] == "non-Bash tool failure"
    assert payload["tool_name"] == "Edit"
    # Nothing injected.
    assert not (tmp_path / ".claude").exists()
    assert not (tmp_path / "tests" / "immunized").exists()
    # But the raw payload still got dumped for inspection (debug env was set).
    assert any((tmp_path / ".immunize" / "hook_payloads").glob("*.json"))


def test_cli_hook_source_skips_dump_without_debug_env(tmp_path: Path) -> None:
    # Default behavior in v0.2.0: no IMMUNIZE_DEBUG_HOOK set → no dumps on disk.
    # Keeps normal users from accumulating .immunize/hook_payloads/ files.
    hook = _cors_hook_payload(tmp_path)
    result = runner.invoke(
        app,
        ["capture", "--source", "claude-code-hook"],
        input=json.dumps(hook),
    )
    assert result.exit_code == 0
    hp_dir = tmp_path / ".immunize" / "hook_payloads"
    if hp_dir.exists():
        assert not list(hp_dir.glob("*.json"))


def test_cli_hook_source_handles_malformed_json(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["capture", "--source", "claude-code-hook"],
        input="{not valid json",
    )
    assert result.exit_code == 0  # capture always exits 0
    # No JSON line emitted (translator never ran); the Rich error goes to stderr.
    assert "invalid capture payload" in (result.stderr or result.output)


def test_cli_hook_source_tolerates_missing_fields(tmp_path: Path) -> None:
    # Minimal Bash hook — no error, no tool_input, no session_id. Should still
    # translate to an empty-stderr CapturePayload and emit `unmatched` (since
    # the matcher has nothing to work with).
    hook = {"tool_name": "Bash"}
    result = runner.invoke(
        app,
        ["capture", "--source", "claude-code-hook"],
        input=json.dumps(hook),
    )
    assert result.exit_code == 0
    payload = _parse_stdout_json(result.output)
    assert payload["outcome"] == "unmatched"
    assert payload["matched"] is False
