"""Tests for slug-or-id identifier resolution on `verify` and `remove`.

v0.2.0 accepts either ``immunize verify 3`` (integer id) or
``immunize verify fetch-missing-credentials`` (pattern slug). Previously the
slug form failed with "not a valid integer" — a UX paper-cut that external
review flagged. The underlying helper ``_resolve_identifier`` is pure: digit
strings hit the id-lookup path, everything else is treated as a slug.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from immunize.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for k in [k for k in os.environ if k.startswith("IMMUNIZE_")]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.chdir(tmp_path)


def _cors_payload(cwd: Path) -> str:
    # Same payload used in test_cli.py — triggers fetch-missing-credentials
    # injection against the current matcher.
    return json.dumps(
        {
            "source": "manual",
            "stderr": (
                "Access to fetch at 'https://api.example.com/me' from origin "
                "'http://localhost:3000' has been blocked by CORS policy: Response "
                "to preflight request doesn't pass access control check: The value "
                "of the 'Access-Control-Allow-Credentials' header in the response "
                "is '' which must be 'true' when the request's credentials mode is "
                "'include'."
            ),
            "exit_code": 1,
            "cwd": str(cwd),
            "timestamp": "2026-04-17T00:00:00Z",
            "project_fingerprint": "slug-test",
        }
    )


def _seed_one_immunity(tmp_path: Path) -> None:
    result = runner.invoke(app, ["capture"], input=_cors_payload(tmp_path))
    assert result.exit_code == 0
    # Sanity: artifacts landed, row inserted.
    assert (tmp_path / "tests" / "immunized" / "fetch-missing-credentials").is_dir()


# --- verify with slug -------------------------------------------------------


def test_verify_by_slug_resolves_to_the_injected_record(tmp_path: Path) -> None:
    _seed_one_immunity(tmp_path)
    result = runner.invoke(app, ["verify", "fetch-missing-credentials"])
    assert result.exit_code == 0
    assert "fetch-missing-credentials" in result.output
    assert "PASS" in result.output


def test_verify_by_id_still_works(tmp_path: Path) -> None:
    _seed_one_immunity(tmp_path)
    result = runner.invoke(app, ["verify", "1"])
    assert result.exit_code == 0
    assert "PASS" in result.output


def test_verify_unknown_slug_errors_out_cleanly(tmp_path: Path) -> None:
    _seed_one_immunity(tmp_path)
    result = runner.invoke(app, ["verify", "no-such-pattern"])
    assert result.exit_code == 1
    # Error message should name the unresolved identifier.
    assert "no-such-pattern" in (result.stderr or result.output)


def test_verify_unknown_id_errors_out_cleanly(tmp_path: Path) -> None:
    _seed_one_immunity(tmp_path)
    result = runner.invoke(app, ["verify", "999"])
    assert result.exit_code == 1
    assert "999" in (result.stderr or result.output)


def test_verify_no_identifier_verifies_all(tmp_path: Path) -> None:
    _seed_one_immunity(tmp_path)
    result = runner.invoke(app, ["verify"])
    assert result.exit_code == 0
    assert "fetch-missing-credentials" in result.output


# --- remove with slug -------------------------------------------------------


def test_remove_by_slug_single_match(tmp_path: Path) -> None:
    _seed_one_immunity(tmp_path)
    result = runner.invoke(app, ["remove", "fetch-missing-credentials", "--yes"])
    assert result.exit_code == 0
    assert "Removed immunity 'fetch-missing-credentials'" in result.output
    # Artifacts gone.
    assert not (tmp_path / "tests" / "immunized" / "fetch-missing-credentials").exists()


def test_remove_by_id_still_works(tmp_path: Path) -> None:
    _seed_one_immunity(tmp_path)
    result = runner.invoke(app, ["remove", "1", "--yes"])
    assert result.exit_code == 0
    assert "Removed" in result.output


def test_remove_unknown_slug_errors_out(tmp_path: Path) -> None:
    _seed_one_immunity(tmp_path)
    result = runner.invoke(app, ["remove", "no-such-slug", "--yes"])
    assert result.exit_code == 1
    assert "no-such-slug" in (result.stderr or result.output)


def test_remove_multi_match_slug_requires_disambiguation(tmp_path: Path) -> None:
    # Seed two records for the same slug by running capture twice against the
    # same project. The second capture creates a new artifacts row (storage
    # appends; doesn't dedupe on slug). Ambiguity → exit 1 with id listing.
    from immunize import storage

    _seed_one_immunity(tmp_path)
    # Manually insert a duplicate artifact row with the same slug but a
    # different id — simulates the --force re-injection scenario without
    # running the whole matcher pipeline a second time.
    conn = storage.connect(tmp_path / ".immunize" / "state.db")
    storage.insert_match(
        conn,
        slug="fetch-missing-credentials",
        pattern_id="fetch-missing-credentials",
        pattern_origin="bundled",
        paths={
            "skill_path": str(tmp_path / "dup" / "SKILL.md"),
            "cursor_rule_path": str(tmp_path / "dup" / "rule.mdc"),
            "semgrep_path": None,
            "pytest_path": str(tmp_path / "dup" / "test_template.py"),
        },
        verified=True,
    )

    result = runner.invoke(app, ["remove", "fetch-missing-credentials", "--yes"])
    assert result.exit_code == 1
    # Error output should enumerate the matching ids so the user can pick one.
    output = result.stderr or result.output
    assert "2 immunities match" in output
    assert "id=1" in output
    assert "id=2" in output


def test_verify_multi_match_slug_verifies_all(tmp_path: Path) -> None:
    # verify is read-only so a slug matching multiple records verifies each —
    # no disambiguation needed.
    from immunize import storage

    _seed_one_immunity(tmp_path)
    conn = storage.connect(tmp_path / ".immunize" / "state.db")
    # Second insertion points at the SAME pytest file on disk so verify can
    # re-run the real injected test for both rows.
    storage.insert_match(
        conn,
        slug="fetch-missing-credentials",
        pattern_id="fetch-missing-credentials",
        pattern_origin="bundled",
        paths={
            "skill_path": str(
                tmp_path / ".claude" / "skills" / "immunize-fetch-missing-credentials" / "SKILL.md"
            ),
            "cursor_rule_path": str(
                tmp_path / ".cursor" / "rules" / "fetch-missing-credentials.mdc"
            ),
            "semgrep_path": None,
            "pytest_path": str(
                tmp_path / "tests" / "immunized" / "fetch-missing-credentials" / "test_template.py"
            ),
        },
        verified=True,
    )

    result = runner.invoke(app, ["verify", "fetch-missing-credentials"])
    assert result.exit_code == 0
    # Both rows should appear in the verification table.
    assert result.output.count("fetch-missing-credentials") >= 2
