from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from immunize.models import (
    CapturePayload,
    Diagnosis,
    GeneratedArtifacts,
    Settings,
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


@pytest.mark.parametrize("slug", ["cors-missing-credentials", "abc", "a1-b2-c3"])
def test_diagnosis_slug_valid(slug: str) -> None:
    diag = _diag(slug=slug)
    assert diag.slug == slug


@pytest.mark.parametrize(
    "slug",
    ["Foo-bar", "foo_bar", "-leading", "trailing-", "a--b", "", "a" * 41],
)
def test_diagnosis_slug_invalid(slug: str) -> None:
    with pytest.raises(ValidationError):
        _diag(slug=slug)


def test_diagnosis_accepts_network_error_class() -> None:
    diag = _diag(error_class="network")
    assert diag.error_class == "network"


def test_diagnosis_rejects_unknown_error_class() -> None:
    with pytest.raises(ValidationError):
        _diag(error_class="teapot")


def test_diagnosis_forbids_extra_fields() -> None:
    payload = _diag_kwargs()
    payload["hallucinated_field"] = "oops"
    with pytest.raises(ValidationError):
        Diagnosis.model_validate(payload)


def test_generated_artifacts_forbids_extras() -> None:
    with pytest.raises(ValidationError):
        GeneratedArtifacts.model_validate(
            {
                "skill_md": "a",
                "cursor_rule": "b",
                "pytest_code": "c",
                "expected_fix_snippet": "d",
                "error_repro_snippet": "e",
                "bonus": "nope",
            }
        )


def test_verification_result_defaults() -> None:
    result = VerificationResult(passed=False, fails_without_fix=False, passes_with_fix=False)
    assert result.error_message is None


def test_settings_defaults_keep_semgrep_off(tmp_path: Path) -> None:
    settings = Settings(project_dir=tmp_path, state_db_path=tmp_path / ".immunize/state.db")
    assert settings.generate_semgrep is False
    assert settings.model == "claude-sonnet-4-6"
    assert settings.verify_timeout_seconds == 30
    assert settings.verify_retry_count == 1


def _diag_kwargs(**overrides: object) -> dict:
    base = {
        "root_cause": "Missing credentials on CORS fetch.",
        "error_class": "cors",
        "is_generalizable": True,
        "canonical_description": (
            "Requests to authenticated cross-origin endpoints must set credentials: 'include'."
        ),
        "fix_summary": (
            "Add credentials: 'include' on fetch and ensure server sends Allow-Credentials."
        ),
        "language": "typescript",
        "slug": "cors-missing-credentials",
        "semgrep_applicable": False,
    }
    base.update(overrides)
    return base


def _diag(**overrides: object) -> Diagnosis:
    return Diagnosis.model_validate(_diag_kwargs(**overrides))
