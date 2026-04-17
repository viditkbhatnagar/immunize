from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from immunize import storage
from immunize.models import CapturePayload, Diagnosis


@pytest.fixture
def conn() -> sqlite3.Connection:
    return storage.connect(":memory:")


@pytest.fixture
def payload() -> CapturePayload:
    return CapturePayload(
        source="manual",
        stderr="boom",
        exit_code=1,
        cwd="/tmp/x",
        timestamp=datetime(2026, 4, 17, 12, 0, tzinfo=timezone.utc),
        project_fingerprint="sha256-proj",
    )


@pytest.fixture
def diagnosis() -> Diagnosis:
    return Diagnosis(
        root_cause="missing credentials on cors fetch",
        error_class="cors",
        is_generalizable=True,
        canonical_description="Cross-origin authenticated fetch needs credentials: 'include'.",
        fix_summary="Set credentials: 'include' and ensure server Allow-Credentials: true.",
        language="typescript",
        slug="cors-missing-credentials",
        semgrep_applicable=False,
    )


def test_init_schema_idempotent(conn: sqlite3.Connection) -> None:
    storage.init_schema(conn)
    storage.init_schema(conn)
    tables = {
        row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"errors", "diagnoses", "artifacts", "rejections"} <= tables


def test_connect_creates_parent_directory(tmp_path: Path) -> None:
    db_path = tmp_path / ".immunize" / "state.db"
    assert not db_path.parent.exists()
    conn = storage.connect(db_path)
    assert db_path.parent.is_dir()
    conn.close()


def test_insert_error_roundtrip(conn: sqlite3.Connection, payload: CapturePayload) -> None:
    error_id = storage.insert_error(conn, payload)
    assert error_id > 0

    row = conn.execute("SELECT * FROM errors WHERE id = ?", (error_id,)).fetchone()
    parsed = json.loads(row["payload_json"])
    assert parsed["source"] == "manual"
    assert row["project_fingerprint"] == "sha256-proj"


def test_insert_diagnosis_with_foreign_key(
    conn: sqlite3.Connection, payload: CapturePayload, diagnosis: Diagnosis
) -> None:
    error_id = storage.insert_error(conn, payload)
    diag_id = storage.insert_diagnosis(conn, error_id, diagnosis, "claude-sonnet-4-6")
    row = conn.execute("SELECT * FROM diagnoses WHERE id = ?", (diag_id,)).fetchone()
    assert row["error_id"] == error_id
    assert row["model"] == "claude-sonnet-4-6"


def test_insert_artifact_stores_paths(
    conn: sqlite3.Connection, payload: CapturePayload, diagnosis: Diagnosis
) -> None:
    error_id = storage.insert_error(conn, payload)
    diag_id = storage.insert_diagnosis(conn, error_id, diagnosis, "m")
    artifact_id = storage.insert_artifact(
        conn,
        diag_id,
        "cors-missing-credentials",
        {
            "skill_path": ".claude/skills/immunize-cors-missing-credentials/SKILL.md",
            "cursor_rule_path": ".cursor/rules/cors-missing-credentials.mdc",
            "semgrep_path": None,
            "pytest_path": "tests/immunized/test_cors_missing_credentials.py",
        },
        verified=True,
    )
    fetched = storage.get_artifact(conn, artifact_id)
    assert fetched is not None
    assert fetched.verified is True
    assert fetched.semgrep_path is None
    assert fetched.slug == "cors-missing-credentials"


def test_list_artifacts_orders_by_id_desc(
    conn: sqlite3.Connection, payload: CapturePayload, diagnosis: Diagnosis
) -> None:
    error_id = storage.insert_error(conn, payload)
    diag_id = storage.insert_diagnosis(conn, error_id, diagnosis, "m")
    storage.insert_artifact(conn, diag_id, "a", {}, verified=True)
    storage.insert_artifact(conn, diag_id, "b", {}, verified=False)
    rows = storage.list_artifacts(conn)
    assert [r.slug for r in rows] == ["b", "a"]


def test_delete_artifact_returns_row_then_removes_it(
    conn: sqlite3.Connection, payload: CapturePayload, diagnosis: Diagnosis
) -> None:
    error_id = storage.insert_error(conn, payload)
    diag_id = storage.insert_diagnosis(conn, error_id, diagnosis, "m")
    artifact_id = storage.insert_artifact(conn, diag_id, "a", {}, verified=True)

    deleted = storage.delete_artifact(conn, artifact_id)
    assert deleted is not None
    assert deleted.slug == "a"
    assert storage.get_artifact(conn, artifact_id) is None


def test_delete_missing_artifact_returns_none(conn: sqlite3.Connection) -> None:
    assert storage.delete_artifact(conn, 9999) is None


def test_slug_exists(
    conn: sqlite3.Connection, payload: CapturePayload, diagnosis: Diagnosis
) -> None:
    error_id = storage.insert_error(conn, payload)
    diag_id = storage.insert_diagnosis(conn, error_id, diagnosis, "m")
    storage.insert_artifact(conn, diag_id, "my-slug", {}, verified=True)
    assert storage.slug_exists(conn, "my-slug") is True
    assert storage.slug_exists(conn, "other-slug") is False


