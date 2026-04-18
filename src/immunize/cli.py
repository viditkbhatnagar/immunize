from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import get_args

import typer
from rich.console import Console
from rich.table import Table

from immunize import capture, inject, matcher, storage, verify
from immunize.capture import CapturePayloadError
from immunize.config import load_settings
from immunize.models import CapturePayload, Source

# Bundled patterns ship inside the installed package tree.
_BUNDLED_PATTERNS_DIR = Path(matcher.__file__).resolve().parent / "patterns"

# Single source of truth: the Source Literal in models.py. get_args resolves
# to the tuple of member strings at runtime; frozenset gives us O(1) membership
# tests against arbitrary user input from --source.
_VALID_SOURCES: frozenset[str] = frozenset(get_args(Source))

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="immunize — turn runtime errors into verified cross-tool immunity artifacts.",
)
console_out = Console()
console_err = Console(stderr=True)


@app.callback()
def _guard() -> None:
    """Global guard registered once — no per-command duplication."""
    if sys.platform == "win32":
        console_err.print(
            "immunize does not yet support Windows. "
            "Track https://github.com/viditkbhatnagar/immunize/issues for Windows support."
        )
        raise typer.Exit(1)


# --- capture ----------------------------------------------------------------
_SOURCE_OPT = typer.Option("manual", "--source")
_STDIN_PLAIN_OPT = typer.Option(
    False, "--stdin-plain", help="Read raw stderr from stdin instead of JSON."
)
_DRY_RUN_OPT = typer.Option(
    False,
    "--dry-run",
    help="Match + verify, but do not inject artifacts or write the SQLite row.",
)


@app.command("capture")
def capture_cmd(
    source: str = _SOURCE_OPT,
    stdin_plain: bool = _STDIN_PLAIN_OPT,
    dry_run: bool = _DRY_RUN_OPT,
) -> None:
    """Match the payload against bundled + local patterns; verify and inject.

    JSON stdout contract — exactly one line, one of these shapes:

      {"outcome": "unmatched", "matched": false, "can_author_locally": true}

      {"outcome": "matched_and_verified", "matched": true, "verified": true,
        "pattern_id": <str>, "pattern_origin": "bundled"|"local"|"community",
        "confidence": <float>,
        "artifacts": {"skill": <abs>, "cursor_rule": <abs>, "pytest": <abs>}}

      {"outcome": "matched_and_verified", "matched": true, "verified": true,
        "pattern_id": <str>, "pattern_origin": <str>, "confidence": <float>,
        "dry_run": true, "artifacts": {}}                    # only with --dry-run

      {"outcome": "matched_verify_failed", "matched": true, "verified": false,
        "pattern_id": <str>, "pattern_origin": <str>, "confidence": <float>,
        "reason": <str>}

    Rich output goes to stderr via Console(stderr=True). Only JSON goes to stdout.
    Exit code is always 0 unless the CLI invocation itself is broken.
    """
    project_dir = Path.cwd()
    try:
        if source not in _VALID_SOURCES:
            console_err.print(
                f"[red]immunize: invalid --source {source!r}; "
                f"expected one of {_VALID_SOURCES}[/red]"
            )
            return
        settings = load_settings()
        project_dir = settings.project_dir
        conn = storage.connect(settings.state_db_path)

        # Claude Code PostToolUseFailure hook speaks a different stdin contract
        # than manual/shell-wrapper captures: a hook JSON object with tool_name,
        # tool_input, error, etc. — not a CapturePayload. Read it raw, dump for
        # offline inspection, translate, and bail early on non-Bash failures.
        if source == "claude-code-hook":
            hook_json = capture.read_hook_json_from_stdin(sys.stdin)
            # Payload dump is a diagnostic for contributors calibrating matcher
            # recall — not something normal users should accumulate on disk.
            # Gated behind IMMUNIZE_DEBUG_HOOK=1 in v0.2.0 after Commit 4
            # empirically confirmed the payload shape.
            if os.environ.get("IMMUNIZE_DEBUG_HOOK") == "1":
                capture.dump_hook_payload(hook_json, settings.project_dir)
            translated = capture.payload_from_claude_code_hook(hook_json, cwd=settings.project_dir)
            if translated is None:
                _emit_json(
                    {
                        "outcome": "skipped",
                        "reason": "non-Bash tool failure",
                        "tool_name": hook_json.get("tool_name"),
                    }
                )
                return
            payload = translated
        else:
            payload = _read_payload(
                stdin_plain=stdin_plain, source=source, cwd=settings.project_dir
            )
        capture.persist(conn, payload)
        _apply_payload(payload, settings, conn, dry_run=dry_run)
    except CapturePayloadError as e:
        console_err.print(f"[red]immunize: invalid capture payload[/red]\n{e}")
        console_err.print(
            "[yellow]Expected a JSON object matching CapturePayload "
            "(keys: source, stderr, exit_code, cwd, timestamp, project_fingerprint).[/yellow]"
        )
    except typer.Exit:
        raise
    except Exception as e:  # noqa: BLE001 -- intentional: capture must never raise
        console_err.print(f"[red]immunize: unexpected error: {e}[/red]")
        _append_error_log(project_dir, e)


