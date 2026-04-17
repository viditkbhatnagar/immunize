from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from immunize.models import (
    AuthoringDraft,
    CapturePayload,
    MatchResult,
    MatchRules,
    Pattern,
    Settings,
    Verification,
    VerificationResult,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(params=["cors_error.json", "import_error.json", "type_error.json"])
def payload_dict(request: pytest.FixtureRequest) -> dict:
    return json.loads((FIXTURES / request.param).read_text())


def test_capture_payload_roundtrip(payload_dict: dict) -> None:
    payload = CapturePayload.model_validate(payload_dict)
    assert payload.source == "manual"
    assert payload.exit_code == 1
    assert isinstance(payload.timestamp, datetime)
    assert payload.cwd == "/tmp/sandbox-project"


def test_capture_payload_tolerates_extra_fields() -> None:
    base = json.loads((FIXTURES / "cors_error.json").read_text())
    base["future_claude_code_field"] = {"whatever": True}
    payload = CapturePayload.model_validate(base)
    assert not hasattr(payload, "future_claude_code_field")


def test_verification_result_defaults() -> None:
    result = VerificationResult(passed=False)
    assert result.error_message is None


def test_verification_result_deprecated_aliases_mirror_passed() -> None:
    """The pre-6d fails_without_fix / passes_with_fix fields are kept as
    @property accessors returning `passed`, for backward compat with callers
    that still read them."""
    passed = VerificationResult(passed=True)
    failed = VerificationResult(passed=False, error_message="nope")
    assert passed.fails_without_fix is True and passed.passes_with_fix is True
    assert failed.fails_without_fix is False and failed.passes_with_fix is False


def test_settings_defaults_keep_semgrep_off(tmp_path: Path) -> None:
    settings = Settings(project_dir=tmp_path, state_db_path=tmp_path / ".immunize/state.db")
    assert settings.generate_semgrep is False
    assert settings.model == "claude-sonnet-4-6"
    assert settings.verify_timeout_seconds == 30
    assert settings.verify_retry_count == 1
    assert settings.min_match_confidence == 0.70
    assert settings.local_patterns_dir == tmp_path / ".immunize" / "patterns_local"


def test_settings_local_patterns_dir_explicit_override(tmp_path: Path) -> None:
    custom = tmp_path / "custom_patterns"
    settings = Settings(
        project_dir=tmp_path,
        state_db_path=tmp_path / ".immunize/state.db",
        local_patterns_dir=custom,
    )
    assert settings.local_patterns_dir == custom


@pytest.mark.parametrize("value", [-0.01, 1.01, 2.0, -1.0])
def test_settings_min_match_confidence_out_of_range(tmp_path: Path, value: float) -> None:
    with pytest.raises(ValidationError):
        Settings(
            project_dir=tmp_path,
            state_db_path=tmp_path / ".immunize/state.db",
            min_match_confidence=value,
        )


def test_settings_forbids_extras(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {
                "project_dir": str(tmp_path),
                "state_db_path": str(tmp_path / ".immunize/state.db"),
                "bonus_field": True,
            }
        )


# --- Pattern library models (Phase 1B step 2b) ------------------------------


def test_match_rules_defaults() -> None:
    rules = MatchRules()
    assert rules.stderr_patterns == []
    assert rules.stdout_patterns == []
    assert rules.error_class_hint is None
    assert rules.min_confidence == 0.70


@pytest.mark.parametrize("value", [-0.1, -0.01, 1.01, 1.5])
def test_match_rules_min_confidence_out_of_range(value: float) -> None:
    with pytest.raises(ValidationError):
        MatchRules(min_confidence=value)


def test_match_rules_forbids_extras() -> None:
    with pytest.raises(ValidationError):
        MatchRules.model_validate({"stderr_patterns": [], "nonsense": True})


def test_verification_minimal_instantiation() -> None:
    v = Verification(pytest_relative_path="test_template.py")
    assert v.pytest_relative_path == "test_template.py"
    assert v.expected_fail_without_fix is True
    assert v.expected_pass_with_fix is True
    assert v.timeout_seconds == 30


def test_verification_forbids_extras() -> None:
    with pytest.raises(ValidationError):
        Verification.model_validate({"pytest_relative_path": "t.py", "nonsense": 1})


def _pattern_kwargs(**overrides: object) -> dict:
    base: dict = {
        "id": "cors-missing-credentials",
        "version": 1,
        "author": "@viditkbhatnagar",
        "origin": "bundled",
        "error_class": "cors",
        "languages": ["javascript", "typescript"],
        "description": "CORS missing credentials header on authenticated fetch",
        "match": {"stderr_patterns": ["CORS"], "min_confidence": 0.70},
        "verification": {"pytest_relative_path": "test_template.py"},
    }
    base.update(overrides)
    return base


def test_pattern_valid_nested() -> None:
    p = Pattern.model_validate(_pattern_kwargs())
    assert p.id == "cors-missing-credentials"
    assert p.schema_version == 1
    assert p.directory is None
    assert isinstance(p.match, MatchRules)
    assert isinstance(p.verification, Verification)


@pytest.mark.parametrize(
    "slug",
    ["Foo-bar", "foo_bar", "-leading", "trailing-", "a--b", "", "a" * 41],
)
def test_pattern_id_invalid(slug: str) -> None:
    with pytest.raises(ValidationError):
        Pattern.model_validate(_pattern_kwargs(id=slug))


def test_pattern_rejects_unknown_origin() -> None:
    with pytest.raises(ValidationError):
        Pattern.model_validate(_pattern_kwargs(origin="unverified"))


def test_pattern_forbids_extras() -> None:
    payload = _pattern_kwargs()
    payload["bonus"] = "nope"
    with pytest.raises(ValidationError):
        Pattern.model_validate(payload)


def _valid_pattern() -> Pattern:
    return Pattern.model_validate(_pattern_kwargs())


def test_match_result_valid() -> None:
    result = MatchResult(
        pattern=_valid_pattern(),
        confidence=0.85,
        matched_stderr_patterns=["CORS"],
        matched_stdout_patterns=[],
        score_breakdown={"stderr": 0.6, "class_hint": 0.15, "language": 0.10},
    )
    assert result.confidence == 0.85
    assert result.score_breakdown["stderr"] == 0.6


@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_match_result_confidence_out_of_range(value: float) -> None:
    with pytest.raises(ValidationError):
        MatchResult(
            pattern=_valid_pattern(),
            confidence=value,
            matched_stderr_patterns=[],
            matched_stdout_patterns=[],
            score_breakdown={},
        )


def test_match_result_forbids_extras() -> None:
    with pytest.raises(ValidationError):
        MatchResult.model_validate(
            {
                "pattern": _pattern_kwargs(),
                "confidence": 0.8,
                "matched_stderr_patterns": [],
                "matched_stdout_patterns": [],
                "score_breakdown": {},
                "bonus": True,
            }
        )


def _draft_kwargs(**overrides: object) -> dict:
    base: dict = {
        "proposed_slug": "novel-error-pattern",
        "skill_md": "# body",
        "cursor_rule_mdc": "rule",
        "pytest_code": "def test_x(): assert True\n",
        "expected_fix_snippet": "x = 1",
        "error_repro_snippet": "x = None",
        "error_class": "other",
        "languages": ["python"],
        "description": "novel error description",
    }
    base.update(overrides)
    return base


def test_authoring_draft_valid() -> None:
    d = AuthoringDraft.model_validate(_draft_kwargs())
    assert d.proposed_slug == "novel-error-pattern"
    assert d.languages == ["python"]


@pytest.mark.parametrize(
    "slug",
    ["Foo-bar", "foo_bar", "-leading", "trailing-", "a--b", "", "a" * 41],
)
def test_authoring_draft_slug_invalid(slug: str) -> None:
    with pytest.raises(ValidationError):
        AuthoringDraft.model_validate(_draft_kwargs(proposed_slug=slug))


def test_authoring_draft_forbids_extras() -> None:
    payload = _draft_kwargs()
    payload["bonus"] = "nope"
    with pytest.raises(ValidationError):
        AuthoringDraft.model_validate(payload)
