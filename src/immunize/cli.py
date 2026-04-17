from __future__ import annotations

import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from typing import get_args

import typer
from rich.console import Console
from rich.table import Table

from immunize import capture, inject, storage, verify
from immunize.capture import CapturePayloadError
from immunize.config import load_settings
from immunize.models import CapturePayload, Source

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
    help="Parse and persist the payload without matching. (Matcher lands in Step 6.)",
)


@app.command("capture")
def capture_cmd(
    source: str = _SOURCE_OPT,
    stdin_plain: bool = _STDIN_PLAIN_OPT,
    dry_run: bool = _DRY_RUN_OPT,  # noqa: ARG001 -- retained until Step 6 rewires orchestration
) -> None:
    """Capture a runtime error and persist it. Matcher wiring lands in Step 6.

    Always exits 0 so the parent shell/hook is never blocked.
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
        payload = _read_payload(
            stdin_plain=stdin_plain, source=source, cwd=settings.project_dir  # type: ignore[arg-type]
        )
        capture.persist(conn, payload)
        console_err.print(
            "[dim]immunize: captured — matcher wiring lands in Step 6.[/dim]"
        )
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
    table.add_column("Verified", justify="center")
    table.add_column("Test file")
    for row in rows:
        table.add_row(
            str(row.id),
            row.created_at[:10],
            row.slug,
            "[green]yes[/green]" if row.verified else "[red]no[/red]",
            Path(row.pytest_path).name if row.pytest_path else "-",
        )
    console_out.print(table)


# --- remove -----------------------------------------------------------------
@app.command("remove")
def remove_cmd(
    artifact_id: int = typer.Argument(..., help="Immunity id from `immunize list`."),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation."),
) -> None:
    """Delete an immunity's artifact files and DB row."""
    settings = load_settings()
    conn = storage.connect(settings.state_db_path)
    row = storage.get_artifact(conn, artifact_id)
    if row is None:
        console_err.print(f"[red]immunize: no immunity with id {artifact_id}[/red]")
        raise typer.Exit(1)
    if not yes and not typer.confirm(
        f"Remove immunity '{row.slug}' (id={artifact_id})?", default=False
    ):
        console_out.print("Cancelled.")
        return
    paths = inject.InjectedPaths(
        slug=row.slug,
        skill_path=Path(row.skill_path) if row.skill_path else Path(),
        cursor_rule_path=Path(row.cursor_rule_path) if row.cursor_rule_path else Path(),
        semgrep_path=Path(row.semgrep_path) if row.semgrep_path else None,
        pytest_path=Path(row.pytest_path) if row.pytest_path else Path(),
    )
    inject.remove(paths)
    storage.delete_artifact(conn, artifact_id)
    console_out.print(f"[green]Removed immunity '{row.slug}'.[/green]")


# --- verify -----------------------------------------------------------------
@app.command("verify")
def verify_cmd(
    artifact_id: int | None = typer.Argument(
        None, help="Specific immunity id; omit to verify all."
    ),
) -> None:
    """Re-run pytest against an injected immunity (or all)."""
    settings = load_settings()
    conn = storage.connect(settings.state_db_path)
    if artifact_id is not None:
        row = storage.get_artifact(conn, artifact_id)
        if row is None:
            console_err.print(f"[red]immunize: no immunity with id {artifact_id}[/red]")
            raise typer.Exit(1)
        rows = [row]
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


# --- helpers ----------------------------------------------------------------
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