# --- list -------------------------------------------------------------------
@app.command("list")
def list_cmd() -> None:
    """Print all active immunities in this project."""
    settings = load_settings()
    conn = storage.connect(settings.state_db_path)
    rows = storage.list_artifacts(conn)
    if not rows:
        console_out.print("No immunities.")
        return
    table = Table(title="Immunities", show_lines=False)
    table.add_column("ID", justify="right")
    table.add_column("Date")
    table.add_column("Slug")
    table.add_column("Pattern")
    table.add_column("Verified", justify="center")
    table.add_column("Test file")
    for row in rows:
        table.add_row(
            str(row.id),
            row.created_at[:10],
            row.slug,
            f"{row.pattern_id or '-'} ({row.pattern_origin or '-'})",
            "[green]yes[/green]" if row.verified else "[red]no[/red]",
            Path(row.pytest_path).name if row.pytest_path else "-",
        )
    console_out.print(table)


# --- remove -----------------------------------------------------------------
@app.command("remove")
def remove_cmd(
    identifier: str = typer.Argument(..., help="Immunity id OR pattern slug from `immunize list`."),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation."),
) -> None:
    """Delete an immunity's artifact files and DB row.

    Accepts either an integer id or a pattern slug. If a slug resolves to more
    than one injected record, the command lists the candidate ids and exits 1
    so the user can disambiguate — removal is destructive and we won't guess.
    """
    settings = load_settings()
    conn = storage.connect(settings.state_db_path)
    matches = _resolve_identifier(identifier, conn)
    if not matches:
        console_err.print(f"[red]immunize: no immunity matches {identifier!r}[/red]")
        raise typer.Exit(1)
    if len(matches) > 1:
        console_err.print(
            f"[yellow]immunize: {len(matches)} immunities match slug {identifier!r}:[/yellow]"
        )
        for match in matches:
            console_err.print(f"  id={match.id}  slug={match.slug}  created={match.created_at}")
        console_err.print("[yellow]Re-run `immunize remove <id>` with a specific id.[/yellow]")
        raise typer.Exit(1)

    row = matches[0]
    if not yes and not typer.confirm(f"Remove immunity '{row.slug}' (id={row.id})?", default=False):
        console_out.print("Cancelled.")
        return
    pytest_path_obj = Path(row.pytest_path) if row.pytest_path else Path()
    paths = inject.InjectedPaths(
        slug=row.slug,
        skill_path=Path(row.skill_path) if row.skill_path else Path(),
        cursor_rule_path=Path(row.cursor_rule_path) if row.cursor_rule_path else Path(),
        semgrep_path=Path(row.semgrep_path) if row.semgrep_path else None,
        pytest_dir=pytest_path_obj.parent,
        pytest_path=pytest_path_obj,
    )
    inject.remove(paths)
    storage.delete_artifact(conn, row.id)
    console_out.print(f"[green]Removed immunity '{row.slug}'.[/green]")


