from __future__ import annotations

import contextlib
import os
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from immunize import storage
from immunize.models import Pattern


class SlugExhaustedError(Exception):
    """Raised when resolve_slug exhausts its 99-collision budget."""


class PatternAssetMissingError(Exception):
    """Raised when a pattern directory is missing a required asset file."""


@dataclass(frozen=True)
class InjectedPaths:
    slug: str
    skill_path: Path
    cursor_rule_path: Path
    semgrep_path: Path | None
    pytest_dir: Path
    pytest_path: Path

    def as_db_dict(self) -> dict[str, str | None]:
        return {
            "skill_path": str(self.skill_path),
            "cursor_rule_path": str(self.cursor_rule_path),
            "semgrep_path": str(self.semgrep_path) if self.semgrep_path else None,
            "pytest_path": str(self.pytest_path),
        }


def inject(
    pattern: Pattern,
    *,
    project_dir: Path,
    conn: sqlite3.Connection,
) -> InjectedPaths:
    if pattern.directory is None:
        raise PatternAssetMissingError(
            f"Pattern {pattern.id!r} has no directory set; load_patterns must populate it."
        )
    src = pattern.directory

    skill_src = src / "SKILL.md"
    cursor_src = src / "cursor_rule.mdc"
    pytest_src = src / "test_template.py"
    for required in (skill_src, cursor_src, pytest_src):
        if not required.is_file():
            raise PatternAssetMissingError(
                f"Pattern {pattern.id!r} is missing required asset {required.name}"
            )

    fixtures_src = src / "fixtures"
    semgrep_src = src / "semgrep.yml"

    slug = resolve_slug(conn, pattern.id, project_dir=project_dir)
    paths = _target_paths(
        project_dir,
        slug,
        include_semgrep=semgrep_src.is_file(),
    )

    _atomic_write_text(paths.skill_path, skill_src.read_text())
    _atomic_write_text(paths.cursor_rule_path, cursor_src.read_text())

    paths.pytest_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(paths.pytest_path, pytest_src.read_text())
    _atomic_write_text(paths.pytest_dir / "__init__.py", "")

    if fixtures_src.is_dir():
        _copy_tree(fixtures_src, paths.pytest_dir / "fixtures")

    if paths.semgrep_path is not None:
        _atomic_write_bytes(paths.semgrep_path, semgrep_src.read_bytes())

    return paths


def remove(paths: InjectedPaths) -> None:
    """Delete artifact files and the slug-scoped pytest directory."""
    with contextlib.suppress(FileNotFoundError):
        paths.skill_path.unlink()
    with contextlib.suppress(FileNotFoundError):
        paths.cursor_rule_path.unlink()
    if paths.semgrep_path is not None:
        with contextlib.suppress(FileNotFoundError):
            paths.semgrep_path.unlink()
    if paths.pytest_dir.exists():
        shutil.rmtree(paths.pytest_dir, ignore_errors=True)

    for parent in (
        paths.skill_path.parent,
        paths.cursor_rule_path.parent,
        paths.pytest_dir.parent,
        paths.semgrep_path.parent if paths.semgrep_path else None,
    ):
        if parent is None:
            continue
        try:
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            pass


def resolve_slug(conn: sqlite3.Connection, base_slug: str, *, project_dir: Path) -> str:
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
    if paths.skill_path.exists() or paths.cursor_rule_path.exists():
        return True
    if paths.pytest_dir.exists():
        return True
    return paths.semgrep_path is not None and paths.semgrep_path.exists()


def _target_paths(project_dir: Path, slug: str, *, include_semgrep: bool) -> InjectedPaths:
    skill = project_dir / ".claude" / "skills" / f"immunize-{slug}" / "SKILL.md"
    cursor = project_dir / ".cursor" / "rules" / f"{slug}.mdc"
    pytest_dir = project_dir / "tests" / "immunized" / slug
    pytest_path = pytest_dir / "test_template.py"
    semgrep = project_dir / ".semgrep" / f"{slug}.yml" if include_semgrep else None
    return InjectedPaths(
        slug=slug,
        skill_path=skill,
        cursor_rule_path=cursor,
        semgrep_path=semgrep,
        pytest_dir=pytest_dir,
        pytest_path=pytest_path,
    )


def _atomic_write_text(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    # PID in suffix prevents races between concurrent immunize processes
    # (e.g., a Claude Code hook firing while a manual capture is mid-write).
    tmp = target.with_suffix(target.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(content)
    os.replace(tmp, target)


def _atomic_write_bytes(target: Path, content: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + f".{os.getpid()}.tmp")
    tmp.write_bytes(content)
    os.replace(tmp, target)


def _copy_tree(src: Path, dst: Path) -> None:
    """Recursively copy src to dst with atomic per-file replace."""
    dst.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        if entry.name == "__pycache__":
            continue
        target = dst / entry.name
        if entry.is_dir():
            _copy_tree(entry, target)
        else:
            _atomic_write_bytes(target, entry.read_bytes())
