"""Copy the bundled immunize-manager skill into a user's project.

Separated from cli.py so the logic is unit-testable without invoking Typer.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

SKILL_REL_PATH = Path(".claude/skills/immunize-manager/SKILL.md")


class SkillInstallError(Exception):
    """Raised when install refuses to overwrite existing, drifted content."""


@dataclass(frozen=True)
class InstallResult:
    destination: Path
    action: str  # "installed" | "unchanged" | "overwritten"


def bundled_skill_bytes() -> bytes:
    """Return the bundled SKILL.md as bytes, read from package data."""
    resource = files("immunize") / "skill_assets" / "immunize-manager" / "SKILL.md"
    return resource.read_bytes()


def install_skill(project_dir: Path, *, force: bool = False) -> InstallResult:
    """Copy the bundled skill to <project_dir>/.claude/skills/immunize-manager/SKILL.md.

    Rules:
      - Destination absent                              → write, return action="installed".
      - Destination present, identical bytes            → no write, return action="unchanged".
      - Destination present, different bytes, no force  → raise SkillInstallError.
      - Destination present, different bytes, force     → overwrite, return action="overwritten".
    """
    if not project_dir.exists():
        raise SkillInstallError(f"project directory does not exist: {project_dir}")
    if not project_dir.is_dir():
        raise SkillInstallError(f"project path is not a directory: {project_dir}")

    dest = project_dir / SKILL_REL_PATH
    bundled = bundled_skill_bytes()

    if dest.exists():
        if force:
            dest.write_bytes(bundled)
            return InstallResult(destination=dest, action="overwritten")
        if dest.read_bytes() == bundled:
            return InstallResult(destination=dest, action="unchanged")
        raise SkillInstallError(
            f"skill exists with different content at {dest}; " "rerun with --force to overwrite"
        )

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(bundled)
    return InstallResult(destination=dest, action="installed")
