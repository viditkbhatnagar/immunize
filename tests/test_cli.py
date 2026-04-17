from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from immunize import verify
from immunize.cli import app
from immunize.models import VerificationResult

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for k in [k for k in os.environ if k.startswith("IMMUNIZE_")]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.chdir(tmp_path)


def _cors_payload(cwd: Path) -> str:
    return json.dumps(
        {
            "source": "manual",
            "stderr": (
                "Access to fetch at 'https://api.example.com/me' from origin "
                "'http://localhost:3000' has been blocked by CORS policy: Response "
                "to preflight request doesn't pass access control check: The value "
                "of the 'Access-Control-Allow-Credentials' header in the response "
                "is '' which must be 'true' when the request's credentials mode is "
                "'include'."
            ),
            "exit_code": 1,
            "cwd": str(cwd),
            "timestamp": "2026-04-17T00:00:00Z",
            "project_fingerprint": "smoke",
        }
    )


def _novel_payload(cwd: Path) -> str:
    return json.dumps(
        {
            "source": "manual",
            "stderr": "this is a wholly novel error with no matching pattern whatsoever zzz",
            "exit_code": 1,
            "cwd": str(cwd),
            "timestamp": "2026-04-17T00:00:00Z",
            "project_fingerprint": "smoke-novel",
        }
    )


def _parse_stdout_json(stdout: str) -> dict:
    """Extract the single JSON line from capture's stdout. Rich may have left
    no output on stdout at all, so we split and find the first JSON line."""
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    raise AssertionError(f"no JSON line on stdout: {stdout!r}")


# ---- Existing smoke tests -------------------------------------------------
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


# ---- Step 6f integration tests --------------------------------------------
def test_capture_known_error_matches_and_injects_bundled_pattern(tmp_path: Path) -> None:
    result = runner.invoke(app, ["capture"], input=_cors_payload(tmp_path))
    assert result.exit_code == 0

    payload = _parse_stdout_json(result.output)
    assert payload["outcome"] == "matched_and_verified"
    assert payload["verified"] is True
    assert payload["pattern_id"] == "fetch-missing-credentials"
    assert payload["pattern_origin"] == "bundled"
    assert payload["confidence"] >= 0.70

    skill = Path(payload["artifacts"]["skill"])
    cursor = Path(payload["artifacts"]["cursor_rule"])
    pytest_file = Path(payload["artifacts"]["pytest"])
    assert skill.is_file() and skill.name == "SKILL.md"
    assert cursor.is_file() and cursor.suffix == ".mdc"
    assert pytest_file.is_file() and pytest_file.name == "test_template.py"

    # SQLite row carries the pattern metadata.
    conn = sqlite3.connect(str(tmp_path / ".immunize" / "state.db"))
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute("SELECT pattern_id, pattern_origin FROM artifacts"))
    conn.close()
    assert len(rows) == 1
    assert rows[0]["pattern_id"] == "fetch-missing-credentials"
    assert rows[0]["pattern_origin"] == "bundled"


def test_capture_unknown_error_returns_can_author_locally(tmp_path: Path) -> None:
    result = runner.invoke(app, ["capture"], input=_novel_payload(tmp_path))
    assert result.exit_code == 0
    payload = _parse_stdout_json(result.output)
    assert payload == {"outcome": "unmatched", "matched": False, "can_author_locally": True}
    # No injection should have happened.
    assert not (tmp_path / ".claude").exists()
    assert not (tmp_path / "tests" / "immunized").exists()


def test_capture_verify_fail_does_not_inject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake_verify(pattern, settings):
        return VerificationResult(passed=False, error_message="forced failure for test")

    monkeypatch.setattr(verify, "verify", _fake_verify)
    result = runner.invoke(app, ["capture"], input=_cors_payload(tmp_path))
    assert result.exit_code == 0

    payload = _parse_stdout_json(result.output)
    assert payload["outcome"] == "matched_verify_failed"
    assert payload["verified"] is False
    assert payload["pattern_id"] == "fetch-missing-credentials"
    assert "forced failure" in payload["reason"]

    # No artifacts written, no SQLite row in artifacts table.
    assert not (tmp_path / ".claude").exists()
    conn = sqlite3.connect(str(tmp_path / ".immunize" / "state.db"))
    count = conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
    conn.close()
    assert count == 0


