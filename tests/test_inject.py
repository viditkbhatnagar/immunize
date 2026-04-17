from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from immunize import inject, storage
from immunize.models import Pattern


@pytest.fixture
def conn() -> sqlite3.Connection:
    return storage.connect(":memory:")


def _write_pattern(
    root: Path,
    slug: str,
    *,
    with_semgrep: bool = False,
    with_fixtures: bool = True,
    omit: str | None = None,
) -> Pattern:
    """Create a minimal pattern directory at root/slug and return a Pattern.

    `omit` names a file to skip creating, for missing-asset tests.
    """
    pattern_dir = root / slug
    pattern_dir.mkdir(parents=True, exist_ok=True)
    if omit != "SKILL.md":
        (pattern_dir / "SKILL.md").write_text(
            f"---\nname: immunize-{slug}\ndescription: d\n---\n\nSKILL body for {slug}\n"
        )
    if omit != "cursor_rule.mdc":
        (pattern_dir / "cursor_rule.mdc").write_text(
            f"---\ndescription: d\nglobs: **/*.py\nalwaysApply: false\n---\n\nRule for {slug}\n"
        )
    if omit != "test_template.py":
        (pattern_dir / "test_template.py").write_text(
            "from __future__ import annotations\n"
            "from pathlib import Path\n\n"
            "FIXTURE = Path(__file__).parent / 'fixtures' / 'data.txt'\n\n"
            "def test_fixture_readable() -> None:\n"
            "    assert FIXTURE.read_text().strip() == 'ok'\n"
        )
    if with_fixtures:
        fixtures = pattern_dir / "fixtures"
        fixtures.mkdir(exist_ok=True)
        (fixtures / "data.txt").write_text("ok\n")
    if with_semgrep:
        (pattern_dir / "semgrep.yml").write_text(f"rules:\n  - id: immunize-{slug}\n")

    return Pattern.model_validate(
        {
            "id": slug,
            "version": 1,
            "author": "@test",
            "origin": "bundled",
            "error_class": "other",
            "languages": ["python"],
            "description": "test pattern",
            "match": {"stderr_patterns": ["boom"], "min_confidence": 0.70},
            "verification": {"pytest_relative_path": "test_template.py"},
            "directory": pattern_dir,
        }
    )


# ---- inject writes all three mandatory files + optional semgrep ------------
def test_inject_writes_all_artifacts(conn: sqlite3.Connection, tmp_path: Path) -> None:
    patterns_dir = tmp_path / "patterns"
    project_dir = tmp_path / "project"
    pattern = _write_pattern(patterns_dir, "my-slug")

    paths = inject.inject(pattern, project_dir=project_dir, conn=conn)
    assert paths.skill_path.is_file()
    assert paths.cursor_rule_path.is_file()
    assert paths.pytest_path.is_file()
    assert paths.semgrep_path is None
    assert paths.slug == "my-slug"
    assert (paths.pytest_dir / "__init__.py").is_file()


def test_inject_copies_fixtures_subtree(conn: sqlite3.Connection, tmp_path: Path) -> None:
    patterns_dir = tmp_path / "patterns"
    project_dir = tmp_path / "project"
    pattern = _write_pattern(patterns_dir, "with-fix")

    paths = inject.inject(pattern, project_dir=project_dir, conn=conn)
    fixture_file = paths.pytest_dir / "fixtures" / "data.txt"
    assert fixture_file.is_file()
    assert fixture_file.read_text() == "ok\n"

    # The injected test_template.py reads Path(__file__).parent / "fixtures" /
    # "data.txt" — that expression must resolve correctly in the target tree.
    expected = paths.pytest_path.parent / "fixtures" / "data.txt"
    assert expected == fixture_file


def test_inject_writes_semgrep_when_present(conn: sqlite3.Connection, tmp_path: Path) -> None:
    patterns_dir = tmp_path / "patterns"
    project_dir = tmp_path / "project"
    pattern = _write_pattern(patterns_dir, "sem-slug", with_semgrep=True)

    paths = inject.inject(pattern, project_dir=project_dir, conn=conn)
    assert paths.semgrep_path is not None
    assert paths.semgrep_path.is_file()
    assert "immunize-sem-slug" in paths.semgrep_path.read_text()


