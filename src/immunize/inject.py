from __future__ import annotations

import contextlib
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from immunize import storage
from immunize.models import CapturePayload, Diagnosis, GeneratedArtifacts


class SlugExhaustedError(Exception):
    """Raised when resolve_slug exhausts its 99-collision budget."""


@dataclass(frozen=True)
class InjectedPaths:
    slug: str
    skill_path: Path
    cursor_rule_path: Path
    semgrep_path: Path | None
    pytest_path: Path

    def as_db_dict(self) -> dict[str, str | None]:
        return {
            "skill_path": str(self.skill_path),
            "cursor_rule_path": str(self.cursor_rule_path),
            "semgrep_path": str(self.semgrep_path) if self.semgrep_path else None,
            "pytest_path": str(self.pytest_path),
        }


def inject(
    artifacts: GeneratedArtifacts,
    diagnosis: Diagnosis,
    payload: CapturePayload,
    *,
    conn: sqlite3.Connection,
) -> InjectedPaths:
    project_dir = Path(payload.cwd).resolve()
    slug = resolve_slug(conn, diagnosis.slug, project_dir=project_dir)
    paths = _target_paths(project_dir, slug, include_semgrep=artifacts.semgrep_yaml is not None)

    _atomic_write_text(paths.skill_path, artifacts.skill_md)
    _atomic_write_text(paths.cursor_rule_path, artifacts.cursor_rule)
    _atomic_write_text(paths.pytest_path, artifacts.pytest_code)
    if paths.semgrep_path and artifacts.semgrep_yaml:
        _atomic_write_text(paths.semgrep_path, artifacts.semgrep_yaml)

    return paths


def remove(paths: InjectedPaths) -> None:
    """Delete artifact files. Tolerant of missing files."""
    for p in [paths.skill_path, paths.cursor_rule_path, paths.semgrep_path, paths.pytest_path]:
        if p is None:
            continue
        with contextlib.suppress(FileNotFoundError):
            p.unlink()
    # Best-effort cleanup of now-empty parent dirs.
    for p in [paths.skill_path, paths.cursor_rule_path, paths.semgrep_path, paths.pytest_path]:
        if p is None:
            continue
        try:
            parent = p.parent
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            pass


def resolve_slug(
    conn: sqlite3.Connection, base_slug: str, *, project_dir: Path
) -> str:
    for i in range(1, 100):
        candidate = base_slug if i == 1 else f"{base_slug}-{i}"
        if not _slug_in_use(conn, candidate, project_dir):
            return candidate
    raise SlugExhaustedError(
        f"Slug '{base_slug}' has 99 collisions in this project. "
        "Use 'immunize remove' to clear stale immunities before capturing new ones."
    )


def _slug_in_use(conn: sqlite3.Connection, slug: str, project_dir: Path) -> bool:
    if storage.slug_exists(conn, slug):
        return True
    paths = _target_paths(project_dir, slug, include_semgrep=True)
    return any(
        p is not None and p.exists()
        for p in (paths.skill_path, paths.cursor_rule_path, paths.pytest_path, paths.semgrep_path)
    )


def _target_paths(project_dir: Path, slug: str, *, include_semgrep: bool) -> InjectedPaths:
    skill = project_dir / ".claude" / "skills" / f"immunize-{slug}" / "SKILL.md"
    cursor = project_dir / ".cursor" / "rules" / f"{slug}.mdc"
    # Python filenames can't have hyphens — convert to underscores for test files only.
    pytest_name = f"test_{slug.replace('-', '_')}.py"
    pytest_ = project_dir / "tests" / "immunized" / pytest_name
    semgrep = project_dir / ".semgrep" / f"{slug}.yml" if include_semgrep else None
    return InjectedPaths(
        slug=slug,
        skill_path=skill,
        cursor_rule_path=cursor,
        semgrep_path=semgrep,
        pytest_path=pytest_,
    )


def _atomic_write_text(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    # PID in suffix prevents races between concurrent immunize processes
    # (e.g., a Claude Code hook firing while a manual capture is mid-write).
    tmp = target.with_suffix(target.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(content)
    os.replace(tmp, target)