# --- verify -----------------------------------------------------------------
@app.command("verify")
def verify_cmd(
    identifier: str | None = typer.Argument(
        None, help="Immunity id OR pattern slug; omit to verify all."
    ),
) -> None:
    """Re-run pytest against an injected immunity (or all).

    Accepts either an integer id or a pattern slug. Since verify is read-only,
    a slug that matches multiple records verifies all of them.
    """
    settings = load_settings()
    conn = storage.connect(settings.state_db_path)
    if identifier is not None:
        rows = _resolve_identifier(identifier, conn)
        if not rows:
            console_err.print(f"[red]immunize: no immunity matches {identifier!r}[/red]")
            raise typer.Exit(1)
    else:
        rows = storage.list_artifacts(conn)

    if not rows:
        console_out.print("No immunities to verify.")
        return

    table = Table(title="Verification", show_lines=False)
    table.add_column("ID", justify="right")
    table.add_column("Slug")
    table.add_column("Status")
    table.add_column("Message")

    any_failed = False
    for row in rows:
        pytest_path = Path(row.pytest_path) if row.pytest_path else None
        if pytest_path is None or not pytest_path.exists():
            table.add_row(str(row.id), row.slug, "[yellow]SKIP[/yellow]", "pytest file missing")
            any_failed = True
            continue
        result = verify.verify_artifact_on_disk(pytest_path, settings)
        if result.passed:
            table.add_row(str(row.id), row.slug, "[green]PASS[/green]", "")
        else:
            table.add_row(str(row.id), row.slug, "[red]FAIL[/red]", result.error_message or "")
            any_failed = True

    console_out.print(table)
    if any_failed:
        raise typer.Exit(1)


# --- install-skill ----------------------------------------------------------
_PROJECT_DIR_OPT = typer.Option(
    None,
    "--project-dir",
    help="Directory to install into. Defaults to the current working directory.",
)
_FORCE_OPT = typer.Option(
    False,
    "--force",
    help="Overwrite an existing SKILL.md whose bytes differ from the bundled skill.",
)


@app.command("install-skill")
def install_skill_cmd(
    project_dir: Path | None = _PROJECT_DIR_OPT,
    force: bool = _FORCE_OPT,
) -> None:
    """Copy the bundled immunize-manager skill into a project's .claude/skills/.

    Idempotent: if the destination file already exists with identical bytes,
    exits 0 with no change. If it exists with different bytes, exits 1 unless
    --force is passed.
    """
    from immunize.skill_install import SkillInstallError, install_skill

    target = project_dir if project_dir is not None else Path.cwd()
    try:
        result = install_skill(target, force=force)
    except SkillInstallError as exc:
        console_err.print(f"[red]immunize: {exc}[/red]")
        raise typer.Exit(1) from exc

    if result.action == "installed":
        console_out.print(f"Installed immunize-manager skill to {result.destination}")
    elif result.action == "overwritten":
        console_out.print(f"Overwrote immunize-manager skill at {result.destination}")
    elif result.action == "unchanged":
        console_out.print(
            f"immunize-manager skill already installed at {result.destination} (no change)"
        )


# --- install-hook -----------------------------------------------------------
_HOOK_PROJECT_DIR_OPT = typer.Option(
    None,
    "--project-dir",
    help="Directory to install into. Defaults to the current working directory.",
)
_HOOK_FORCE_OPT = typer.Option(
    False,
    "--force",
    help="Overwrite an existing immunize hook entry whose command differs from the canonical one.",
)


@app.command("install-hook")
def install_hook_cmd(
    project_dir: Path | None = _HOOK_PROJECT_DIR_OPT,
    force: bool = _HOOK_FORCE_OPT,
) -> None:
    """Register a Claude Code PostToolUseFailure hook that auto-captures bash failures.

    Writes (or merges into) the project-scope ``.claude/settings.json``. Existing
    hooks on other events, and existing PostToolUseFailure entries that aren't
    ours, are preserved. Idempotent: running twice is a no-op.

    Also adds ``hook_payloads/`` to ``.immunize/.gitignore`` so debug dumps
    written by the hook don't land in commits.
    """
    from immunize.hook_installer import install_claude_code_hook

    target = project_dir if project_dir is not None else Path.cwd()
    result = install_claude_code_hook(target, force=force)

    if result.status == "installed":
        console_out.print(f"Installed Claude Code hook at {result.settings_path}")
        console_out.print("Restart Claude Code for the hook to take effect.")
    elif result.status == "overwritten":
        console_out.print(f"Overwrote immunize hook at {result.settings_path}")
        console_out.print("Restart Claude Code for the hook to take effect.")
    elif result.status == "already_installed":
        console_out.print(f"immunize hook already installed at {result.settings_path}; no change.")
    else:
        console_err.print(f"[red]immunize install-hook: {result.error}[/red]")
        raise typer.Exit(1)


# --- author-pattern ---------------------------------------------------------
_FROM_ERROR_OPT = typer.Option(..., "--from-error", exists=True, dir_okay=False)
_OUTPUT_OPT = typer.Option(..., "--output", file_okay=False)
_MODEL_OPT = typer.Option(None, "--model")