# ---- Path layout -----------------------------------------------------------
def test_paths_follow_architecture_layout(conn: sqlite3.Connection, tmp_path: Path) -> None:
    patterns_dir = tmp_path / "patterns"
    project_dir = tmp_path / "project"
    pattern = _write_pattern(patterns_dir, "int-vs-str", with_semgrep=True)

    paths = inject.inject(pattern, project_dir=project_dir, conn=conn)
    assert paths.skill_path == (
        project_dir / ".claude" / "skills" / "immunize-int-vs-str" / "SKILL.md"
    )
    assert paths.cursor_rule_path == project_dir / ".cursor" / "rules" / "int-vs-str.mdc"
    assert paths.pytest_dir == project_dir / "tests" / "immunized" / "int-vs-str"
    assert paths.pytest_path == paths.pytest_dir / "test_template.py"
    assert paths.semgrep_path == project_dir / ".semgrep" / "int-vs-str.yml"


# ---- Missing asset raises ---------------------------------------------------
def test_inject_raises_on_missing_required_asset(conn: sqlite3.Connection, tmp_path: Path) -> None:
    patterns_dir = tmp_path / "patterns"
    project_dir = tmp_path / "project"
    pattern = _write_pattern(patterns_dir, "broken", omit="test_template.py")

    with pytest.raises(inject.PatternAssetMissingError, match="test_template.py"):
        inject.inject(pattern, project_dir=project_dir, conn=conn)


# ---- Atomic write removes the tmp file -------------------------------------
def test_tmp_file_does_not_remain(conn: sqlite3.Connection, tmp_path: Path) -> None:
    patterns_dir = tmp_path / "patterns"
    project_dir = tmp_path / "project"
    pattern = _write_pattern(patterns_dir, "atomic-check")

    inject.inject(pattern, project_dir=project_dir, conn=conn)
    leftovers = list(project_dir.rglob(f"*.{os.getpid()}.tmp"))
    assert leftovers == []


# ---- Collision: DB row already has the slug --------------------------------
def test_collision_via_db_appends_suffix(conn: sqlite3.Connection, tmp_path: Path) -> None:
    patterns_dir = tmp_path / "patterns"
    project_dir = tmp_path / "project"
    pattern = _write_pattern(patterns_dir, "int-vs-str")

    storage.insert_match(
        conn,
        slug="int-vs-str",
        pattern_id="int-vs-str",
        pattern_origin="bundled",
        paths={},
        verified=True,
    )
    paths = inject.inject(pattern, project_dir=project_dir, conn=conn)
    assert paths.slug == "int-vs-str-2"
    assert paths.pytest_dir.name == "int-vs-str-2"


# ---- Collision: filesystem artifact exists (not in DB) ---------------------
def test_collision_via_filesystem_appends_suffix(conn: sqlite3.Connection, tmp_path: Path) -> None:
    patterns_dir = tmp_path / "patterns"
    project_dir = tmp_path / "project"
    pattern = _write_pattern(patterns_dir, "int-vs-str")

    stale = project_dir / ".claude" / "skills" / "immunize-int-vs-str" / "SKILL.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale from a previous manual edit")

    paths = inject.inject(pattern, project_dir=project_dir, conn=conn)
    assert paths.slug == "int-vs-str-2"
    assert stale.read_text() == "stale from a previous manual edit"


def test_collision_via_pytest_dir_appends_suffix(conn: sqlite3.Connection, tmp_path: Path) -> None:
    patterns_dir = tmp_path / "patterns"
    project_dir = tmp_path / "project"
    pattern = _write_pattern(patterns_dir, "int-vs-str")

    stale_dir = project_dir / "tests" / "immunized" / "int-vs-str"
    stale_dir.mkdir(parents=True)
    (stale_dir / "stale_marker").write_text("x")

    paths = inject.inject(pattern, project_dir=project_dir, conn=conn)
    assert paths.slug == "int-vs-str-2"
    assert (stale_dir / "stale_marker").exists()


# ---- Exhausting the 99-slot budget raises ----------------------------------
def test_slug_exhausted_raises(conn: sqlite3.Connection, tmp_path: Path) -> None:
    patterns_dir = tmp_path / "patterns"
    project_dir = tmp_path / "project"
    pattern = _write_pattern(patterns_dir, "int-vs-str")

    for i in range(1, 100):
        slug = "int-vs-str" if i == 1 else f"int-vs-str-{i}"
        storage.insert_match(
            conn,
            slug=slug,
            pattern_id="int-vs-str",
            pattern_origin="bundled",
            paths={},
            verified=True,
        )
    with pytest.raises(inject.SlugExhaustedError, match="99 collisions"):
        inject.inject(pattern, project_dir=project_dir, conn=conn)


