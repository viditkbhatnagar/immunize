from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import pytest

from immunize.config import ConfigError, load_settings
from immunize.generate import GenerateError
from immunize.generate.pytest_gen import generate_pytest
from immunize.models import CapturePayload, Diagnosis, Settings

_VALID_OUTPUT = {
    "error_repro_snippet": "def add(a, b):\n    return a - b\n",
    "pytest_code": (
        "from app_under_test import add\n\n"
        "def test_add() -> None:\n"
        "    assert add(2, 3) == 5\n"
    ),
    "expected_fix_snippet": "def add(a, b):\n    return a + b\n",
}
_VALID_OUTPUT_JSON = json.dumps(_VALID_OUTPUT)


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for k in [k for k in os.environ if k.startswith("IMMUNIZE_")]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))


@pytest.fixture
def diagnosis() -> Diagnosis:
    return Diagnosis(
        root_cause="rc",
        error_class="type_error",
        is_generalizable=True,
        canonical_description=(
            "A function mis-returns subtraction where addition is expected, "
            "silently corrupting totals."
        ),
        fix_summary="fs",
        language="python",
        slug="add-subtraction-bug",
        semgrep_applicable=False,
    )


@pytest.fixture
def payload() -> CapturePayload:
    return CapturePayload(
        source="manual",
        stderr="assert 5 == -1",
        exit_code=1,
        cwd="/tmp/x",
        timestamp=datetime(2026, 4, 17, 12, 0, tzinfo=timezone.utc),
        project_fingerprint="sha256-proj",
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return load_settings(cwd=tmp_path)


def _fake_client(text: str) -> SimpleNamespace:
    def _create(**_: Any) -> Any:
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])

    return SimpleNamespace(messages=SimpleNamespace(create=_create))


def test_happy_path(diagnosis: Diagnosis, payload: CapturePayload, settings: Settings) -> None:
    out = generate_pytest(diagnosis, payload, settings, client=_fake_client(_VALID_OUTPUT_JSON))
    assert "def test_add" in out.pytest_code
    assert "return a + b" in out.expected_fix_snippet
    assert "return a - b" in out.error_repro_snippet


def test_drift_code_fence(
    diagnosis: Diagnosis, payload: CapturePayload, settings: Settings
) -> None:
    fenced = f"```json\n{_VALID_OUTPUT_JSON}\n```"
    out = generate_pytest(diagnosis, payload, settings, client=_fake_client(fenced))
    assert "def test_add" in out.pytest_code


def test_drift_preamble(
    diagnosis: Diagnosis, payload: CapturePayload, settings: Settings
) -> None:
    with_preamble = f"Here's the test:\n\n{_VALID_OUTPUT_JSON}"
    out = generate_pytest(diagnosis, payload, settings, client=_fake_client(with_preamble))
    assert "return a + b" in out.expected_fix_snippet


def test_drift_trailing_whitespace(
    diagnosis: Diagnosis, payload: CapturePayload, settings: Settings
) -> None:
    trailing = f"{_VALID_OUTPUT_JSON}\n\n   \n"
    out = generate_pytest(diagnosis, payload, settings, client=_fake_client(trailing))
    assert "def test_add" in out.pytest_code


def test_no_internal_retry_on_invalid_json(
    diagnosis: Diagnosis, payload: CapturePayload, settings: Settings
) -> None:
    """Per Refinement B, pytest_gen does NOT retry internally. One bad response → GenerateError."""
    calls: list[int] = []

    def _create(**_: Any) -> Any:
        calls.append(1)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="not json")])

    client = SimpleNamespace(messages=SimpleNamespace(create=_create))
    with pytest.raises(GenerateError, match="invalid JSON"):
        generate_pytest(diagnosis, payload, settings, client=client)
    assert len(calls) == 1  # no retry


def test_missing_key_raises_generate_error(
    diagnosis: Diagnosis, payload: CapturePayload, settings: Settings
) -> None:
    incomplete = json.dumps({"pytest_code": "x", "expected_fix_snippet": "y"})
    with pytest.raises(GenerateError, match="invalid JSON"):
        generate_pytest(diagnosis, payload, settings, client=_fake_client(incomplete))


def test_extra_field_raises_generate_error(
    diagnosis: Diagnosis, payload: CapturePayload, settings: Settings
) -> None:
    bloated = dict(_VALID_OUTPUT)
    bloated["bonus"] = "nope"
    with pytest.raises(GenerateError, match="invalid JSON"):
        generate_pytest(diagnosis, payload, settings, client=_fake_client(json.dumps(bloated)))


def test_auth_error_raises_config_error(
    diagnosis: Diagnosis, payload: CapturePayload, settings: Settings
) -> None:
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(401, request=req, content=b'{"error":"unauthorized"}')
    err = anthropic.AuthenticationError(message="no", response=resp, body={})

    def _create(**_: Any) -> Any:
        raise err

    client = SimpleNamespace(messages=SimpleNamespace(create=_create))
    with pytest.raises(ConfigError, match="invalid or lacks permissions"):
        generate_pytest(diagnosis, payload, settings, client=client)
