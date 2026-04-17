"""Contributor-only CLI: ``immunize author-pattern``.

This is the ONE module in the runtime src/ tree allowed to import
``anthropic``. End users never run this command; it is used by contributors
(with their own ``ANTHROPIC_API_KEY``) to draft new bundled patterns from a
``CapturePayload``-shaped error JSON. The body is a skeleton in Step 7a; the
full Claude-driven drafting flow lands in Step 7b.
"""

from __future__ import annotations

import os
from pathlib import Path

import typer
from rich.console import Console

console_err = Console(stderr=True)


def author_pattern_cmd(
    from_error: Path,
    output: Path,
    model: str | None = None,
) -> None:
    """Step 7a skeleton. Validates the API key + input file; body lands in 7b."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        console_err.print(
            "[red]ANTHROPIC_API_KEY is required.[/red] "
            "immunize author-pattern is a contributor-only tool; "
            "set the key to continue."
        )
        raise typer.Exit(1)

    console_err.print(
        "[yellow]immunize author-pattern is not implemented yet (Step 7a skeleton). "
        "Drafting + verification land in Step 7b.[/yellow]"
    )
    raise typer.Exit(1)
