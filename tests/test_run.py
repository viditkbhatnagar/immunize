"""Tests for ``immunize run <cmd>`` — the subprocess-wrapping fallback path.

Covers the tricky parts: exit-code propagation (subprocess's, not ours),
capture-on-failure default, --no-capture opt-out, --timeout semantics
(no capture on deadline), end-to-end match/verify/inject via a synthetic
CORS-spewing subprocess, and arg-parsing edge cases (empty cmd, unknown
--source, --verbose-type flags passing through to the child).

Signal forwarding (first Ctrl-C → SIGINT to child, second → SIGKILL) is
validated by manual smoke, not here — CliRunner and pytest don't expose a
clean way to simulate two async SIGINTs without racing the test harness.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
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


def _parse_stdout_json(stdout: str) -> dict:
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    raise AssertionError(f"no JSON line on stdout: {stdout!r}")


# --- exit code propagation + capture gating --------------------------------


def test_run_success_exits_zero_no_capture(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", "true"])
    assert result.exit_code == 0
    # No state.db written — capture never fires on clean exits.
    assert not (tmp_path / ".immunize" / "state.db").exists()
    assert not (tmp_path / ".claude").exists()


def test_run_failure_captures_with_unmatched_outcome(tmp_path: Path) -> None:
    # `false` exits 1 with no stderr content; matcher has nothing to grip,
    # returns unmatched. Proves the capture path fires on non-zero exit.
    result = runner.invoke(app, ["run", "false"])
    assert result.exit_code == 1

    payload = _parse_stdout_json(result.output)
    assert payload["outcome"] == "unmatched"

    # Errors table has a row for the failure.
    conn = sqlite3.connect(str(tmp_path / ".immunize" / "state.db"))
    count = conn.execute("SELECT COUNT(*) FROM errors").fetchone()[0]
    conn.close()
    assert count == 1


def test_run_no_capture_flag_skips_match_but_still_exits_child_code(
    tmp_path: Path,
) -> None:
    result = runner.invoke(app, ["run", "--no-capture", "false"])
    assert result.exit_code == 1
    # No match JSON, no state.db, no artifact dirs.
    assert "outcome" not in result.output
    assert not (tmp_path / ".immunize" / "state.db").exists()
    assert not (tmp_path / ".claude").exists()


def test_run_propagates_arbitrary_exit_code(tmp_path: Path) -> None:
    # Exit codes other than 0/1 must propagate unmodified. Python (which
    # is guaranteed available — we're running inside it) is a more portable
    # vehicle than `bash`, which on GitHub Actions Windows runners flakes
    # depending on which bash shim is first on PATH.
    result = runner.invoke(app, ["run", sys.executable, "-c", "import sys; sys.exit(42)"])
    assert result.exit_code == 42
    # Capture still fires on non-zero exit.
    payload = _parse_stdout_json(result.output)
    assert payload["outcome"] == "unmatched"


# --- streaming preservation ------------------------------------------------


def test_run_teees_stdout_and_stderr_lines(tmp_path: Path) -> None:
    # Python subprocess writes two lines each to stdout and stderr with a
    # small sleep between. The test just confirms both lines show up in the
    # captured runner output — it's a proxy for "the tee threads worked,
    # both pipes were drained". True live-streaming verification needs
    # inter-process observation and is covered by the subprocess-timing
    # test below.
    script = (
        "import sys, time\n"
        "sys.stdout.write('OUT1\\n'); sys.stdout.flush()\n"
        "sys.stderr.write('ERR1\\n'); sys.stderr.flush()\n"
        "time.sleep(0.1)\n"
        "sys.stdout.write('OUT2\\n'); sys.stdout.flush()\n"
        "sys.stderr.write('ERR2\\n'); sys.stderr.flush()\n"
        "sys.exit(0)\n"
    )
    result = runner.invoke(app, ["run", sys.executable, "-c", script])
    assert result.exit_code == 0
    # CliRunner merges stdout + stderr; both child streams should appear.
    combined = result.output
    assert "OUT1" in combined
    assert "OUT2" in combined
    assert "ERR1" in combined
    assert "ERR2" in combined


def test_run_streams_output_live_via_subprocess(tmp_path: Path) -> None:
    # Wall-clock proof that the tee threads deliver output BEFORE the child
    # exits. Run a subprocess that emits a line, sleeps 2s, then exits. If
    # we read >=1 line out of immunize's stdout before the 2-second mark,
    # streaming is live. If the tee drained only at the end, we'd see no
    # bytes until second 2.
    script = (
        "import sys, time\n"
        "sys.stdout.write('FIRST\\n'); sys.stdout.flush()\n"
        "time.sleep(2.0)\n"
        "sys.stdout.write('SECOND\\n'); sys.stdout.flush()\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("IMMUNIZE_")}
    env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg")

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "immunize",
            "run",
            "--no-capture",
            sys.executable,
            "-c",
            script,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(tmp_path),
        env=env,
        bufsize=1,
    )
    assert proc.stdout is not None
    t0 = time.monotonic()
    first_line = proc.stdout.readline()
    first_arrival = time.monotonic() - t0

    # FIRST must arrive well before the 2s sleep inside the child.
    assert "FIRST" in first_line, f"unexpected first line: {first_line!r}"
    assert (
        first_arrival < 1.5
    ), f"first line took {first_arrival:.2f}s — teeing is not live (expected <1.5s)"

    # Let the child finish.
    proc.wait(timeout=10)
    assert proc.returncode == 0


# --- timeout ---------------------------------------------------------------


def test_run_timeout_exits_124_and_skips_capture(tmp_path: Path) -> None:
    # `--timeout 1 sleep 10` must return within ~2s wall (kill + drain),
    # exit 124, and NOT fire capture (deadline trip isn't a runtime bug).
    t0 = time.monotonic()
    result = runner.invoke(app, ["run", "--timeout", "1", "sleep", "10"])
    elapsed = time.monotonic() - t0

    assert result.exit_code == 124
    assert elapsed < 5.0, f"timeout took {elapsed:.2f}s — should kill within ~2s"
    # No match JSON emitted, no state.db persisted: timeout trip skips capture.
    assert "outcome" not in result.output
    assert not (tmp_path / ".immunize" / "state.db").exists()
    assert not (tmp_path / ".claude").exists()


# --- real match path -------------------------------------------------------


def test_run_matches_fetch_missing_credentials_on_cors_failure(tmp_path: Path) -> None:
    # Subprocess emits CORS stderr hitting the fetch-missing-credentials
    # anchors and exits 1. immunize run must match, verify, inject — same
    # end state as `immunize capture` on the equivalent payload.
    stderr_line = (
        "Access to fetch at 'https://api.example.com/me' from origin "
        "'http://localhost:3000' has been blocked by CORS policy: The value "
        "of the 'Access-Control-Allow-Credentials' header in the response is "
        "'' which must be 'true' when the request's credentials mode is 'include'."
    )
    script = "import sys\n" f"sys.stderr.write({stderr_line!r} + '\\n')\n" "sys.exit(1)\n"
    result = runner.invoke(app, ["run", sys.executable, "-c", script])
    assert result.exit_code == 1

    payload = _parse_stdout_json(result.output)
    assert payload["outcome"] == "matched_and_verified"
    assert payload["pattern_id"] == "fetch-missing-credentials"
    assert payload["pattern_origin"] == "bundled"

    # Artifacts landed in the tmp project.
    assert (tmp_path / ".claude" / "skills" / "immunize-fetch-missing-credentials").is_dir()
    assert (tmp_path / ".cursor" / "rules" / "fetch-missing-credentials.mdc").is_file()
    assert (
        tmp_path / "tests" / "immunized" / "fetch-missing-credentials" / "test_template.py"
    ).is_file()

    # SQLite row carries the pattern metadata; source is shell-wrapper.
    conn = sqlite3.connect(str(tmp_path / ".immunize" / "state.db"))
    conn.row_factory = sqlite3.Row
    art_rows = list(conn.execute("SELECT pattern_id, pattern_origin FROM artifacts"))
    err_rows = list(conn.execute("SELECT payload_json FROM errors"))
    conn.close()
    assert len(art_rows) == 1
    assert art_rows[0]["pattern_id"] == "fetch-missing-credentials"
    persisted = json.loads(err_rows[0]["payload_json"])
    assert persisted["source"] == "shell-wrapper"
    assert persisted["command"] is not None
    assert persisted["exit_code"] == 1


# --- arg parsing -----------------------------------------------------------


def test_run_empty_command_exits_usage_error(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run"])
    assert result.exit_code == 2
    assert "Usage" in result.output or "usage" in result.output


def test_run_invalid_source_exits_usage_error(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", "--source", "bogus-source", "true"])
    assert result.exit_code == 2
    assert "bogus-source" in result.output or "invalid" in result.output


def test_run_passes_unknown_flags_to_child(tmp_path: Path) -> None:
    # `--verbose` is not a known flag on `immunize run`; with
    # ignore_unknown_options it should land in ctx.args and be passed to
    # the child. Use python -c "import sys; print(sys.argv)" so we can
    # inspect what the child actually received.
    script = "import sys; print(sys.argv)"
    result = runner.invoke(
        app,
        ["run", sys.executable, "-c", script, "--verbose", "extra-arg"],
    )
    assert result.exit_code == 0
    assert "--verbose" in result.output
    assert "extra-arg" in result.output