# ---- remove deletes files + pytest_dir + tolerates missing ones -----------
def test_remove_deletes_files_and_pytest_dir(conn: sqlite3.Connection, tmp_path: Path) -> None:
    patterns_dir = tmp_path / "patterns"
    project_dir = tmp_path / "project"
    pattern = _write_pattern(patterns_dir, "slug-a", with_semgrep=True)

    paths = inject.inject(pattern, project_dir=project_dir, conn=conn)
    inject.remove(paths)
    assert not paths.skill_path.exists()
    assert not paths.cursor_rule_path.exists()
    assert paths.semgrep_path is not None and not paths.semgrep_path.exists()
    assert not paths.pytest_dir.exists()


def test_remove_tolerates_missing_files(conn: sqlite3.Connection, tmp_path: Path) -> None:
    patterns_dir = tmp_path / "patterns"
    project_dir = tmp_path / "project"
    pattern = _write_pattern(patterns_dir, "slug-b")

    paths = inject.inject(pattern, project_dir=project_dir, conn=conn)
    paths.skill_path.unlink()
    # remove() must not raise.
    inject.remove(paths)
    assert not paths.pytest_dir.exists()


# ---- InjectedPaths.as_db_dict ---------------------------------------------
def test_as_db_dict_shape(conn: sqlite3.Connection, tmp_path: Path) -> None:
    patterns_dir = tmp_path / "patterns"
    project_dir = tmp_path / "project"
    pattern = _write_pattern(patterns_dir, "slug-c", with_semgrep=True)

    paths = inject.inject(pattern, project_dir=project_dir, conn=conn)
    d = paths.as_db_dict()
    assert set(d) == {"skill_path", "cursor_rule_path", "semgrep_path", "pytest_path"}
    assert d["skill_path"].endswith("SKILL.md")
    assert d["semgrep_path"] is not None
    assert d["pytest_path"].endswith("test_template.py")


def test_as_db_dict_nosemgrep(conn: sqlite3.Connection, tmp_path: Path) -> None:
    patterns_dir = tmp_path / "patterns"
    project_dir = tmp_path / "project"
    pattern = _write_pattern(patterns_dir, "slug-d")

    paths = inject.inject(pattern, project_dir=project_dir, conn=conn)
    assert paths.as_db_dict()["semgrep_path"] is None


