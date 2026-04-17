"""End-to-end integration test for the Phase 1B capture stack.

Proves capture -> match -> verify -> inject -> storage works against the
real bundled pattern library, and — the unique coverage of this file —
that the injected pytest passes when a user runs it standalone in their
own project. Runs with ANTHROPIC_API_KEY unset to lock in the
no-runtime-LLM invariant.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from immunize.cli import app

runner = CliRunner()


def _scrub_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
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


def test_capture_matches_injects_and_artifacts_pass_in_user_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _scrub_env(monkeypatch, tmp_path)
    assert "ANTHROPIC_API_KEY" not in os.environ

    payload = json.dumps(
        {
            "source": "manual",
            "stderr": (
                "CORS policy: The 'Access-Control-Allow-Credentials' header is "
                "required when the credentials mode is 'include'"
            ),
            "stdout": "",
            "exit_code": 1,
            "cwd": str(tmp_path),
            "timestamp": "2026-04-17T00:00:00Z",
            "project_fingerprint": "integration-test",
        }
    )

    result = runner.invoke(app, ["capture", "--source", "manual"], input=payload)
    assert result.exit_code == 0, result.output

    out = _parse_stdout_json(result.output)
    assert out["outcome"] == "matched_and_verified"
    assert out["matched"] is True
    assert out["verified"] is True
    assert out["pattern_id"] == "fetch-missing-credentials"
    assert out["pattern_origin"] == "bundled"
    assert out["confidence"] >= 0.70
    assert set(out["artifacts"]) == {"skill", "cursor_rule", "pytest"}

    skill = Path(out["artifacts"]["skill"])
    cursor = Path(out["artifacts"]["cursor_rule"])
    pytest_file = Path(out["artifacts"]["pytest"])
    for p in (skill, cursor, pytest_file):
        assert p.is_file(), f"artifact missing on disk: {p}"
        assert p.is_relative_to(tmp_path), f"artifact escaped tmp_path: {p}"

    db = tmp_path / ".immunize" / "state.db"
    assert db.is_file()
    with sqlite3.connect(str(db)) as conn:
        conn.row_factory = sqlite3.Row
        rows = list(conn.execute("SELECT pattern_id, pattern_origin, verified FROM artifacts"))
    assert len(rows) == 1
    assert rows[0]["pattern_id"] == "fetch-missing-credentials"
    assert rows[0]["pattern_origin"] == "bundled"
    assert rows[0]["verified"] == 1

    injected_dir = tmp_path / "tests" / "immunized" / "fetch-missing-credentials"
    assert injected_dir.is_dir()
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(injected_dir),
            "--rootdir",
            str(tmp_path),
            "-p",
            "no:cacheprovider",
        ],
        cwd=str(tmp_path),
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, (
        f"injected pytest failed in user project simulation\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )


def test_capture_unknown_error_returns_unmatched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _scrub_env(monkeypatch, tmp_path)
    assert "ANTHROPIC_API_KEY" not in os.environ

    payload = json.dumps(
        {
            "source": "manual",
            "stderr": (
                "panic: runtime error: invalid memory address or nil pointer "
                "dereference\n\ngoroutine 42 [running]:\nmain.worker(0xc0000b8020)"
                "\n\t/app/worker.go:17 +0x2d"
            ),
            "stdout": "",
            "exit_code": 2,
            "cwd": str(tmp_path),
            "timestamp": "2026-04-17T00:00:00Z",
            "project_fingerprint": "integration-test-novel",
        }
    )

    result = runner.invoke(app, ["capture"], input=payload)
    assert result.exit_code == 0, result.output

    out = _parse_stdout_json(result.output)
    assert out == {"outcome": "unmatched", "matched": False, "can_author_locally": True}

    assert not (tmp_path / ".claude").exists()
    assert not (tmp_path / ".cursor").exists()
    assert not (tmp_path / "tests" / "immunized").exists()

    with sqlite3.connect(str(tmp_path / ".immunize" / "state.db")) as conn:
        count = conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
    assert count == 0
