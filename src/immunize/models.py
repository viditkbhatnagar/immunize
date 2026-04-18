from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class VerificationResult(BaseModel):
    # extra="ignore" (not "forbid") keeps backward-compat with the pre-6d
    # call-sites that passed fails_without_fix / passes_with_fix explicitly;
    # those are now derived from `passed` via the properties below. The
    # authoring-time dual-run semantics live in `scripts/pattern_lint.py`.
    model_config = ConfigDict(extra="ignore")

    passed: bool
    error_message: str | None = None

    @property
    def fails_without_fix(self) -> bool:
        """DEPRECATED: mirrors `passed`. Dual-run semantics moved to pattern_lint."""
        return self.passed

    @property
    def passes_with_fix(self) -> bool:
        """DEPRECATED: mirrors `passed`. Dual-run semantics moved to pattern_lint."""
        return self.passed


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = "claude-sonnet-4-6"
    generate_semgrep: bool = False
    verify_timeout_seconds: int = 30
    verify_retry_count: int = 1
    project_dir: Path
    state_db_path: Path
    # Global floor on match confidence, applied AFTER each pattern's own
    # min_confidence filter. Default 0.30 so per-pattern thresholds (which
    # the author tunes for precision) remain authoritative; raise this via
    # IMMUNIZE_MIN_MATCH_CONFIDENCE in CI/strict-mode deployments to gate
    # every pattern at a higher shared threshold. Before v0.2.0 this was
    # 0.70, which silently shadowed per-pattern calibration and made the
    # lower-threshold patterns dead code.
    min_match_confidence: float = Field(default=0.30, ge=0.0, le=1.0)
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
