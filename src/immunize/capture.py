from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any

from pydantic import ValidationError

from immunize import storage
from immunize.models import CapturePayload, Source


class CapturePayloadError(Exception):
    """Raised when stdin input cannot be parsed or validated as a CapturePayload."""


def read_payload_from_stdin(stdin: IO[str]) -> CapturePayload:
    text = stdin.read()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise CapturePayloadError(f"stdin is not valid JSON: {e}") from e
    try:
        return CapturePayload.model_validate(data)
    except ValidationError as e:
        raise CapturePayloadError(f"stdin payload failed validation: {e}") from e


def read_hook_json_from_stdin(stdin: IO[str]) -> dict[str, Any]:
    """Parse raw JSON off stdin without CapturePayload validation.

    Claude Code's PostToolUseFailure hook emits a payload with its own schema
    (tool_name, tool_input, error, …) — different from CapturePayload. We read
    the raw object here and translate via payload_from_claude_code_hook.
    """
    text = stdin.read()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise CapturePayloadError(f"hook stdin is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise CapturePayloadError(f"hook stdin must be a JSON object, got {type(data).__name__}")
    return data


def build_payload_from_plain(
    stderr_text: str, *, cwd: Path, source: Source = "manual"
) -> CapturePayload:
    return CapturePayload(
        source=source,
        stderr=stderr_text,
        exit_code=1,
        cwd=str(cwd),
        timestamp=datetime.now(timezone.utc),
        project_fingerprint=project_fingerprint_for(cwd),
    )


def payload_from_claude_code_hook(
    hook_json: dict[str, Any],
    *,
    cwd: Path,
    source: Source = "claude-code-hook",
) -> CapturePayload | None:
    """Translate a PostToolUseFailure hook JSON to a CapturePayload.

    The hook schema (code.claude.com/docs/en/hooks) delivers ``error`` (string)
    and ``is_interrupt`` (bool) at the top level — no ``tool_response`` with
    structured stderr/stdout/exit_code. We map what we have and fill reasonable
    defaults. Callers treat a ``None`` return as "skip this hook firing":
    immunize only cares about Bash failures; Edit/Write/etc. failures would
    just produce noisy unmatched captures.
    """
    if hook_json.get("tool_name") != "Bash":
        return None
    hook_cwd = hook_json.get("cwd") or str(cwd)
    tool_input = hook_json.get("tool_input") or {}
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    session_id = hook_json.get("session_id")
    error_text = hook_json.get("error") or ""
    return CapturePayload(
        source=source,
        tool_name="Bash",
        command=command if isinstance(command, str) else None,
        stdout="",
        stderr=error_text if isinstance(error_text, str) else "",
        exit_code=1,
        cwd=hook_cwd,
        timestamp=datetime.now(timezone.utc),
        project_fingerprint=project_fingerprint_for(Path(hook_cwd)),
        session_id=session_id if isinstance(session_id, str) else None,
    )


def dump_hook_payload(hook_json: dict[str, Any], project_dir: Path) -> Path | None:
    """Persist the raw hook payload for offline inspection. Best-effort.

    v0.2.0 spike: the exact shape and content of PostToolUseFailure's ``error``
    field for Bash is underspecified in the docs. Dumping every payload into
    ``.immunize/hook_payloads/`` lets contributors inspect real data and drives
    Commit 5's matcher calibration. Commit 5 gates this behind
    IMMUNIZE_DEBUG_HOOK=1 once calibration is informed.

    Returns the path written, or None on failure (never raises — a dump failure
    must not break capture's main flow).
    """
    try:
        payloads_dir = project_dir / ".immunize" / "hook_payloads"
        payloads_dir.mkdir(parents=True, exist_ok=True)
        session_id = hook_json.get("session_id")
        session_tag = str(session_id)[:8] if session_id else "nosess"
        ts = datetime.now(timezone.utc).isoformat().replace(":", "-")
        target = payloads_dir / f"{ts}-{session_tag}.json"
        tmp = target.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(hook_json, indent=2))
        os.replace(tmp, target)
        return target
    except OSError:
        return None


def project_fingerprint_for(cwd: Path) -> str:
    digest = hashlib.sha256(str(cwd.resolve()).encode()).hexdigest()[:16]
    return f"sha256-{digest}"


def persist(conn: sqlite3.Connection, payload: CapturePayload) -> int:
    return storage.insert_error(conn, payload)