@app.command("author-pattern")
def author_pattern_cli(
    from_error: Path = _FROM_ERROR_OPT,
    output: Path = _OUTPUT_OPT,
    model: str | None = _MODEL_OPT,
) -> None:
    """Draft a new bundled pattern from a CapturePayload error JSON (contributor-only).

    Requires ANTHROPIC_API_KEY. End users never run this; it is the authoring tool
    used by contributors to add patterns. Lazy-imports `anthropic` inside the
    forwarded function so `immunize capture` never drags the SDK into its import graph.
    """
    from immunize.authoring.cli_author import author_pattern_cmd

    author_pattern_cmd(from_error=from_error, output=output, model=model)


# --- run --------------------------------------------------------------------
_RUN_NO_CAPTURE_OPT = typer.Option(
    False,
    "--no-capture",
    help="Run the command but skip capture/match on failure.",
)
_RUN_SOURCE_OPT = typer.Option(
    "shell-wrapper",
    "--source",
    help="Source label recorded on the CapturePayload when capture fires.",
)
_RUN_TIMEOUT_OPT = typer.Option(
    None,
    "--timeout",
    help="Kill the subprocess after N seconds; exit 124 on trip, no capture.",
)


@app.command(
    "run",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def run_cmd(
    ctx: typer.Context,
    no_capture: bool = _RUN_NO_CAPTURE_OPT,
    source: str = _RUN_SOURCE_OPT,
    timeout: int | None = _RUN_TIMEOUT_OPT,
) -> None:
    """Run a command; on non-zero exit, auto-capture its output for matching.

    Fallback automation path for environments without the Claude Code hook
    (Cursor, bare terminals, CI, Codex). Wraps any command: stdout and stderr
    stream live to your terminal, and on non-zero exit the captured bytes
    feed the matcher — the same pipeline `immunize capture` uses.

    The subprocess's exit code is propagated. A `--timeout` trip exits 124
    and does NOT fire capture (a missed deadline isn't a runtime bug worth
    persisting an immunity against).

    ``immunize run`` consumes its own flags before the child command; any
    flags belonging to the child are passed through because the command
    uses `ignore_unknown_options`. Example:

        immunize run --timeout 60 pytest --verbose tests/

    Here `--timeout 60` is consumed by immunize and `--verbose tests/` is
    passed to pytest.
    """
    from immunize.runner import run_with_capture

    cmd = list(ctx.args)
    if not cmd:
        console_err.print("[red]Usage: immunize run [OPTIONS] <cmd> [args...][/red]")
        raise typer.Exit(2)

    if source not in _VALID_SOURCES:
        console_err.print(
            f"[red]immunize: invalid --source {source!r}; "
            f"expected one of {_VALID_SOURCES}[/red]"
        )
        raise typer.Exit(2)

    result = run_with_capture(cmd, timeout=timeout)

    # Never capture on: clean exit, --no-capture, or --timeout. Always
    # propagate the child's exit code. A timeout is a deadline decision,
    # not a runtime bug.
    if result.exit_code == 0 or no_capture or result.timed_out:
        raise typer.Exit(result.exit_code)

    # Capture path: construct a CapturePayload from buffers and run the same
    # match/verify/inject flow as `immunize capture`.
    try:
        settings = load_settings()
        conn = storage.connect(settings.state_db_path)
        base = capture.build_payload_from_plain(
            result.stderr,
            cwd=settings.project_dir,
            source=source,  # type: ignore[arg-type]
        )
        payload = base.model_copy(
            update={
                "stdout": result.stdout,
                "command": " ".join(cmd),
                "exit_code": result.exit_code,
            }
        )
        capture.persist(conn, payload)
        _apply_payload(payload, settings, conn, dry_run=False)
    except Exception as e:  # noqa: BLE001 -- capture must never mask the child's exit
        console_err.print(f"[red]immunize: unexpected error during capture: {e}[/red]")
        _append_error_log(Path.cwd(), e)

    raise typer.Exit(result.exit_code)


# --- helpers ----------------------------------------------------------------
def _apply_payload(
    payload: CapturePayload,
    settings,  # type: ignore[no-untyped-def]
    conn,  # type: ignore[no-untyped-def]
    *,
    dry_run: bool = False,
) -> None:
    """Match → verify → inject → emit-JSON against a pre-persisted payload.

    Shared between `capture` and `run`. Emits exactly one JSON line on stdout
    per the contract in capture_cmd's docstring; Rich output goes to stderr.
    """
    patterns = matcher.load_patterns(
        _BUNDLED_PATTERNS_DIR,
        settings.local_patterns_dir,
    )
    results = matcher.match(payload, patterns)
    applicable = [m for m in results if m.confidence >= settings.min_match_confidence]

    if not applicable:
        _emit_json({"outcome": "unmatched", "matched": False, "can_author_locally": True})
        console_err.print(
            "[yellow]immunize: no pattern matched — Claude Code can draft a "
            "local pattern via the immunize-manager skill.[/yellow]"
        )
        return

    top = applicable[0]
    try:
        vresult = verify.verify(top.pattern, settings)
    except Exception as exc:  # noqa: BLE001 -- verify must never crash capture
        console_err.print(f"[red]immunize: verify raised for {top.pattern.id}: {exc}[/red]")
        _emit_json(
            {
                "outcome": "matched_verify_failed",
                "matched": True,
                "verified": False,
                "pattern_id": top.pattern.id,
                "pattern_origin": top.pattern.origin,
                "confidence": top.confidence,
                "reason": f"verify raised: {exc}",
            }
        )
        return

    if not vresult.passed:
        reason = (vresult.error_message or "verify failed")[:500]
        console_err.print(f"[red]immunize: verify failed for {top.pattern.id}: {reason}[/red]")
        _emit_json(
            {
                "outcome": "matched_verify_failed",
                "matched": True,
                "verified": False,
                "pattern_id": top.pattern.id,
                "pattern_origin": top.pattern.origin,
                "confidence": top.confidence,
                "reason": reason,
            }
        )
        return

    if dry_run:
        console_err.print(
            f"[cyan]immunize: --dry-run — matched {top.pattern.id} "
            f"(confidence={top.confidence:.2f}); skipping inject.[/cyan]"
        )
        _emit_json(
            {
                "outcome": "matched_and_verified",
                "matched": True,
                "verified": True,
                "pattern_id": top.pattern.id,
                "pattern_origin": top.pattern.origin,
                "confidence": top.confidence,
                "dry_run": True,
                "artifacts": {},
            }
        )
        return

    paths = inject.inject(top.pattern, project_dir=settings.project_dir, conn=conn)
    storage.insert_match(
        conn,
        slug=paths.slug,
        pattern_id=top.pattern.id,
        pattern_origin=top.pattern.origin,
        paths=paths.as_db_dict(),
        verified=True,
    )
    _emit_json(
        {
            "outcome": "matched_and_verified",
            "matched": True,
            "verified": True,
            "pattern_id": top.pattern.id,
            "pattern_origin": top.pattern.origin,
            "confidence": top.confidence,
            "artifacts": {
                "skill": str(paths.skill_path),
                "cursor_rule": str(paths.cursor_rule_path),
                "pytest": str(paths.pytest_path),
            },
        }
    )
    console_err.print(
        f"[green]✓ Immunized against {top.pattern.id} " f"(confidence={top.confidence:.2f})[/green]"
    )


def _resolve_identifier(raw: str, conn) -> list[storage.ArtifactRow]:
    """Resolve a CLI identifier (int id or pattern slug) to matching rows.

    Digit-only strings are treated as ids and look up a single record (or
    empty). Anything else is treated as a slug and returns every record with
    that slug — multi-match happens when the user's project has been
    re-immunized against the same pattern with ``--force``.
    """
    if raw.isdigit():
        row = storage.get_artifact(conn, int(raw))
        return [row] if row else []
    return [r for r in storage.list_artifacts(conn) if r.slug == raw]


def _emit_json(obj: dict) -> None:
    """Write exactly one line of JSON to stdout. Never through Rich."""
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _read_payload(*, stdin_plain: bool, source: Source, cwd: Path) -> CapturePayload:
    if stdin_plain:
        return capture.build_payload_from_plain(sys.stdin.read(), cwd=cwd, source=source)
    payload = capture.read_payload_from_stdin(sys.stdin)
    # If the payload says "manual" but the user passed --source, honor the CLI flag.
    if source != "manual":
        payload = payload.model_copy(update={"source": source})
    return payload


def _append_error_log(project_dir: Path, exc: BaseException) -> None:
    log_dir = project_dir / ".immunize"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "errors.log").open("a") as f:
            f.write(f"\n--- {datetime.now(timezone.utc).isoformat()} ---\n")
            f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    except Exception:  # noqa: BLE001 -- last-resort logger: swallow everything
        pass


__all__ = ["app"]
