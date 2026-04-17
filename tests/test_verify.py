from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from immunize import verify
from immunize.models import Pattern, Settings, VerificationResult


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        project_dir=tmp_path,
        state_db_path=tmp_path / ".immunize" / "state.db",
    )


def _write_pattern(
    root: Path,
    slug: str,
    *,
    test_body: str,
    fixtures: dict[str, str] | None = None,
    pytest_relative_path: str = "test_template.py",
    timeout_seconds: int = 30,
) -> Pattern:
    pattern_dir = root / slug
    pattern_dir.mkdir(parents=True, exist_ok=True)
    (pattern_dir / pytest_relative_path).write_text(test_body)
    if fixtures:
        (pattern_dir / "fixtures").mkdir(exist_ok=True)
        for name, content in fixtures.items():
            (pattern_dir / "fixtures" / name).write_text(content)
    return Pattern.model_validate(
        {
            "id": slug,
            "version": 1,
            "author": "@test",
            "origin": "bundled",
            "error_class": "other",
            "languages": ["python"],
            "description": f"pattern {slug}",
            "match": {"stderr_patterns": ["boom"], "min_confidence": 0.70},
            "verification": {
                "pytest_relative_path": pytest_relative_path,
                "timeout_seconds": timeout_seconds,
            },
            "directory": pattern_dir,
        }
    )


# ---- Scenario 1: happy path ------------------------------------------------
def test_verify_passes_when_pattern_test_passes(settings: Settings, tmp_path: Path) -> None:
    pattern = _write_pattern(
        tmp_path / "patterns",
        "ok",
        test_body="def test_ok() -> None:\n    assert 1 + 1 == 2\n",
    )
    result = verify.verify(pattern, settings)
    assert result.passed is True
    assert result.error_message is None


def test_verify_reads_fixtures_from_pattern_directory(settings: Settings, tmp_path: Path) -> None:
    pattern = _write_pattern(
        tmp_path / "patterns",
        "uses-fixture",
        test_body=(
            "from pathlib import Path\n\n"
            "def test_fixture_visible() -> None:\n"
            "    data = (Path(__file__).parent / 'fixtures' / 'data.txt')\n"
            "    assert data.read_text().strip() == 'ok'\n"
        ),
        fixtures={"data.txt": "ok\n"},
    )
    result = verify.verify(pattern, settings)
    assert result.passed is True


# ---- Scenario 2: pattern test fails ---------------------------------------
def test_verify_fails_when_test_fails(settings: Settings, tmp_path: Path) -> None:
    pattern = _write_pattern(
        tmp_path / "patterns",
        "broken",
        test_body="def test_fail() -> None:\n    assert False, 'nope'\n",
    )
    result = verify.verify(pattern, settings)
    assert result.passed is False
    assert "exit 1" in (result.error_message or "")


# ---- Scenario 3: missing test file ----------------------------------------
def test_verify_missing_test_file_returns_failure(settings: Settings, tmp_path: Path) -> None:
    pattern_dir = tmp_path / "patterns" / "missing"
    pattern_dir.mkdir(parents=True)
    pattern = Pattern.model_validate(
        {
            "id": "missing",
            "version": 1,
            "author": "@test",
            "origin": "bundled",
            "error_class": "other",
            "languages": ["python"],
            "description": "test",
            "match": {"stderr_patterns": ["boom"]},
            "verification": {"pytest_relative_path": "test_template.py"},
            "directory": pattern_dir,
        }
    )
    result = verify.verify(pattern, settings)
    assert result.passed is False
    assert "missing test file" in (result.error_message or "")


# ---- Scenario 4: pattern directory not set --------------------------------
def test_verify_requires_directory_on_pattern(settings: Settings) -> None:
    pattern = Pattern.model_validate(
        {
            "id": "no-dir",
            "version": 1,
            "author": "@test",
            "origin": "bundled",
            "error_class": "other",
            "languages": ["python"],
            "description": "test",
            "match": {"stderr_patterns": ["boom"]},
            "verification": {"pytest_relative_path": "test_template.py"},
        }
    )
    result = verify.verify(pattern, settings)
    assert result.passed is False
    assert "no directory" in (result.error_message or "")


