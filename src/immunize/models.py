from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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

# DEPRECATED pending pivot: Diagnosis, GeneratedArtifacts, ErrorClass
# These models are scheduled for deletion once their consumers (storage, inject,
# verify, cursor_rule) are rewired to use Pattern / MatchResult in Steps 3-6.
# Do not add new callers of these models.


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
    min_match_confidence: float = Field(default=0.70, ge=0.0, le=1.0)
    local_patterns_dir: Path | None = None

    @model_validator(mode="after")
    def _fill_local_patterns_dir(self) -> Settings:
        if self.local_patterns_dir is None:
            self.local_patterns_dir = self.project_dir / ".immunize" / "patterns_local"
        return self


# --- Pattern library models (Phase 1B) --------------------------------------


class MatchRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stderr_patterns: list[str] = Field(default_factory=list)
    stdout_patterns: list[str] = Field(default_factory=list)
    error_class_hint: str | None = None
    min_confidence: float = Field(default=0.70, ge=0.0, le=1.0)


class Verification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pytest_relative_path: str
    expected_fail_without_fix: bool = True
    expected_pass_with_fix: bool = True
    timeout_seconds: int = 30


class Pattern(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: int
    schema_version: int = 1
    author: str
    origin: Literal["bundled", "local", "community"]
    error_class: str
    languages: list[str]
    description: str
    match: MatchRules
    verification: Verification
    # Populated at load time from the pattern's directory path; never in YAML.
    directory: Path | None = None

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        if not _SLUG_RE.fullmatch(v):
            raise ValueError("id must be kebab-case (lowercase letters, digits, hyphens)")
        if len(v) > 40:
            raise ValueError("id must be <= 40 chars")
        return v


class MatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern: Pattern
    confidence: float = Field(ge=0.0, le=1.0)
    matched_stderr_patterns: list[str]
    matched_stdout_patterns: list[str]
    score_breakdown: dict[str, float]


class AuthoringDraft(BaseModel):
    """Draft received from a Claude Code session for local-pattern authoring."""

    model_config = ConfigDict(extra="forbid")

    proposed_slug: str
    skill_md: str
    cursor_rule_mdc: str
    pytest_code: str
    expected_fix_snippet: str
    error_repro_snippet: str
    error_class: str
    languages: list[str]
    description: str

    @field_validator("proposed_slug")
    @classmethod
    def _validate_proposed_slug(cls, v: str) -> str:
        if not _SLUG_RE.fullmatch(v):
            raise ValueError(
                "proposed_slug must be kebab-case (lowercase letters, digits, hyphens)"
            )
        if len(v) > 40:
            raise ValueError("proposed_slug must be <= 40 chars")
        return v
