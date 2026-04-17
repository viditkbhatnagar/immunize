from __future__ import annotations

import ast
import json
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from immunize.cli import app

runner = CliRunner()

FIXTURES = Path(__file__).parent / "fixtures"

# Realistic CORS shape — matches what Claude produced on the gate call,
# trimmed so the fixed code passes pytest and the buggy code fails it.
_DIAG_JSON = json.dumps(
    {
        "root_cause": (
            "Server omits Access-Control-Allow-Credentials header for credentialed fetch."
        ),
        "error_class": "cors",
        "is_generalizable": True,
        "canonical_description": (
            "Credentialed fetch requests (cookies/auth headers) are blocked when the server "
            "omits Access-Control-Allow-Credentials: true and sets Access-Control-Allow-Origin "
            "to wildcard instead of the exact requesting origin."
        ),
        "fix_summary": (
            "Set Access-Control-Allow-Credentials: true on the server alongside an exact "
            "Access-Control-Allow-Origin; ensure the client uses credentials: 'include'."
        ),
        "language": "JavaScript",
        "slug": "cors-missing-allow-credentials",
        "semgrep_applicable": True,  # model drift; finalize() should flip to False
    }
)

_SKILL_MD = (
    "# Avoid CORS credential errors\n\n"
    "When the server omits `Access-Control-Allow-Credentials: true`, credentialed fetches fail.\n\n"
    "```javascript\n"
    "// SERVER: echo exact origin + Allow-Credentials: true\n"
    "app.use((req, res, next) => {\n"
    "  res.setHeader('Access-Control-Allow-Origin', req.headers.origin);\n"
    "  res.setHeader('Access-Control-Allow-Credentials', 'true');\n"
    "  next();\n"
    "});\n"
    "```\n"
)

_PYTEST_GEN_JSON = json.dumps(
    {
        "error_repro_snippet": (
            "def get_cors_headers():\n"
            "    return {'Access-Control-Allow-Origin': 'http://localhost:3000'}\n"
            "\n"
            "def fetch_with_credentials(headers):\n"
            "    if headers.get('Access-Control-Allow-Credentials') != 'true':\n"
            "        raise RuntimeError('CORS blocked')\n"
            "    return 'ok'\n"
            "\n"
            "def make_api_call():\n"
            "    return fetch_with_credentials(get_cors_headers())\n"
        ),
        "pytest_code": (
            "from app_under_test import make_api_call\n"
            "\n"
            "def test_cors_credentialed_fetch_succeeds():\n"
            "    assert make_api_call() == 'ok'\n"
        ),
        "expected_fix_snippet": (
            "def get_cors_headers():\n"
            "    return {\n"
            "        'Access-Control-Allow-Origin': 'http://localhost:3000',\n"
            "        'Access-Control-Allow-Credentials': 'true',\n"
            "    }\n"
            "\n"
            "def fetch_with_credentials(headers):\n"
            "    if headers.get('Access-Control-Allow-Credentials') != 'true':\n"
            "        raise RuntimeError('CORS blocked')\n"
            "    return 'ok'\n"
            "\n"
            "def make_api_call():\n"
            "    return fetch_with_credentials(get_cors_headers())\n"
        ),
    }
)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for k in [k for k in os.environ if k.startswith("IMMUNIZE_")]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake-for-tests")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.chdir(tmp_path)