# ---- Scenario 5: subprocess timeout ---------------------------------------
def test_subprocess_timeout_surfaces_cleanly(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=["pytest"], timeout=30)

    monkeypatch.setattr(subprocess, "run", _fake_run)
    pattern = _write_pattern(
        tmp_path / "patterns",
        "timeout",
        test_body="def test_x() -> None: pass\n",
    )
    result = verify.verify(pattern, settings)
    assert result.passed is False
    assert "timed out" in (result.error_message or "")


# ---- Scenario 6: pytest exit code 2 (collection error) --------------------
def test_pytest_exit_2_treated_as_verification_failure(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["pytest"], returncode=2, stdout="", stderr="collection error: cannot import"
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    pattern = _write_pattern(
        tmp_path / "patterns",
        "collect-err",
        test_body="def test_x() -> None: pass\n",
    )
    result = verify.verify(pattern, settings)
    assert result.passed is False
    assert "collection error" in (result.error_message or "")


# ---- Scenario 7: pytest exit code 5 (no tests collected) ------------------
def test_pytest_exit_5_no_tests_collected(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["pytest"], returncode=5, stdout="no tests ran", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    pattern = _write_pattern(
        tmp_path / "patterns",
        "no-tests",
        test_body="# no tests\n",
    )
    result = verify.verify(pattern, settings)
    assert result.passed is False
    assert "collected no tests" in (result.error_message or "")


# ---- Scenario 8: syntactically invalid pytest ------------------------------
def test_syntactically_invalid_pytest_code_surfaces_cleanly(
    settings: Settings, tmp_path: Path
) -> None:
    pattern = _write_pattern(
        tmp_path / "patterns",
        "syntax-err",
        test_body="def test_x(:\n    this is not python\n",
    )
    result = verify.verify(pattern, settings)
    assert result.passed is False
    assert "collection error" in (result.error_message or "") or "exit 2" in (
        result.error_message or ""
    )


# ---- "No module named pytest" message --------------------------------------
def test_pytest_missing_gives_clean_hint(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["python", "-m", "pytest"],
            returncode=1,
            stdout="",
            stderr="/usr/bin/python: No module named pytest\n",
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    pattern = _write_pattern(
        tmp_path / "patterns",
        "no-pytest",
        test_body="def test_x(): pass\n",
    )
    result = verify.verify(pattern, settings)
    assert result.passed is False
    assert "pytest is not installed" in (result.error_message or "")


# ---- Pattern-level timeout override applies -------------------------------
def test_pattern_timeout_overrides_settings(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict = {}

    def _fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["timeout"] = kwargs.get("timeout")
        return subprocess.CompletedProcess(args=["pytest"], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    pattern = _write_pattern(
        tmp_path / "patterns",
        "tight-budget",
        test_body="def test_x(): pass\n",
        timeout_seconds=7,
    )
    verify.verify(pattern, settings)
    assert captured["timeout"] == 7


# ---- Rejection dump --------------------------------------------------------
def test_write_rejection_dump_creates_files(tmp_path: Path) -> None:
    pattern = _write_pattern(
        tmp_path / "patterns",
        "rejected-pat",
        test_body="def test_x(): pass\n",
    )
    result = VerificationResult(passed=False, error_message="pytest exit 1")
    target = verify.write_rejection_dump(tmp_path / ".immunize" / "rejected", pattern, result)
    assert target.is_dir()
    assert (target / "pattern_id.txt").read_text() == "rejected-pat"
    assert (target / "pattern_origin.txt").read_text() == "bundled"
    assert (target / "pattern_description.txt").read_text() == "pattern rejected-pat"
    assert (target / "reason.txt").read_text() == "pytest exit 1"


# ---- verify_artifact_on_disk -----------------------------------------------
def test_verify_artifact_on_disk_happy_path(tmp_path: Path, settings: Settings) -> None:
    pytest_file = tmp_path / "test_x.py"
    pytest_file.write_text("def test_x() -> None:\n    assert 1 + 1 == 2\n")
    result = verify.verify_artifact_on_disk(pytest_file, settings)
    assert result.passed is True


def test_verify_artifact_on_disk_failing(tmp_path: Path, settings: Settings) -> None:
    pytest_file = tmp_path / "test_x.py"
    pytest_file.write_text("def test_x() -> None:\n    assert 1 + 1 == 3\n")
    result = verify.verify_artifact_on_disk(pytest_file, settings)
    assert result.passed is False
    assert "exit 1" in (result.error_message or "")
