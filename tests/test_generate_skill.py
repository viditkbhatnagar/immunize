from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import pytest

from immunize.config import ConfigError, load_settings
from immunize.generate import GenerateError
from immunize.generate.skill import generate_skill_md
from immunize.models import CapturePayload, Diagnosis, Settings


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    for k in [k for k in os.environ if k.startswith("IMMUNIZE_")]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))


@pytest.fixture
def diagnosis() -> Diagnosis:
    return Diagnosis(
        root_cause="Fetch call omits credentials so the server rejects the preflight.",
        error_class="cors",
        is_generalizable=True,
        canonical_description=(
            "Cross-origin authenticated fetches must set credentials: 'include' "
            "and the server must respond with Access-Control-Allow-Credentials: true."
        ),
        fix_summary="Set credentials: 'include' and configure the server CORS policy.",
        language="typescript",
        slug="cors-missing-credentials",
        semgrep_applicable=False,
    )


@pytest.fixture
def payload() -> CapturePayload:
    return CapturePayload(
        source="manual",
        stderr="Access to fetch blocked by CORS policy",
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
    raw = (
        "---\n"
        "name: immunize-cors-missing-credentials\n"
        "description: stub\n"
        "---\n\n"
        "# Avoid CORS errors\n\n"
        "Always set credentials: 'include'.\n"
    )
    md = generate_skill_md(diagnosis, payload, settings, client=_fake_client(raw))
    assert md.startswith("---\nname: immunize-cors-missing-credentials\n")
    assert "Avoid CORS errors" in md


def test_prepends_frontmatter_when_missing(
    diagnosis: Diagnosis, payload: CapturePayload, settings: Settings
) -> None:
    raw = "# Title without frontmatter\n\nSome body text."
    md = generate_skill_md(diagnosis, payload, settings, client=_fake_client(raw))
    assert md.startswith("---\nname: immunize-cors-missing-credentials\n")
    assert "Some body text." in md


def test_strips_code_fences(
    diagnosis: Diagnosis, payload: CapturePayload, settings: Settings
) -> None:
    raw = (
        "```markdown\n"
        "---\nname: immunize-cors-missing-credentials\ndescription: stub\n---\n\n"
        "Body.\n"
        "```"
    )
    md = generate_skill_md(diagnosis, payload, settings, client=_fake_client(raw))
    assert "```" not in md
    assert md.startswith("---\nname: immunize-cors-missing-credentials\n")


def test_replaces_wrong_name(
    diagnosis: Diagnosis, payload: CapturePayload, settings: Settings
) -> None:
    raw = (
        "---\nname: bogus-name\ndescription: anything\n---\n\n"
        "# Good body\n\nReal content here."
    )
    md = generate_skill_md(diagnosis, payload, settings, client=_fake_client(raw))
    assert "name: immunize-cors-missing-credentials" in md
    assert "bogus-name" not in md
    assert "Real content here." in md


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
        generate_skill_md(diagnosis, payload, settings, client=client)


def test_api_error_raises_generate_error(
    diagnosis: Diagnosis, payload: CapturePayload, settings: Settings
) -> None:
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(500, request=req, content=b"boom")
    err = anthropic.APIStatusError(message="boom", response=resp, body={})

    def _create(**_: Any) -> Any:
        raise err

    client = SimpleNamespace(messages=SimpleNamespace(create=_create))
    with pytest.raises(GenerateError, match="generation failed"):
        generate_skill_md(diagnosis, payload, settings, client=client)