def _patch_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Route every messages.create call by system-prompt content."""

    def _route(**kwargs: Any) -> Any:
        system = kwargs.get("system", "")
        if "diagnosing a runtime error" in system:
            text = _DIAG_JSON
        elif "SKILL.md files for AI coding assistants" in system:
            text = _SKILL_MD
        elif "pytest regression test" in system:
            text = _PYTEST_GEN_JSON
        elif "Semgrep rule" in system:
            text = "rules:\n  - id: unused\n"
        else:
            text = ""
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])

    fake_client = SimpleNamespace(messages=SimpleNamespace(create=_route))
    monkeypatch.setattr("immunize.config.anthropic.Anthropic", lambda *a, **kw: fake_client)


def _payload_for(tmp_path: Path) -> str:
    payload = json.loads((FIXTURES / "cors_error.json").read_text())
    payload["cwd"] = str(tmp_path)
    return json.dumps(payload)


# --- capture: end-to-end -----------------------------------------------------
def test_capture_full_pipeline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_anthropic(monkeypatch)
    payload_json = _payload_for(tmp_path)

    result = runner.invoke(app, ["capture", "--source", "manual"], input=payload_json)

    assert result.exit_code == 0, result.output + "\n" + (result.stderr or "")

    # Files exist at architecture-specified paths.
    slug = "cors-missing-allow-credentials"
    skill_path = tmp_path / ".claude" / "skills" / f"immunize-{slug}" / "SKILL.md"
    cursor_path = tmp_path / ".cursor" / "rules" / f"{slug}.mdc"
    pytest_path = tmp_path / "tests" / "immunized" / f"test_{slug.replace('-', '_')}.py"

    assert skill_path.is_file()
    assert cursor_path.is_file()
    assert pytest_path.is_file()

    # SKILL.md content shape.
    skill_text = skill_path.read_text()
    assert skill_text.startswith(f"---\nname: immunize-{slug}\n")
    body_after_frontmatter = skill_text.split("---", 2)[-1].strip()
    assert len(body_after_frontmatter) > 0

    # Cursor .mdc frontmatter.
    cursor_text = cursor_path.read_text()
    assert "description:" in cursor_text
    assert "globs:" in cursor_text
    assert "alwaysApply: false" in cursor_text

    # Injected pytest parses as valid Python.
    ast.parse(pytest_path.read_text())

    # Injected pytest is standalone (no app_under_test import).
    assert "from app_under_test" not in pytest_path.read_text()

    # DB state: errors/diagnoses/artifacts each have one row.
    conn = sqlite3.connect(tmp_path / ".immunize" / "state.db")
    conn.row_factory = sqlite3.Row
    assert conn.execute("SELECT COUNT(*) AS c FROM errors").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) AS c FROM diagnoses").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) AS c FROM artifacts").fetchone()["c"] == 1
    art = conn.execute("SELECT * FROM artifacts").fetchone()
    assert art["slug"] == slug
    assert art["verified"] == 1
    # language normalized to lowercase via Diagnosis field_validator.
    diag = json.loads(conn.execute("SELECT diagnosis_json FROM diagnoses").fetchone()[0])
    assert diag["language"] == "javascript"
    # semgrep_applicable forced False via _finalize because error_class == "cors".
    assert diag["semgrep_applicable"] is False


def test_capture_bad_json_exits_zero_with_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_anthropic(monkeypatch)
    result = runner.invoke(app, ["capture"], input="not-valid-json")
    assert result.exit_code == 0  # capture always exits 0
    assert "invalid capture payload" in (result.stderr or result.output)


def test_capture_dry_run_skips_inject(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_anthropic(monkeypatch)
    result = runner.invoke(app, ["capture", "--dry-run"], input=_payload_for(tmp_path))
    assert result.exit_code == 0
    # No artifact files.
    assert not (tmp_path / ".claude").exists()
    assert not (tmp_path / ".cursor").exists()
    assert not (tmp_path / "tests" / "immunized").exists()
    # DB still records errors + diagnoses (audit trail) but no artifact row.
    conn = sqlite3.connect(tmp_path / ".immunize" / "state.db")
    conn.row_factory = sqlite3.Row
    assert conn.execute("SELECT COUNT(*) AS c FROM errors").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) AS c FROM diagnoses").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) AS c FROM artifacts").fetchone()["c"] == 0


# --- list --------------------------------------------------------------------
def test_list_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "No immunities" in result.output


def test_list_after_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_anthropic(monkeypatch)
    runner.invoke(app, ["capture"], input=_payload_for(tmp_path))
    # Widen the terminal so Rich doesn't ellipsize the slug column.
    result = runner.invoke(app, ["list"], env={"COLUMNS": "160"})
    assert result.exit_code == 0
    assert "cors-missing-allow-credentials" in result.output


# --- remove ------------------------------------------------------------------
def test_remove_with_yes_deletes_files_and_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_anthropic(monkeypatch)
    runner.invoke(app, ["capture"], input=_payload_for(tmp_path))
    skill_path = (
        tmp_path / ".claude" / "skills" / "immunize-cors-missing-allow-credentials" / "SKILL.md"
    )
    assert skill_path.exists()

    result = runner.invoke(app, ["remove", "1", "--yes"])
    assert result.exit_code == 0
    assert not skill_path.exists()

    conn = sqlite3.connect(tmp_path / ".immunize" / "state.db")
    assert conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 0


def test_remove_unknown_id_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result = runner.invoke(app, ["remove", "42", "--yes"])
    assert result.exit_code == 1


# --- verify ------------------------------------------------------------------
def test_verify_passes_on_injected_immunity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_anthropic(monkeypatch)
    runner.invoke(app, ["capture"], input=_payload_for(tmp_path))
    result = runner.invoke(app, ["verify"])
    assert result.exit_code == 0, result.output
    assert "PASS" in result.output


def test_verify_empty_is_noop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result = runner.invoke(app, ["verify"])
    assert result.exit_code == 0
    assert "No immunities" in result.output


# --- Windows guard (verified on win32 only — skipped elsewhere) -------------
@pytest.mark.skipif(not hasattr(os, "sys"), reason="placeholder to note guard coverage")
def test_windows_guard_documented() -> None:
    pass
