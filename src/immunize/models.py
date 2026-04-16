from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

ErrorClass = Literal[
    "cors",
    "import",
    "auth",
    "rate_limit",
    "type_error",
    "null_ref",
    "config",
    "network",
    "other",
]

Source = Literal["claude-code-hook", "shell-wrapper", "manual"]

_SLUG_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")


class CapturePayload(BaseModel):
    # Claude Code hook payloads will add fields over time; we tolerate unknowns
    # rather than break on upstream upgrades.
    model_config = ConfigDict(extra="ignore")

    source: Source
    tool_name: str | None = None
    command: str | None = None
    stdout: str = ""
    stderr: str
    exit_code: int
    cwd: str
    timestamp: datetime
    project_fingerprint: str
    session_id: str | None = None


class Diagnosis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_cause: str
    error_class: ErrorClass
    is_generalizable: bool
    canonical_description: str
    fix_summary: str
    language: str
    slug: str
    semgrep_applicable: bool

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, v: str) -> str:
        if not _SLUG_RE.fullmatch(v):
            raise ValueError("slug must be kebab-case (lowercase letters, digits, hyphens)")
        if len(v) > 40:
            raise ValueError("slug must be <= 40 chars")
        return v

    @field_validator("language")
    @classmethod
    def _normalize_language(cls, v: str) -> str:
        return v.strip().lower()


class GeneratedArtifacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_md: str
    cursor_rule: str
    semgrep_yaml: str | None = None
    pytest_code: str
    expected_fix_snippet: str
    error_repro_snippet: str


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    fails_without_fix: bool
    passes_with_fix: bool
    error_message: str | None = None


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = "claude-sonnet-4-6"
    generate_semgrep: bool = False
    verify_timeout_seconds: int = 30
    verify_retry_count: int = 1
    project_dir: Path
    state_db_path: Path
