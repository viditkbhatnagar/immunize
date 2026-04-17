from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from immunize.models import CapturePayload, Diagnosis

# The `diagnoses` table is left in place for backward compatibility with
# pre-Phase-1B databases; no code path writes to it after step 6e. The
# `artifacts.diagnosis_id` column is nullable — new matcher-driven inserts
# leave it NULL and populate `pattern_id` / `pattern_origin` instead.
BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payload_json TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    project_fingerprint TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS diagnoses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    error_id INTEGER NOT NULL REFERENCES errors(id),
    diagnosis_json TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    diagnosis_id INTEGER REFERENCES diagnoses(id),
    pattern_id TEXT,
    pattern_origin TEXT,
    slug TEXT NOT NULL,
    skill_path TEXT,
    cursor_rule_path TEXT,
    semgrep_path TEXT,
    pytest_path TEXT,
    verified INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rejections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    diagnosis_id INTEGER REFERENCES diagnoses(id),
    reason TEXT NOT NULL,
    rejected_at TEXT NOT NULL
);
"""

INDEXES = """
CREATE INDEX IF NOT EXISTS idx_artifacts_slug ON artifacts(slug);
CREATE INDEX IF NOT EXISTS idx_artifacts_pattern_id ON artifacts(pattern_id);
"""


@dataclass(frozen=True)
class ArtifactRow:
    id: int
    diagnosis_id: int | None
    pattern_id: str | None
    pattern_origin: str | None
    slug: str
    skill_path: str | None
    cursor_rule_path: str | None
    semgrep_path: str | None
    pytest_path: str | None
    verified: bool
    created_at: str


def connect(db_path: Path | str) -> sqlite3.Connection:
    # First-run capture on a fresh project: ensure .immunize/ exists.
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    # CREATE TABLE IF NOT EXISTS is a no-op for legacy DBs whose `artifacts`
    # table predates the pattern_id column. The migration pass below rebuilds
    # that table in-place; only after it returns are the new indexes safe.
    conn.executescript(BASE_SCHEMA)
    _migrate_artifacts_if_needed(conn)
    conn.executescript(INDEXES)
    conn.commit()


def _migrate_artifacts_if_needed(conn: sqlite3.Connection) -> None:
    cols = {row["name"] for row in conn.execute("PRAGMA table_info('artifacts')")}
    if not cols or "pattern_id" in cols:
        return
    conn.executescript(
        """
        PRAGMA foreign_keys = OFF;
        CREATE TABLE artifacts_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            diagnosis_id INTEGER REFERENCES diagnoses(id),
            pattern_id TEXT,
            pattern_origin TEXT,
            slug TEXT NOT NULL,
            skill_path TEXT,
            cursor_rule_path TEXT,
            semgrep_path TEXT,
            pytest_path TEXT,
            verified INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        INSERT INTO artifacts_new
            (id, diagnosis_id, pattern_id, pattern_origin, slug,
             skill_path, cursor_rule_path, semgrep_path, pytest_path,
             verified, created_at)
        SELECT id, diagnosis_id, NULL, NULL, slug,
               skill_path, cursor_rule_path, semgrep_path, pytest_path,
               verified, created_at
        FROM artifacts;
        DROP TABLE artifacts;
        ALTER TABLE artifacts_new RENAME TO artifacts;
        CREATE INDEX IF NOT EXISTS idx_artifacts_slug ON artifacts(slug);
        CREATE INDEX IF NOT EXISTS idx_artifacts_pattern_id ON artifacts(pattern_id);
        PRAGMA foreign_keys = ON;
        """
    )


def insert_error(conn: sqlite3.Connection, payload: CapturePayload) -> int:
    cursor = conn.execute(
        "INSERT INTO errors (payload_json, captured_at, project_fingerprint) VALUES (?, ?, ?)",
        (payload.model_dump_json(), _now(), payload.project_fingerprint),
    )
    conn.commit()
    return cursor.lastrowid or 0


# DEPRECATED: slated for deletion in step 6e. No code path writes to the
# diagnoses table after the Phase 1B pivot. Kept here so the tests that
# still exercise the legacy shape pass until 6e prunes them.
def insert_diagnosis(
    conn: sqlite3.Connection, error_id: int, diagnosis: Diagnosis, model: str
) -> int:
    cursor = conn.execute(
        "INSERT INTO diagnoses (error_id, diagnosis_json, model, created_at) "
        "VALUES (?, ?, ?, ?)",
        (error_id, diagnosis.model_dump_json(), model, _now()),
    )
    conn.commit()
    return cursor.lastrowid or 0


# DEPRECATED: callers should use insert_match. Kept alive through step 6e
# so legacy tests round-trip; the diagnoses FK is nullable.
def insert_artifact(
    conn: sqlite3.Connection,
    diagnosis_id: int | None,
    slug: str,
    paths: dict[str, str | None],
    verified: bool,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO artifacts
          (diagnosis_id, slug, skill_path, cursor_rule_path,
           semgrep_path, pytest_path, verified, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            diagnosis_id,
            slug,
            paths.get("skill_path"),
            paths.get("cursor_rule_path"),
            paths.get("semgrep_path"),
            paths.get("pytest_path"),
            1 if verified else 0,
            _now(),
        ),
    )
    conn.commit()
    return cursor.lastrowid or 0


def insert_match(
    conn: sqlite3.Connection,
    *,
    slug: str,
    pattern_id: str,
    pattern_origin: str,
    paths: dict[str, str | None],
    verified: bool,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO artifacts
          (diagnosis_id, pattern_id, pattern_origin, slug,
           skill_path, cursor_rule_path, semgrep_path, pytest_path,
           verified, created_at)
        VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            pattern_id,
            pattern_origin,
            slug,
            paths.get("skill_path"),
            paths.get("cursor_rule_path"),
            paths.get("semgrep_path"),
            paths.get("pytest_path"),
            1 if verified else 0,
            _now(),
        ),
    )
    conn.commit()
    return cursor.lastrowid or 0


def insert_rejection(conn: sqlite3.Connection, diagnosis_id: int | None, reason: str) -> int:
    cursor = conn.execute(
        "INSERT INTO rejections (diagnosis_id, reason, rejected_at) VALUES (?, ?, ?)",
        (diagnosis_id, reason, _now()),
    )
    conn.commit()
    return cursor.lastrowid or 0


def list_artifacts(conn: sqlite3.Connection) -> list[ArtifactRow]:
    rows = conn.execute("SELECT * FROM artifacts ORDER BY id DESC").fetchall()
    return [_row_to_artifact(r) for r in rows]


def get_artifact(conn: sqlite3.Connection, artifact_id: int) -> ArtifactRow | None:
    row = conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
    return _row_to_artifact(row) if row else None


def delete_artifact(conn: sqlite3.Connection, artifact_id: int) -> ArtifactRow | None:
    row = get_artifact(conn, artifact_id)
    if row is None:
        return None
    conn.execute("DELETE FROM artifacts WHERE id = ?", (artifact_id,))
    conn.commit()
    return row


def slug_exists(conn: sqlite3.Connection, slug: str) -> bool:
    hit = conn.execute("SELECT 1 FROM artifacts WHERE slug = ? LIMIT 1", (slug,)).fetchone()
    return hit is not None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_artifact(row: sqlite3.Row) -> ArtifactRow:
    return ArtifactRow(
        id=row["id"],
        diagnosis_id=row["diagnosis_id"],
        pattern_id=row["pattern_id"],
        pattern_origin=row["pattern_origin"],
        slug=row["slug"],
        skill_path=row["skill_path"],
        cursor_rule_path=row["cursor_rule_path"],
        semgrep_path=row["semgrep_path"],
        pytest_path=row["pytest_path"],
        verified=bool(row["verified"]),
        created_at=row["created_at"],
    )
