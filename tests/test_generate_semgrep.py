from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from immunize.config import load_settings
from immunize.generate.semgrep import generate_semgrep_yaml
from immunize.models import CapturePayload, Diagnosis, Settings


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for k in [k for k in os.environ if k.startswith("IMMUNIZE_")]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))


@pytest.fixture
def diagnosis_source_pattern() -> Diagnosis:
    return Diagnosis(
        root_cause="hardcoded secret in source",
        error_class="type_error",
        is_generalizable=True,
        canonical_description=(
            "Hardcoded API tokens in source code should never be committed; "
            "use environment variables instead."
        ),
        fix_summary="Move token to env var.",
        language="python",
        slug="hardcoded-api-token",
        semgrep_applicable=True,
    )


@pytest.fixture
def payload() -> CapturePayload:
    return CapturePayload(
        source="manual",
        stderr="x",
        exit_code=1,
        cwd="/tmp/x",
        timestamp=datetime(2026, 4, 17, 12, 0, tzinfo=timezone.utc),
        project_fingerprint="sha256-proj",
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return load_settings(cwd=tmp_path)


def _fake_client(text: str) -> SimpleNamespace:
    called: list[int] = []

    def _create(**_: Any) -> Any:
        called.append(1)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])

    client = SimpleNamespace(messages=SimpleNamespace(create=_create))
    client._called = called  # type: ignore[attr-defined]
    return client


_VALID_YAML = """\
rules:
  - id: immunize-hardcoded-api-token
    pattern: API_TOKEN = "..."
    message: Move hardcoded tokens to env vars.
    severity: WARNING
    languages: [python]
"""


def test_gated_off_by_setting(
    diagnosis_source_pattern: Diagnosis,
    payload: CapturePayload,
    settings: Settings,
) -> None:
    """Default settings.generate_semgrep=False → return None without any client call."""
    client = _fake_client(_VALID_YAML)
    result = generate_semgrep_yaml(diagnosis_source_pattern, payload, settings, client=client)
    assert result is None
    assert client._called == []  # type: ignore[attr-defined]


def test_gated_off_by_diagnosis_flag(
    payload: CapturePayload, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IMMUNIZE_GENERATE_SEMGREP", "true")
    settings = load_settings(cwd=settings.project_dir)
    diag = Diagnosis(
        root_cause="rc",
        error_class="cors",
        is_generalizable=True,
        canonical_description="x" * 30,
        fix_summary="fs",
        language="typescript",
        slug="s",
        semgrep_applicable=False,
    )
    client = _fake_client(_VALID_YAML)
    assert generate_semgrep_yaml(diag, payload, settings, client=client) is None
    assert client._called == []  # type: ignore[attr-defined]


def test_gated_on_valid_yaml_returned(
    diagnosis_source_pattern: Diagnosis,
    payload: CapturePayload,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IMMUNIZE_GENERATE_SEMGREP", "true")
    settings = load_settings(cwd=settings.project_dir)
    client = _fake_client(_VALID_YAML)
    result = generate_semgrep_yaml(diagnosis_source_pattern, payload, settings, client=client)
    assert result is not None
    assert "immunize-hardcoded-api-token" in result


def test_gated_on_invalid_yaml_returns_none(
    diagnosis_source_pattern: Diagnosis,
    payload: CapturePayload,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IMMUNIZE_GENERATE_SEMGREP", "true")
    settings = load_settings(cwd=settings.project_dir)
    client = _fake_client("this is not: valid: yaml: at: all: [[[")
    result = generate_semgrep_yaml(diagnosis_source_pattern, payload, settings, client=client)
    assert result is None


def test_gated_on_wrong_rule_id_returns_none(
    diagnosis_source_pattern: Diagnosis,
    payload: CapturePayload,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IMMUNIZE_GENERATE_SEMGREP", "true")
    settings = load_settings(cwd=settings.project_dir)
    wrong_id = _VALID_YAML.replace("immunize-hardcoded-api-token", "wrong-id")
    client = _fake_client(wrong_id)
    result = generate_semgrep_yaml(diagnosis_source_pattern, payload, settings, client=client)
    assert result is None


def test_gated_on_strips_code_fences(
    diagnosis_source_pattern: Diagnosis,
    payload: CapturePayload,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IMMUNIZE_GENERATE_SEMGREP", "true")
    settings = load_settings(cwd=settings.project_dir)
    fenced = f"```yaml\n{_VALID_YAML}\n```"
    client = _fake_client(fenced)
    result = generate_semgrep_yaml(diagnosis_source_pattern, payload, settings, client=client)
    assert result is not None
    assert "```" not in result
