from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import pytest

from immunize import diagnose
from immunize.config import ConfigError, load_settings
from immunize.models import CapturePayload, Settings

_VALID_DIAG_DICT = {
    "root_cause": "Fetch call omits credentials causing the server to reject preflight.",
    "error_class": "cors",
    "is_generalizable": True,
    "canonical_description": (
        "Cross-origin authenticated fetches must set credentials 'include' and the server "
        "must respond with Access-Control-Allow-Credentials true and an explicit origin."
    ),
    "fix_summary": "Set credentials: 'include' on fetch and configure CORS on the server.",
    "language": "typescript",
    "slug": "cors-missing-credentials",
    "semgrep_applicable": False,
}
_VALID_DIAG_JSON = json.dumps(_VALID_DIAG_DICT)


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list({k for k in __import__("os").environ if k.startswith("IMMUNIZE_")}):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))


@pytest.fixture
def payload() -> CapturePayload:
    return CapturePayload(
        source="manual",
        stderr="CORS error: missing credentials",
        exit_code=1,
        cwd="/tmp/x",
        timestamp=datetime(2026, 4, 17, 12, 0, tzinfo=timezone.utc),
        project_fingerprint="sha256-proj",
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return load_settings(cwd=tmp_path)


def _text_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def _fake_client(*responses: Any) -> SimpleNamespace:
    """Return a Mock-like client whose messages.create returns the next response on each call.

    Each entry in *responses is either a string (treated as TextBlock text) or an Exception
    (raised on that call).
    """
    calls = iter(responses)

    def _create(**_: Any) -> Any:
        nxt = next(calls)
        if isinstance(nxt, Exception):
            raise nxt
        return _text_response(nxt)

    return SimpleNamespace(messages=SimpleNamespace(create=_create))


def test_happy_path(payload: CapturePayload, settings: Settings) -> None:
    client = _fake_client(_VALID_DIAG_JSON)
    diag = diagnose.diagnose(payload, settings, client=client)
    assert diag.slug == "cors-missing-credentials"
    assert diag.error_class == "cors"


def test_drift_code_fence(payload: CapturePayload, settings: Settings) -> None:
    fenced = f"```json\n{_VALID_DIAG_JSON}\n```"
    diag = diagnose.diagnose(payload, settings, client=_fake_client(fenced))
    assert diag.slug == "cors-missing-credentials"


def test_drift_preamble(payload: CapturePayload, settings: Settings) -> None:
    with_preamble = f"Here's the diagnosis:\n\n{_VALID_DIAG_JSON}"
    diag = diagnose.diagnose(payload, settings, client=_fake_client(with_preamble))
    assert diag.error_class == "cors"


def test_drift_trailing_whitespace(payload: CapturePayload, settings: Settings) -> None:
    trailing = f"{_VALID_DIAG_JSON}\n\n   \n"
    diag = diagnose.diagnose(payload, settings, client=_fake_client(trailing))
    assert diag.is_generalizable is True


def test_retry_on_validation_failure(payload: CapturePayload, settings: Settings) -> None:
    calls: list[str] = []

    def _create(**kwargs: Any) -> Any:
        calls.append(kwargs.get("system", ""))
        text = "not even close to JSON" if len(calls) == 1 else _VALID_DIAG_JSON
        return _text_response(text)

    client = SimpleNamespace(messages=SimpleNamespace(create=_create))
    diag = diagnose.diagnose(payload, settings, client=client)
    assert diag.slug == "cors-missing-credentials"
    assert len(calls) == 2
    assert "failed schema validation" in calls[1]


def test_retry_still_invalid_raises(payload: CapturePayload, settings: Settings) -> None:
    client = _fake_client("garbage 1", "garbage 2")
    with pytest.raises(diagnose.DiagnoseError, match="failed validation twice"):
        diagnose.diagnose(payload, settings, client=client)


def test_missing_api_key_raises_config_error(
    payload: CapturePayload, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    settings = load_settings(cwd=tmp_path)
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY is not set"):
        diagnose.diagnose(payload, settings)


def _auth_error() -> anthropic.AuthenticationError:
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(status_code=401, request=req, content=b'{"error":"unauthorized"}')
    return anthropic.AuthenticationError(message="Unauthorized", response=resp, body={})


@pytest.mark.parametrize("cls", ["cors", "network", "auth", "rate_limit", "config"])
def test_non_source_classes_force_semgrep_false(
    payload: CapturePayload, settings: Settings, cls: str
) -> None:
    drifted = dict(_VALID_DIAG_DICT)
    drifted["error_class"] = cls
    drifted["semgrep_applicable"] = True
    client = _fake_client(json.dumps(drifted))
    diag = diagnose.diagnose(payload, settings, client=client)
    assert diag.error_class == cls
    assert diag.semgrep_applicable is False


def test_source_class_keeps_model_semgrep_decision(
    payload: CapturePayload, settings: Settings
) -> None:
    drifted = dict(_VALID_DIAG_DICT)
    drifted["error_class"] = "type_error"
    drifted["semgrep_applicable"] = True
    client = _fake_client(json.dumps(drifted))
    diag = diagnose.diagnose(payload, settings, client=client)
    assert diag.semgrep_applicable is True


def test_401_auth_error_raises_config_error(
    payload: CapturePayload, settings: Settings
) -> None:
    client = _fake_client(_auth_error())
    with pytest.raises(ConfigError, match="invalid or lacks permissions"):
        diagnose.diagnose(payload, settings, client=client)


def test_smart_truncate_short_text_passthrough() -> None:
    assert diagnose._smart_truncate("short", head=10, tail=10) == "short"


def test_smart_truncate_long_text_keeps_tail() -> None:
    long_text = "H" * 500 + "M" * 4000 + "TAIL_SIGNAL"
    out = diagnose._smart_truncate(long_text, head=1000, tail=3000)
    assert out.endswith("TAIL_SIGNAL")
    assert "chars truncated" in out
    assert len(out) < len(long_text)


def test_extract_json_handles_fenced_and_preamble() -> None:
    assert diagnose._extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert diagnose._extract_json('Here is it:\n{"a": 1}\nthanks') == '{"a": 1}'
    assert diagnose._extract_json('{"a": 1}\n\n') == '{"a": 1}'