def test_insert_rejection(conn: sqlite3.Connection) -> None:
    rej_id = storage.insert_rejection(conn, None, "verify_failed_twice")
    assert rej_id > 0
    row = conn.execute("SELECT * FROM rejections WHERE id = ?", (rej_id,)).fetchone()
    assert row["reason"] == "verify_failed_twice"
    assert row["diagnosis_id"] is None


def test_insert_match_happy_path(conn: sqlite3.Connection) -> None:
    artifact_id = storage.insert_match(
        conn,
        slug="fetch-missing-credentials",
        pattern_id="fetch-missing-credentials",
        pattern_origin="bundled",
        paths={
            "skill_path": ".claude/skills/immunize-fetch-missing-credentials/SKILL.md",
            "cursor_rule_path": ".cursor/rules/fetch-missing-credentials.mdc",
            "semgrep_path": None,
            "pytest_path": "tests/immunized/fetch-missing-credentials/test_template.py",
        },
        verified=True,
    )
    fetched = storage.get_artifact(conn, artifact_id)
    assert fetched is not None
    assert fetched.diagnosis_id is None
    assert fetched.pattern_id == "fetch-missing-credentials"
    assert fetched.pattern_origin == "bundled"
    assert fetched.slug == "fetch-missing-credentials"
    assert fetched.verified is True
    assert fetched.semgrep_path is None


def test_list_artifacts_returns_pattern_fields(conn: sqlite3.Connection) -> None:
    storage.insert_match(
        conn,
        slug="a",
        pattern_id="pat-a",
        pattern_origin="bundled",
        paths={},
        verified=True,
    )
    storage.insert_match(
        conn,
        slug="b",
        pattern_id="pat-b",
        pattern_origin="local",
        paths={},
        verified=False,
    )
    rows = storage.list_artifacts(conn)
    assert [(r.slug, r.pattern_id, r.pattern_origin) for r in rows] == [
        ("b", "pat-b", "local"),
        ("a", "pat-a", "bundled"),
    ]


def test_migration_from_legacy_schema_adds_pattern_columns(tmp_path: Path) -> None:
    """A DB created under the pre-6b schema must open cleanly and gain the
    new pattern_id/pattern_origin columns with diagnosis_id becoming nullable."""
    db_path = tmp_path / "legacy.db"
    raw = sqlite3.connect(str(db_path))
    raw.executescript(
        """
        CREATE TABLE errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payload_json TEXT NOT NULL,
            captured_at TEXT NOT NULL,
            project_fingerprint TEXT NOT NULL
        );
        CREATE TABLE diagnoses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            error_id INTEGER NOT NULL REFERENCES errors(id),
            diagnosis_json TEXT NOT NULL,
            model TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE artifacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            diagnosis_id INTEGER NOT NULL REFERENCES diagnoses(id),
            slug TEXT NOT NULL,
            skill_path TEXT,
            cursor_rule_path TEXT,
            semgrep_path TEXT,
            pytest_path TEXT,
            verified INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE rejections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            diagnosis_id INTEGER REFERENCES diagnoses(id),
            reason TEXT NOT NULL,
            rejected_at TEXT NOT NULL
        );
        INSERT INTO errors (payload_json, captured_at, project_fingerprint)
            VALUES ('{}', '2026-01-01T00:00:00+00:00', 'legacy-proj');
        INSERT INTO diagnoses (error_id, diagnosis_json, model, created_at)
            VALUES (1, '{}', 'legacy-model', '2026-01-01T00:00:00+00:00');
        INSERT INTO artifacts
            (diagnosis_id, slug, skill_path, cursor_rule_path,
             semgrep_path, pytest_path, verified, created_at)
        VALUES
            (1, 'legacy-slug', 's.md', 'r.mdc', NULL, 't.py', 1,
             '2026-01-01T00:00:00+00:00');
        """
    )
    raw.commit()
    raw.close()

    conn = storage.connect(db_path)
    try:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info('artifacts')")}
        assert {"pattern_id", "pattern_origin"} <= cols

        rows = storage.list_artifacts(conn)
        assert len(rows) == 1
        legacy = rows[0]
        assert legacy.slug == "legacy-slug"
        assert legacy.diagnosis_id == 1
        assert legacy.pattern_id is None
        assert legacy.pattern_origin is None

        new_id = storage.insert_match(
            conn,
            slug="new-slug",
            pattern_id="new-pat",
            pattern_origin="bundled",
            paths={"skill_path": "s"},
            verified=True,
        )
        fresh = storage.get_artifact(conn, new_id)
        assert fresh is not None
        assert fresh.diagnosis_id is None
        assert fresh.pattern_id == "new-pat"
    finally:
        conn.close()


def test_migration_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    conn = storage.connect(db_path)
    storage.insert_match(
        conn,
        slug="a",
        pattern_id="p",
        pattern_origin="bundled",
        paths={},
        verified=True,
    )
    conn.close()

    # Re-open: init_schema runs again; migration must be a no-op.
    conn = storage.connect(db_path)
    try:
        rows = storage.list_artifacts(conn)
        assert len(rows) == 1
        assert rows[0].pattern_id == "p"
    finally:
        conn.close()
