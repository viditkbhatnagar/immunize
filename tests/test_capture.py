from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from immunize import capture, storage

FIXTURES = Path(__file__).parent / "fixtures"


def test_read_payload_from_stdin_happy(tmp_path: Path) -> None:
    text = (FIXTURES / "cors_error.json").read_text()
    payload = capture.read_payload_from_stdin(io.StringIO(text))
    assert payload.source == "manual"
    assert payload.exit_code == 1


def test_read_payload_from_stdin_invalid_json() -> None:
    with pytest.raises(capture.CapturePayloadError, match="not valid JSON"):
        capture.read_payload_from_stdin(io.StringIO("not-json-at-all"))


def test_read_payload_from_stdin_missing_required_field() -> None:
    # Drop the required `stderr` field.
    bad = json.loads((FIXTURES / "cors_error.json").read_text())
    bad.pop("stderr")
    with pytest.raises(capture.CapturePayloadError, match="failed validation"):
        capture.read_payload_from_stdin(io.StringIO(json.dumps(bad)))


def test_build_payload_from_plain(tmp_path: Path) -> None:
    payload = capture.build_payload_from_plain("oh no traceback", cwd=tmp_path)
    assert payload.source == "manual"
    assert payload.stderr == "oh no traceback"
    assert payload.cwd == str(tmp_path)
    assert payload.project_fingerprint.startswith("sha256-")


def test_project_fingerprint_stable(tmp_path: Path) -> None:
    first = capture.project_fingerprint_for(tmp_path)
    second = capture.project_fingerprint_for(tmp_path)
    assert first == second


def test_project_fingerprint_differs_by_path(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    assert capture.project_fingerprint_for(tmp_path) != capture.project_fingerprint_for(other)


def test_persist_writes_errors_row() -> None:
    text = (FIXTURES / "cors_error.json").read_text()
    payload = capture.read_payload_from_stdin(io.StringIO(text))
    conn = storage.connect(":memory:")
    error_id = capture.persist(conn, payload)
    row = conn.execute("SELECT * FROM errors WHERE id = ?", (error_id,)).fetchone()
    stored = json.loads(row["payload_json"])
    assert stored["cwd"] == "/tmp/sandbox-project"
