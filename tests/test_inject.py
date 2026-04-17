from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from immunize import inject, storage
from immunize.models import CapturePayload, Diagnosis, GeneratedArtifacts


@pytest.fixture
def conn() -> sqlite3.Connection:
    return storage.connect(":memory:")


@pytest.fixture
def payload(tmp_path: Path) -> CapturePayload:
    return CapturePayload(
        source="manual",
        stderr="boom",
        exit_code=1,
        cwd=str(tmp_path),
        timestamp=datetime(2026, 4, 17, tzinfo=timezone.utc),
        project_fingerprint="sha256-proj",
    )


@pytest.fixture
def diagnosis() -> Diagnosis:
    return Diagnosis(
        root_cause="rc",
        error_class="type_error",
        is_generalizable=True,
        canonical_description="An integer was passed where a string was expected.",
        fix_summary="Coerce the value.",
        language="python",
        slug="int-vs-str",
        semgrep_applicable=False,
    )


def _artifacts(*, with_semgrep: bool = False) -> GeneratedArtifacts:
    return GeneratedArtifacts(
        skill_md="---\nname: immunize-int-vs-str\ndescription: d\n---\n\nSKILL body\n",
        cursor_rule="---\ndescription: d\nglobs: **/*.py\nalwaysApply: false\n---\n\nBody\n",
        semgrep_yaml="rules:\n  - id: immunize-int-vs-str\n" if with_semgrep else None,
        pytest_code="def test_x() -> None:\n    assert True\n",
        expected_fix_snippet="fix\n",
        error_repro_snippet="repro\n",
    )


# ---- inject writes all three mandatory files + optional semgrep ------------
def test_inject_writes_all_artifacts(
    conn: sqlite3.Connection, diagnosis: Diagnosis, payload: CapturePayload, tmp_path: Path
) -> None:
    paths = inject.inject(_artifacts(), diagnosis, payload, conn=conn)
    assert paths.skill_path.is_file()
    assert paths.cursor_rule_path.is_file()
    assert paths.pytest_path.is_file()
    assert paths.semgrep_path is None
    assert paths.slug == "int-vs-str"


def test_inject_writes_semgrep_when_provided(
    conn: sqlite3.Connection, diagnosis: Diagnosis, payload: CapturePayload, tmp_path: Path
) -> None:
    paths = inject.inject(_artifacts(with_semgrep=True), diagnosis, payload, conn=conn)
    assert paths.semgrep_path is not None
    assert paths.semgrep_path.is_file()
    assert "immunize-int-vs-str" in paths.semgrep_path.read_text()


# ---- Path layout -----------------------------------------------------------
def test_paths_follow_architecture_layout(
    conn: sqlite3.Connection, diagnosis: Diagnosis, payload: CapturePayload, tmp_path: Path
) -> None:
    paths = inject.inject(_artifacts(with_semgrep=True), diagnosis, payload, conn=conn)
    assert paths.skill_path == tmp_path / ".claude" / "skills" / "immunize-int-vs-str" / "SKILL.md"
    assert paths.cursor_rule_path == tmp_path / ".cursor" / "rules" / "int-vs-str.mdc"
    assert paths.pytest_path == tmp_path / "tests" / "immunized" / "test_int_vs_str.py"
    assert paths.semgrep_path == tmp_path / ".semgrep" / "int-vs-str.yml"


def test_pytest_filename_replaces_hyphens_with_underscores(
    conn: sqlite3.Connection, payload: CapturePayload, tmp_path: Path
) -> None:
    diagnosis = Diagnosis(
        root_cause="rc",
        error_class="cors",
        is_generalizable=True,
        canonical_description="x" * 30,
        fix_summary="fs",
        language="typescript",
        slug="cors-missing-allow-credentials",
        semgrep_applicable=False,
    )
    paths = inject.inject(_artifacts(), diagnosis, payload, conn=conn)
    assert paths.pytest_path.name == "test_cors_missing_allow_credentials.py"