# ---- Injected pytest can actually read its fixtures ------------------------
def test_injected_pytest_reads_fixtures_in_project_tree(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """Proves the slug-scoped layout preserves the pattern's
    Path(__file__).parent / 'fixtures' path expression."""
    patterns_dir = tmp_path / "patterns"
    project_dir = tmp_path / "project"
    pattern = _write_pattern(patterns_dir, "reads-fixture")

    paths = inject.inject(pattern, project_dir=project_dir, conn=conn)
    ns: dict = {"__file__": str(paths.pytest_path)}
    exec(paths.pytest_path.read_text(), ns)
    ns["test_fixture_readable"]()


# ---- 6g: injected repro.* slot carries fix.* bytes -------------------------
def _write_pattern_with_repro_fix_pair(root: Path, slug: str) -> tuple[Pattern, bytes, bytes]:
    """Create a pattern whose test_template.py reads fixtures/repro.jsx and
    asserts a 'FIXED' marker is present. repro.jsx ships BAD bytes; fix.jsx
    ships GOOD bytes. Inject must write fix bytes to the repro slot."""
    import importlib

    pattern_dir = root / slug
    pattern_dir.mkdir(parents=True, exist_ok=True)
    (pattern_dir / "SKILL.md").write_text(f"---\nname: immunize-{slug}\ndescription: d\n---\n\nx\n")
    (pattern_dir / "cursor_rule.mdc").write_text(
        "---\ndescription: d\nglobs: '**/*.jsx'\nalwaysApply: false\n---\n\nrule\n"
    )
    (pattern_dir / "test_template.py").write_text(
        "from pathlib import Path\n\n"
        "def test_repro_has_fix_marker() -> None:\n"
        "    src = (Path(__file__).parent / 'fixtures' / 'repro.jsx').read_text()\n"
        "    assert 'FIXED' in src, f'expected FIXED marker, got: {src!r}'\n"
    )
    fixtures = pattern_dir / "fixtures"
    fixtures.mkdir(exist_ok=True)
    bad_bytes = b"const x = 'BUGGY';\n"
    good_bytes = b"const x = 'FIXED';\n"
    (fixtures / "repro.jsx").write_bytes(bad_bytes)
    (fixtures / "fix.jsx").write_bytes(good_bytes)

    importlib.invalidate_caches()  # belt-and-braces; not strictly needed here
    pattern = Pattern.model_validate(
        {
            "id": slug,
            "version": 1,
            "author": "@test",
            "origin": "bundled",
            "error_class": "other",
            "languages": ["javascript"],
            "description": "repro/fix rewrite test",
            "match": {"stderr_patterns": ["boom"], "min_confidence": 0.70},
            "verification": {"pytest_relative_path": "test_template.py"},
            "directory": pattern_dir,
        }
    )
    return pattern, bad_bytes, good_bytes


def test_inject_rewrites_repro_bytes_to_fix_bytes(conn: sqlite3.Connection, tmp_path: Path) -> None:
    patterns_dir = tmp_path / "patterns"
    project_dir = tmp_path / "project"
    pattern, bad_bytes, good_bytes = _write_pattern_with_repro_fix_pair(patterns_dir, "rewrite-me")

    paths = inject.inject(pattern, project_dir=project_dir, conn=conn)

    injected_repro = paths.pytest_dir / "fixtures" / "repro.jsx"
    injected_fix = paths.pytest_dir / "fixtures" / "fix.jsx"
    assert injected_repro.read_bytes() == good_bytes, "repro slot must carry fix bytes"
    assert injected_fix.read_bytes() == good_bytes, "fix slot must carry fix bytes"

    # Pattern's source tree is untouched — pattern_lint still owns the swap.
    assert (pattern.directory / "fixtures" / "repro.jsx").read_bytes() == bad_bytes
    assert (pattern.directory / "fixtures" / "fix.jsx").read_bytes() == good_bytes


def test_injected_guardrail_test_passes_in_user_pytest(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """Run pytest on the injected test_template.py without any fixture
    manipulation. It MUST pass. This is the ship-blocker guarantee from 6g."""
    import subprocess
    import sys

    patterns_dir = tmp_path / "patterns"
    project_dir = tmp_path / "project"
    pattern, _, _ = _write_pattern_with_repro_fix_pair(patterns_dir, "user-ci")

    paths = inject.inject(pattern, project_dir=project_dir, conn=conn)
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-x",
        "-q",
        "-p",
        "no:cacheprovider",
        str(paths.pytest_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert (
        proc.returncode == 0
    ), f"injected guardrail test must pass; stdout={proc.stdout!r} stderr={proc.stderr!r}"


def test_inject_copies_repro_verbatim_when_no_fix_sibling(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """Patterns with only a repro (no fix) fall through to verbatim copy —
    the rewrite only fires on a matched repro+fix pair."""
    pattern_dir = tmp_path / "patterns" / "only-repro"
    pattern_dir.mkdir(parents=True)
    (pattern_dir / "SKILL.md").write_text("---\nname: x\ndescription: d\n---\nx\n")
    (pattern_dir / "cursor_rule.mdc").write_text(
        "---\ndescription: d\nglobs: '**/*'\nalwaysApply: false\n---\nrule\n"
    )
    (pattern_dir / "test_template.py").write_text("def test_x(): pass\n")
    (pattern_dir / "fixtures").mkdir()
    (pattern_dir / "fixtures" / "repro.txt").write_bytes(b"verbatim\n")

    pattern = Pattern.model_validate(
        {
            "id": "only-repro",
            "version": 1,
            "author": "@t",
            "origin": "bundled",
            "error_class": "other",
            "languages": ["python"],
            "description": "no-fix pattern",
            "match": {"stderr_patterns": ["x"]},
            "verification": {"pytest_relative_path": "test_template.py"},
            "directory": pattern_dir,
        }
    )
    paths = inject.inject(pattern, project_dir=tmp_path / "project", conn=conn)
    assert (paths.pytest_dir / "fixtures" / "repro.txt").read_bytes() == b"verbatim\n"
