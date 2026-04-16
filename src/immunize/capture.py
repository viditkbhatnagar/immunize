from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import IO

from pydantic import ValidationError

from immunize import storage
from immunize.models import CapturePayload, Source


class CapturePayloadError(Exception):
    """Raised when stdin input cannot be parsed or validated as a CapturePayload."""


def read_payload_from_stdin(stdin: IO[str]) -> CapturePayload:
    text = stdin.read()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise CapturePayloadError(f"stdin is not valid JSON: {e}") from e
    try:
        return CapturePayload.model_validate(data)
    except ValidationError as e:
        raise CapturePayloadError(f"stdin payload failed validation: {e}") from e


def build_payload_from_plain(
    stderr_text: str, *, cwd: Path, source: Source = "manual"
) -> CapturePayload:
    return CapturePayload(
        source=source,
        stderr=stderr_text,
        exit_code=1,
        cwd=str(cwd),
        timestamp=datetime.now(timezone.utc),
        project_fingerprint=project_fingerprint_for(cwd),
    )


def project_fingerprint_for(cwd: Path) -> str:
    digest = hashlib.sha256(str(cwd.resolve()).encode()).hexdigest()[:16]
    return f"sha256-{digest}"


def persist(conn: sqlite3.Connection, payload: CapturePayload) -> int:
    return storage.insert_error(conn, payload)
