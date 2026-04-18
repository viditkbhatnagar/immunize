"""Install a PostToolUseFailure hook into a project's Claude Code settings.

The hook fires on every failed Bash tool call and pipes the hook JSON into
``immunize capture --source claude-code-hook``. One-time setup; subsequent
failures auto-capture without any prompting of Claude.

Scope: project-scope ``.claude/settings.json`` so the hook is committable and
shared with teammates. User-scope settings at ``~/.claude/settings.json`` are
intentionally left alone — a user-scope hook would fire in every project the
user opens, including ones that don't have ``immunize`` on PATH.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Canonical command. Users who want to extend it (e.g. adding --project-dir)
# can edit the settings file manually; --force lets them overwrite our entry
# back to canonical form.
HOOK_COMMAND = "immunize capture --source claude-code-hook"


@dataclass(frozen=True)
class InstallResult:
    """Outcome of an install attempt. ``status`` is one of:

    - ``installed``         — we wrote our hook into a fresh or hook-free file.
    - ``already_installed`` — an entry with the canonical command + matcher
                              was already present; no change.
    - ``overwritten``       — ``--force`` replaced an immunize entry whose
                              command had drifted from the canonical one.
    - ``error``             — filesystem, JSON parse, or schema failure;
                              see ``error`` for details.
    """

    status: str
    settings_path: Path
    error: str | None = None


def install_claude_code_hook(project_dir: Path, *, force: bool = False) -> InstallResult:
    """Merge a PostToolUseFailure Bash hook into ``<project_dir>/.claude/settings.json``.

    Idempotent. Preserves any existing hooks on other events and any existing
    PostToolUseFailure entries that aren't ours (matcher != "Bash", or command
    not starting with ``immunize capture``).
    """
    settings_path = project_dir / ".claude" / "settings.json"

    try:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return InstallResult(status="error", settings_path=settings_path, error=str(exc))

    existing: dict[str, Any]
    if settings_path.exists():
        try:
            raw = settings_path.read_text() or "{}"
            parsed = json.loads(raw) if raw.strip() else {}
        except (OSError, json.JSONDecodeError) as exc:
            return InstallResult(status="error", settings_path=settings_path, error=str(exc))
        if not isinstance(parsed, dict):
            return InstallResult(
                status="error",
                settings_path=settings_path,
                error=(
                    f"expected top-level JSON object in {settings_path}, "
                    f"got {type(parsed).__name__}"
                ),
            )
        existing = parsed
    else:
        existing = {}

    hooks = existing.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        return InstallResult(
            status="error",
            settings_path=settings_path,
            error=f"`hooks` in {settings_path} is not a JSON object",
        )

    events = hooks.setdefault("PostToolUseFailure", [])
    if not isinstance(events, list):
        return InstallResult(
            status="error",
            settings_path=settings_path,
            error=f"`hooks.PostToolUseFailure` in {settings_path} is not a JSON array",
        )

    our_entry: dict[str, Any] = {
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": HOOK_COMMAND}],
    }

    # Find an immunize-authored entry if present. Ownership signal: first
    # command in the entry's hooks array starts with "immunize capture".
    matched_index: int | None = None
    already_canonical = False
    for i, entry in enumerate(events):
        if not isinstance(entry, dict):
            continue
        inner = entry.get("hooks")
        if not isinstance(inner, list) or not inner:
            continue
        first = inner[0]
        if not isinstance(first, dict):
            continue
        cmd = first.get("command")
        if not isinstance(cmd, str) or not cmd.startswith("immunize capture"):
            continue
        matched_index = i
        already_canonical = (
            cmd == HOOK_COMMAND
            and entry.get("matcher") == "Bash"
            and len(inner) == 1
            and first.get("type") == "command"
        )
        break

    status: str
    if matched_index is not None:
        if already_canonical:
            return InstallResult(status="already_installed", settings_path=settings_path)
        if not force:
            return InstallResult(
                status="error",
                settings_path=settings_path,
                error=(
                    f"an immunize hook entry already exists in {settings_path} "
                    f"with a non-canonical command; pass --force to overwrite."
                ),
            )
        events[matched_index] = our_entry
        status = "overwritten"
    else:
        events.append(our_entry)
        status = "installed"

    # Atomic write: PID-suffixed temp + os.replace, mirroring inject.py's
    # ``_atomic_write_text`` so a concurrent Claude Code session or another
    # immunize process can't observe a partial file.
    try:
        rendered = json.dumps(existing, indent=2, ensure_ascii=False) + "\n"
        tmp = settings_path.with_suffix(settings_path.suffix + f".{os.getpid()}.tmp")
        tmp.write_text(rendered)
        os.replace(tmp, settings_path)
    except OSError as exc:
        return InstallResult(status="error", settings_path=settings_path, error=str(exc))

    # Gitignore the hook-payload dumps so they never land in a commit.
    # Best-effort: if .immunize/ can't be created we still return success on
    # the primary install.
    try:
        immunize_dir = project_dir / ".immunize"
        immunize_dir.mkdir(parents=True, exist_ok=True)
        gitignore = immunize_dir / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("hook_payloads/\n")
    except OSError:
        pass

    return InstallResult(status=status, settings_path=settings_path)
