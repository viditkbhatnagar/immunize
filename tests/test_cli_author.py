"""Tests for ``immunize author-pattern``.

All 8 Step 7 scenarios. Zero network: `anthropic.Anthropic` is mocked at the
module level before `author_pattern_cmd`'s lazy import resolves, so the real
SDK never sees a request. `_verify_scratch` is patched independently in each
test to decouple "does the Claude path do the right thing" from "does pytest
subprocess pass on a synthetic draft."
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture
from typer.testing import CliRunner

from immunize.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for k in [k for k in os.environ if k.startswith("IMMUNIZE_")]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.chdir(tmp_path)


def _valid_payload_json(cwd: Path) -> str:
    return json.dumps(
        {
            "source": "manual",
            "stderr": "TypeError: Cannot read properties of undefined (reading 'map')",
            "exit_code": 1,
            "cwd": str(cwd),
            "timestamp": "2026-04-17T00:00:00Z",
            "project_fingerprint": "authtest",
        }
    )


def _analysis_input() -> dict[str, Any]:
    return {
        "proposed_slug": "undefined-map-access",
        "error_class": "runtime",
        "languages": ["javascript"],
        "description": "Calling .map on an undefined value.",
        "stderr_patterns": ["Cannot read properties of undefined \\(reading 'map'\\)"],
        "error_class_hint": None,
        "min_confidence": 0.75,
    }


def _drafting_input() -> dict[str, Any]:
    return {
        "skill_md": (
            "---\nname: immunize-undefined-map-access\n"
            "description: Guard array access before mapping over it.\n---\n\n"
            "# undefined-map-access\n\nBefore calling `.map`, check the array exists.\n"
        ),
        "cursor_rule_mdc": (
            "---\ndescription: Guard before map\nglobs: **/*.js, **/*.jsx\n"
            "alwaysApply: false\n---\n\nCheck array before .map.\n"
        ),
        "pytest_code": (
            "from pathlib import Path\n\n"
            "def test_guarded():\n"
            "    src = (Path(__file__).parent / 'fixtures' / 'repro.js').read_text()\n"
            "    assert 'items?.map' in src or 'if (items)' in src, 'array not guarded'\n"
        ),
        "error_repro_snippet": "const render = (items) => items.map(x => x);\n",
        "expected_fix_snippet": "const render = (items) => items?.map(x => x);\n",
    }


def _tool_use_response(name: str, input_dict: dict[str, Any]) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.input = input_dict
    resp = MagicMock()
    resp.content = [block]
    resp.stop_reason = "tool_use"
    return resp


def _no_tool_use_response() -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.name = None
    block.input = None
    resp = MagicMock()
    resp.content = [block]
    resp.stop_reason = "end_turn"
    return resp


@pytest.fixture
def mock_anthropic(mocker: MockerFixture) -> MagicMock:
    """Patch anthropic.Anthropic so the lazy import inside author_pattern_cmd
    picks up a MagicMock client. Callers configure `.messages.create.side_effect`.
    """
    import anthropic  # ensure module is imported before patching its attribute

    _ = anthropic  # silence flake
    client = MagicMock()
    mocker.patch("anthropic.Anthropic", return_value=client)
    return client


def _write_input(tmp_path: Path) -> Path:
    p = tmp_path / "err.json"
    p.write_text(_valid_payload_json(tmp_path))
    return p


def _run(tmp_path: Path, api_key: str | None = "sk-test") -> Any:
    out = tmp_path / "patterns"
    out.mkdir(exist_ok=True)
    env: dict[str, Any] = {}
    if api_key is not None:
        env["ANTHROPIC_API_KEY"] = api_key
    return runner.invoke(
        app,
        [
            "author-pattern",
            "--from-error",
            str(_write_input(tmp_path)),
            "--output",
            str(out),
        ],
        env=env,
    )


# --- scenarios --------------------------------------------------------------


def test_missing_api_key_exits_1_with_clear_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario #2 — API key check short-circuits before any SDK work.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = _run(tmp_path, api_key=None)
    assert result.exit_code == 1
    assert "ANTHROPIC_API_KEY" in result.output


def test_missing_input_file_exits_with_typer_validation_error(tmp_path: Path) -> None:
    # Scenario #3 — Typer's Option(exists=True) trips before our code runs.
    out = tmp_path / "patterns"
    out.mkdir()
    result = runner.invoke(
        app,
        [
            "author-pattern",
            "--from-error",
            str(tmp_path / "does-not-exist.json"),
            "--output",
            str(out),
        ],
        env={"ANTHROPIC_API_KEY": "sk-test"},
    )
    assert result.exit_code == 2


def test_malformed_error_json_exits_1(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Scenario #4 — JSONDecodeError or ValidationError surface as exit 1.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    bad = tmp_path / "err.json"
    bad.write_text("this is not json")
    out = tmp_path / "patterns"
    out.mkdir()
    result = runner.invoke(
        app,
        ["author-pattern", "--from-error", str(bad), "--output", str(out)],
    )
    assert result.exit_code == 1
    assert "failed to read" in result.output or "CapturePayload" in result.output


def test_happy_path_writes_pattern_to_output_dir(
    mock_anthropic: MagicMock, mocker: MockerFixture, tmp_path: Path
) -> None:
    # Scenario #1 — valid analysis + drafting + verification passes.
    mock_anthropic.messages.create.side_effect = [
        _tool_use_response("propose_pattern_metadata", _analysis_input()),
        _tool_use_response("emit_pattern_draft", _drafting_input()),
    ]
    mocker.patch("immunize.authoring.cli_author._verify_scratch", return_value=[])

    result = _run(tmp_path)
    assert result.exit_code == 0, result.output

    final = tmp_path / "patterns" / "undefined-map-access"
    assert final.is_dir()
    assert (final / "pattern.yaml").is_file()
    assert (final / "SKILL.md").is_file()
    assert (final / "cursor_rule.mdc").is_file()
    assert (final / "test_template.py").is_file()
    assert (final / "fixtures" / "repro.js").is_file()
    assert (final / "fixtures" / "fix.js").is_file()


def test_malformed_drafting_response_retries_and_succeeds(
    mock_anthropic: MagicMock, mocker: MockerFixture, tmp_path: Path
) -> None:
    # Scenario #5 — first drafting call returns no tool_use; second succeeds.
    mock_anthropic.messages.create.side_effect = [
        _tool_use_response("propose_pattern_metadata", _analysis_input()),
        _no_tool_use_response(),  # malformed — triggers internal retry
        _tool_use_response("emit_pattern_draft", _drafting_input()),
    ]
    mocker.patch("immunize.authoring.cli_author._verify_scratch", return_value=[])

    result = _run(tmp_path)
    assert result.exit_code == 0, result.output
    assert (tmp_path / "patterns" / "undefined-map-access").is_dir()
    assert mock_anthropic.messages.create.call_count == 3


def test_malformed_drafting_twice_dumps_to_rejected(
    mock_anthropic: MagicMock, tmp_path: Path
) -> None:
    # Scenario #6 — both drafting attempts malformed. Exit 1, stub rejection.
    mock_anthropic.messages.create.side_effect = [
        _tool_use_response("propose_pattern_metadata", _analysis_input()),
        _no_tool_use_response(),
        _no_tool_use_response(),
    ]

    result = _run(tmp_path)
    assert result.exit_code == 1

    rejected = tmp_path / ".immunize" / "rejected" / "undefined-map-access"
    assert rejected.is_dir()
    assert (rejected / "REJECTION.md").is_file()
    assert "drafting" in (rejected / "REJECTION.md").read_text().lower()
    # Output dir must NOT have the draft.
    assert not (tmp_path / "patterns" / "undefined-map-access").exists()


def test_valid_draft_but_verification_fails_dumps_to_rejected(
    mock_anthropic: MagicMock, mocker: MockerFixture, tmp_path: Path
) -> None:
    # Scenario #7 — schema-valid drafts, but verification returns errors on
    # both the initial draft and the retry. Dump to rejected, exit 1.
    mock_anthropic.messages.create.side_effect = [
        _tool_use_response("propose_pattern_metadata", _analysis_input()),
        _tool_use_response("emit_pattern_draft", _drafting_input()),
        _tool_use_response("emit_pattern_draft", _drafting_input()),
    ]
    mocker.patch(
        "immunize.authoring.cli_author._verify_scratch",
        return_value=["test_template.py passed with repro in place; expected failure"],
    )

    result = _run(tmp_path)
    assert result.exit_code == 1

    rejected = tmp_path / ".immunize" / "rejected" / "undefined-map-access"
    assert rejected.is_dir()
    assert (rejected / "REJECTION.md").is_file()
    assert not (tmp_path / "patterns" / "undefined-map-access").exists()
    # Drafting retry fired (3 calls total: analysis + draft + draft-retry).
    assert mock_anthropic.messages.create.call_count == 3


def test_scratch_cleaned_up_on_both_success_and_failure(
    mock_anthropic: MagicMock, mocker: MockerFixture, tmp_path: Path
) -> None:
    # Scenario #8 — the tempfile.mkdtemp scratch directory is removed by the
    # finally block in both the happy path and the verification-failure path.
    # (Drafting-failed-before-mkdtemp path is covered by scenario #6 — its
    # scratch never gets created, so there's nothing to clean up there.)
    scratch_a = tmp_path / "scratch-a"
    scratch_b = tmp_path / "scratch-b"

    # --- happy path: scratch created by _write_draft_files, removed by finally.
    mock_anthropic.messages.create.side_effect = [
        _tool_use_response("propose_pattern_metadata", _analysis_input()),
        _tool_use_response("emit_pattern_draft", _drafting_input()),
    ]
    mocker.patch("immunize.authoring.cli_author._verify_scratch", return_value=[])
    mocker.patch(
        "immunize.authoring.cli_author.tempfile.mkdtemp",
        return_value=str(scratch_a),
    )
    result = _run(tmp_path)
    assert result.exit_code == 0
    assert not scratch_a.exists(), "scratch dir leaked after happy path"

    # --- verification-failure path: same, but lint_errors force rejection.
    mock_anthropic.messages.create.reset_mock()
    analysis_two = _analysis_input() | {"proposed_slug": "undefined-map-access-two"}
    mock_anthropic.messages.create.side_effect = [
        _tool_use_response("propose_pattern_metadata", analysis_two),
        _tool_use_response("emit_pattern_draft", _drafting_input()),
        _tool_use_response("emit_pattern_draft", _drafting_input()),
    ]
    mocker.patch(
        "immunize.authoring.cli_author._verify_scratch",
        return_value=["synthetic verification failure"],
    )
    mocker.patch(
        "immunize.authoring.cli_author.tempfile.mkdtemp",
        return_value=str(scratch_b),
    )
    result = _run(tmp_path)
    assert result.exit_code == 1
    assert not scratch_b.exists(), "scratch dir leaked after failure path"
    # Rejected dir exists at the sibling .immunize/ path (not inside scratch).
    assert (tmp_path / ".immunize" / "rejected" / "undefined-map-access-two").is_dir()