def test_capture_multiple_matches_picks_top_confidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Register a local pattern with a WEAKER match than the bundled one; top
    pick must remain fetch-missing-credentials (higher bundled confidence)."""
    local_patterns_dir = tmp_path / "local_patterns"
    weak_dir = local_patterns_dir / "weak-local-pattern"
    weak_dir.mkdir(parents=True)
    (weak_dir / "pattern.yaml").write_text(
        """id: weak-local-pattern
version: 1
schema_version: 1
author: "@test"
origin: local
error_class: other
languages: [python]
description: "weak test pattern"
match:
  stderr_patterns:
    - "Access-Control-Allow-Credentials"
  stdout_patterns: []
  error_class_hint: null
  min_confidence: 0.30
verification:
  pytest_relative_path: test_template.py
  timeout_seconds: 10
"""
    )
    (weak_dir / "SKILL.md").write_text("---\nname: weak\n---\n\nweak\n")
    (weak_dir / "cursor_rule.mdc").write_text(
        "---\ndescription: weak\nglobs: '**/*.py'\nalwaysApply: false\n---\n\nweak\n"
    )
    (weak_dir / "test_template.py").write_text("def test_x() -> None:\n    assert True\n")
    monkeypatch.setenv("IMMUNIZE_LOCAL_PATTERNS_DIR", str(local_patterns_dir))

    result = runner.invoke(app, ["capture"], input=_cors_payload(tmp_path))
    assert result.exit_code == 0

    payload = _parse_stdout_json(result.output)
    assert payload["pattern_id"] == "fetch-missing-credentials"
    assert payload["pattern_origin"] == "bundled"


def test_capture_dry_run_matches_but_does_not_inject(tmp_path: Path) -> None:
    result = runner.invoke(app, ["capture", "--dry-run"], input=_cors_payload(tmp_path))
    assert result.exit_code == 0

    payload = _parse_stdout_json(result.output)
    assert payload["outcome"] == "matched_and_verified"
    assert payload["dry_run"] is True
    assert payload["artifacts"] == {}
    # No injection happened.
    assert not (tmp_path / ".claude").exists()
    assert not (tmp_path / "tests" / "immunized").exists()


def test_capture_writes_json_to_stdout_not_stderr(tmp_path: Path) -> None:
    """Subprocess invocation so stdout and stderr stay separate — typer's
    CliRunner in this version merges them and drops the mix_stderr toggle."""
    import subprocess
    import sys as _sys

    proc = subprocess.run(
        [_sys.executable, "-m", "immunize", "capture"],
        input=_cors_payload(tmp_path),
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env={**os.environ, "XDG_CONFIG_HOME": str(tmp_path / "xdg")},
    )
    assert proc.returncode == 0

    # stdout: exactly one JSON line.
    stdout_lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert len(stdout_lines) == 1
    assert stdout_lines[0].startswith("{")
    parsed = json.loads(stdout_lines[0])
    assert parsed["outcome"] == "matched_and_verified"

    # stderr: no JSON line. Rich summary may be there; we just forbid stdout leakage.
    for line in proc.stderr.splitlines():
        assert not line.strip().startswith("{"), f"JSON leaked to stderr: {line!r}"


def test_capture_exits_zero_on_verify_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(pattern, settings):
        raise RuntimeError("synthetic verify blowup")

    monkeypatch.setattr(verify, "verify", _raise)
    result = runner.invoke(app, ["capture"], input=_cors_payload(tmp_path))
    assert result.exit_code == 0

    payload = _parse_stdout_json(result.output)
    assert payload["outcome"] == "matched_verify_failed"
    assert "synthetic verify blowup" in payload["reason"]
    # No artifact row written.
    conn = sqlite3.connect(str(tmp_path / ".immunize" / "state.db"))
    count = conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
    conn.close()
    assert count == 0