# ---- Atomic write removes the tmp file -------------------------------------
def test_tmp_file_does_not_remain(
    conn: sqlite3.Connection, diagnosis: Diagnosis, payload: CapturePayload, tmp_path: Path
) -> None:
    inject.inject(_artifacts(), diagnosis, payload, conn=conn)
    leftovers = list(tmp_path.rglob(f"*.{os.getpid()}.tmp"))
    assert leftovers == []


# ---- Collision: DB row already has the slug --------------------------------
def test_collision_via_db_appends_suffix(
    conn: sqlite3.Connection, diagnosis: Diagnosis, payload: CapturePayload, tmp_path: Path
) -> None:
    # Seed storage with an existing artifact at the base slug.
    error_id = storage.insert_error(conn, payload)
    diag_id = storage.insert_diagnosis(conn, error_id, diagnosis, "m")
    storage.insert_artifact(conn, diag_id, "int-vs-str", {}, verified=True)

    paths = inject.inject(_artifacts(), diagnosis, payload, conn=conn)
    assert paths.slug == "int-vs-str-2"
    assert paths.pytest_path.name == "test_int_vs_str_2.py"


# ---- Collision: filesystem artifact exists (not in DB) ---------------------
def test_collision_via_filesystem_appends_suffix(
    conn: sqlite3.Connection, diagnosis: Diagnosis, payload: CapturePayload, tmp_path: Path
) -> None:
    stale = tmp_path / ".claude" / "skills" / "immunize-int-vs-str" / "SKILL.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale from a previous manual edit")

    paths = inject.inject(_artifacts(), diagnosis, payload, conn=conn)
    assert paths.slug == "int-vs-str-2"
    # Stale file was never overwritten.
    assert stale.read_text() == "stale from a previous manual edit"


# ---- Exhausting the 99-slot budget raises ----------------------------------
def test_slug_exhausted_raises(
    conn: sqlite3.Connection, diagnosis: Diagnosis, payload: CapturePayload, tmp_path: Path
) -> None:
    error_id = storage.insert_error(conn, payload)
    diag_id = storage.insert_diagnosis(conn, error_id, diagnosis, "m")
    storage.insert_artifact(conn, diag_id, "int-vs-str", {}, verified=True)
    for i in range(2, 100):
        storage.insert_artifact(conn, diag_id, f"int-vs-str-{i}", {}, verified=True)
    with pytest.raises(inject.SlugExhaustedError, match="99 collisions"):
        inject.inject(_artifacts(), diagnosis, payload, conn=conn)


# ---- remove deletes files and tolerates missing ones ----------------------
def test_remove_deletes_files(
    conn: sqlite3.Connection, diagnosis: Diagnosis, payload: CapturePayload, tmp_path: Path
) -> None:
    paths = inject.inject(_artifacts(with_semgrep=True), diagnosis, payload, conn=conn)
    inject.remove(paths)
    assert not paths.skill_path.exists()
    assert not paths.cursor_rule_path.exists()
    assert paths.semgrep_path is not None and not paths.semgrep_path.exists()
    assert not paths.pytest_path.exists()


def test_remove_tolerates_missing_files(
    conn: sqlite3.Connection, diagnosis: Diagnosis, payload: CapturePayload, tmp_path: Path
) -> None:
    paths = inject.inject(_artifacts(), diagnosis, payload, conn=conn)
    # Manually pre-delete one file.
    paths.skill_path.unlink()
    # remove() must not raise.
    inject.remove(paths)
    assert not paths.pytest_path.exists()


# ---- InjectedPaths.as_db_dict ---------------------------------------------
def test_as_db_dict_shape(
    conn: sqlite3.Connection, diagnosis: Diagnosis, payload: CapturePayload, tmp_path: Path
) -> None:
    paths = inject.inject(_artifacts(with_semgrep=True), diagnosis, payload, conn=conn)
    d = paths.as_db_dict()
    assert set(d) == {"skill_path", "cursor_rule_path", "semgrep_path", "pytest_path"}
    assert d["skill_path"].endswith("SKILL.md")
    assert d["semgrep_path"] is not None

    paths_nosemgrep = inject.inject(_artifacts(), diagnosis, payload, conn=conn)
    assert paths_nosemgrep.as_db_dict()["semgrep_path"] is None
