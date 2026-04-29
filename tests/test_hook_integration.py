"""End-to-end integration test for the Claude Code PostToolUseFailure hook.

The payload fixture below is NOT synthetic — it was captured from a real
Claude Code session on 2026-04-18 running in /tmp/immunize-hook-e2e after
`immunize install-hook`. The session prompted Claude to run a CORS-flavored
bash failure; Claude's Bash tool exited 1; PostToolUseFailure fired; the hook
piped the payload to `immunize capture --source claude-code-hook`; immunize
matched `fetch-missing-credentials` and injected artifacts.

Key shape facts observed (drive Commit 5's matcher calibration):

- Top-level `error` carries the full bash stderr, prefixed with `Exit code N\\n`.
  The documented generic `"Command exited with non-zero status code 1"` is a
  FALSE PREMISE for Bash failures — real payloads embed stderr substantively.
- `error` may include the stderr content twice (buffering artifact of Claude
  Code's stdout/stderr tee). Harmless for matching; doubled anchors just
  strengthen the score.
- `tool_input` contains `{command, description}` — Claude auto-generates a
  one-line description that we don't currently use but is available.
- `tool_use_id`, `session_id`, `transcript_path`, `permission_mode`,
  `hook_event_name` appear as documented.
- `is_interrupt: false` for a normal bash exit; reserved for user-initiated
  interrupts.

This test validates the full wire: real payload → subprocess `immunize
capture --source claude-code-hook` → matcher → verify → inject → SQLite →
injected pytest passes standalone.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

# Fixture: the actual JSON Claude Code PostToolUseFailure sent on 2026-04-18,
# with one field redacted (`cwd` and `transcript_path` template-ified so the
# test re-parameterizes them per-tmp_path). Everything else is byte-for-byte.
_REAL_HOOK_PAYLOAD_TEMPLATE = {
    "session_id": "fdbab6a5-a356-4681-b1c1-9244ca9637bc",
    "transcript_path": "{CWD}/.claude-transcript.jsonl",
    "cwd": "{CWD}",
    "permission_mode": "default",
    "hook_event_name": "PostToolUseFailure",
    "tool_name": "Bash",
    "tool_input": {
        "command": (
            "echo \"Access to fetch at 'https://api.example.com/me' from origin "
            "'http://localhost:3000' has been blocked by CORS policy: The value "
            "of the 'Access-Control-Allow-Credentials' header in the response is "
            "'' which must be 'true' when the request's credentials mode is "
            "'include'.\" >&2 && exit 1"
        ),
        "description": "Print a CORS error message to stderr and exit with code 1",
    },
    "tool_use_id": "toolu_01W3mvgXpdwZQXxMp5Apgk7q",
    # `error` carries the full stderr. The real payload contained the message
    # twice; we keep that faithful so the test exercises the duplicate-anchor
    # case the matcher actually sees in production.
    "error": (
        "Exit code 1\n"
        "Access to fetch at 'https://api.example.com/me' from origin "
        "'http://localhost:3000' has been blocked by CORS policy: The value "
        "of the 'Access-Control-Allow-Credentials' header in the response is "
        "'' which must be 'true' when the request's credentials mode is "
        "'include'.\n\n"
        "Access to fetch at 'https://api.example.com/me' from origin "
        "'http://localhost:3000' has been blocked by CORS policy: The value "
        "of the 'Access-Control-Allow-Credentials' header in the response is "
        "'' which must be 'true' when the request's credentials mode is "
        "'include'."
    ),
    "is_interrupt": False,
}


def _materialise_payload(cwd: Path) -> str:
    """Fill the {CWD} placeholders and return the JSON string Claude Code would send.

    Substitution happens on the dict — not on the serialized JSON — because
    on Windows `str(cwd)` contains backslashes that would be parsed as JSON
    escape sequences (\\U, \\A, …) on the second json.loads.
    """
    cwd_str = str(cwd)
    rendered = {
        **_REAL_HOOK_PAYLOAD_TEMPLATE,
        "transcript_path": _REAL_HOOK_PAYLOAD_TEMPLATE["transcript_path"].replace("{CWD}", cwd_str),
        "cwd": cwd_str,
    }
    return json.dumps(rendered)


def test_real_claude_code_hook_payload_matches_verifies_injects(tmp_path: Path) -> None:
    """Pipe the observed-in-the-wild hook payload through a real subprocess
    invocation of `immunize capture --source claude-code-hook` — the same wire
    Claude Code uses when the hook fires.
    """
    payload_json = _materialise_payload(tmp_path)

    env = {k: v for k, v in os.environ.items() if not k.startswith("IMMUNIZE_")}
    env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg")
    # Diagnostic hook-payload dumps are gated behind this env in v0.2.0; the
    # integration test explicitly opts in so it can assert the dump lands.
    env["IMMUNIZE_DEBUG_HOOK"] = "1"

    proc = subprocess.run(
        [sys.executable, "-m", "immunize", "capture", "--source", "claude-code-hook"],
        input=payload_json,
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"immunize exited {proc.returncode}\n" f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )

    # Exactly one JSON line on stdout. It must be the matched_and_verified shape.
    stdout_lines = [ln for ln in proc.stdout.splitlines() if ln.strip().startswith("{")]
    assert len(stdout_lines) == 1, f"expected 1 JSON line, got {stdout_lines!r}"
    result = json.loads(stdout_lines[0])
    assert result["outcome"] == "matched_and_verified"
    assert result["verified"] is True
    assert result["pattern_id"] == "fetch-missing-credentials"
    assert result["pattern_origin"] == "bundled"
    assert result["confidence"] >= 0.75

    # Three artifacts landed in the tmp project tree (real paths).
    skill = Path(result["artifacts"]["skill"])
    cursor = Path(result["artifacts"]["cursor_rule"])
    pytest_path = Path(result["artifacts"]["pytest"])
    assert skill.is_file() and skill.name == "SKILL.md"
    assert cursor.is_file() and cursor.suffix == ".mdc"
    assert pytest_path.is_file() and pytest_path.name == "test_template.py"
    # Injected into the tmp project, not anywhere else.
    assert tmp_path in skill.parents
    assert tmp_path in cursor.parents
    assert tmp_path in pytest_path.parents

    # SQLite row written with pattern metadata.
    conn = sqlite3.connect(str(tmp_path / ".immunize" / "state.db"))
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute("SELECT pattern_id, pattern_origin, verified FROM artifacts"))
    conn.close()
    assert len(rows) == 1
    assert rows[0]["pattern_id"] == "fetch-missing-credentials"
    assert rows[0]["pattern_origin"] == "bundled"
    assert bool(rows[0]["verified"]) is True

    # Hook payload got dumped for offline inspection (diagnostic introduced in step 2).
    dumps = list((tmp_path / ".immunize" / "hook_payloads").glob("*.json"))
    assert len(dumps) == 1
    dumped = json.loads(dumps[0].read_text())
    assert dumped["session_id"] == "fdbab6a5-a356-4681-b1c1-9244ca9637bc"
    assert dumped["hook_event_name"] == "PostToolUseFailure"
    assert dumped["tool_name"] == "Bash"

    # Injected pytest passes when executed standalone — i.e. the fixture on disk
    # reflects the fix, not the repro, post-inject. Mirrors the FAIL→PASS→FAIL
    # dual-run that scripts/pattern_lint.py runs at authoring time.
    inject_test = subprocess.run(
        [sys.executable, "-m", "pytest", str(pytest_path), "-x", "-q", "--no-header"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert (
        inject_test.returncode == 0
    ), f"injected pytest failed:\nstdout: {inject_test.stdout}\nstderr: {inject_test.stderr}"


def test_real_hook_payload_shape_documents_error_prefix(tmp_path: Path) -> None:
    """Regression test pinning the one piece of schema the docs got wrong.

    The official hook docs claim the failure payload's `error` is a short
    string like 'Command exited with non-zero status code 1'. The reality
    (observed 2026-04-18) is 'Exit code N\\n<full stderr>' — sometimes with
    the stderr embedded twice. Pin this so regressions are loud and a future
    Claude Code schema change forces us to update the translator.
    """
    payload = json.loads(_materialise_payload(tmp_path))
    assert payload["error"].startswith("Exit code 1\n")
    assert "Access-Control-Allow-Credentials" in payload["error"]
    assert "credentials mode is 'include'" in payload["error"]
    # Top-level shape matches official schema.
    for key in (
        "session_id",
        "transcript_path",
        "cwd",
        "permission_mode",
        "hook_event_name",
        "tool_name",
        "tool_input",
        "tool_use_id",
        "error",
        "is_interrupt",
    ):
        assert key in payload, f"official docs field {key!r} missing from observed payload"
    assert payload["hook_event_name"] == "PostToolUseFailure"
    assert payload["tool_name"] == "Bash"
    assert "command" in payload["tool_input"]


def test_subprocess_entrypoint_is_python_m_immunize() -> None:
    """Smoke check that the entrypoint Claude Code's hook command relies on
    (``immunize`` on PATH, which is equivalent to ``python -m immunize``)
    exists and ``--help`` exits 0. If this regresses, install-hook's written
    command becomes a dead reference.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "immunize", "capture", "--help"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0
    assert "capture" in proc.stdout.lower()
