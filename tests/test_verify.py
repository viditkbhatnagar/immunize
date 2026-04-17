from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from immunize import verify
from immunize.models import GeneratedArtifacts, Settings, VerificationResult


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        project_dir=tmp_path,
        state_db_path=tmp_path / ".immunize" / "state.db",
    )


def _artifacts(
    *,
    error_repro: str,
    pytest_code: str,
    fix: str,
    cursor_rule: str = "---\n---\n",
    skill_md: str = "---\nname: x\n---\n",
) -> GeneratedArtifacts:
    return GeneratedArtifacts(
        skill_md=skill_md,
        cursor_rule=cursor_rule,
        pytest_code=pytest_code,
        expected_fix_snippet=fix,
        error_repro_snippet=error_repro,
    )


# ---- Scenario 1: happy path -----------------------------------------------
def test_happy_path_buggy_fails_fixed_passes(settings: Settings) -> None:
    artifacts = _artifacts(
        error_repro="def add(a, b):\n    return a - b\n",
        pytest_code=(
            "from app_under_test import add\n\n"
            "def test_add() -> None:\n"
            "    assert add(2, 3) == 5\n"
        ),
        fix="def add(a, b):\n    return a + b\n",
    )
    result = verify.verify(artifacts, settings)
    assert result.passed is True
    assert result.fails_without_fix is True
    assert result.passes_with_fix is True
    assert result.error_message is None


# ---- Scenario 2: test never fails even without fix -------------------------
def test_test_never_fails_sets_fails_without_fix_false(settings: Settings) -> None:
    artifacts = _artifacts(
        error_repro="def add(a, b):\n    return a + b\n",
        pytest_code=(
            "from app_under_test import add\n\n"
            "def test_add() -> None:\n"
            "    assert add(2, 3) == 5\n"
        ),
        fix="def add(a, b):\n    return a + b  # already fine\n",
    )
    result = verify.verify(artifacts, settings)
    assert result.passed is False
    assert result.fails_without_fix is False
    assert "pytest passed when it should have failed" in (result.error_message or "")


# ---- Scenario 3: test still fails with fix applied -------------------------
def test_test_still_fails_with_fix(settings: Settings) -> None:
    artifacts = _artifacts(
        error_repro="def add(a, b):\n    return a - b\n",
        pytest_code=(
            "from app_under_test import add\n\n"
            "def test_add() -> None:\n"
            "    assert add(2, 3) == 5\n"
        ),
        fix="def add(a, b):\n    return a * b\n",  # still wrong
    )
    result = verify.verify(artifacts, settings)
    assert result.passed is False
    assert result.fails_without_fix is True
    assert result.passes_with_fix is False


# ---- Scenario 4: subprocess timeout ----------------------------------------
def test_subprocess_timeout_surfaces_cleanly(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=["pytest"], timeout=30)

    monkeypatch.setattr(subprocess, "run", _fake_run)
    artifacts = _artifacts(
        error_repro="x = 1\n",
        pytest_code="def test_x() -> None:\n    assert True\n",
        fix="x = 2\n",
    )
    result = verify.verify(artifacts, settings)
    assert result.passed is False
    assert result.fails_without_fix is False
    assert "timed out" in (result.error_message or "")


# ---- Scenario 5: pytest exit code 2 (collection error) ---------------------
def test_pytest_exit_2_treated_as_verification_failure(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["pytest"], returncode=2, stdout="", stderr="collection error: cannot import"
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    artifacts = _artifacts(
        error_repro="x = 1\n",
        pytest_code="def test_x() -> None:\n    assert True\n",
        fix="x = 2\n",
    )
    result = verify.verify(artifacts, settings)
    assert result.passed is False
    assert "collection error" in (result.error_message or "")


# ---- Scenario 6: pytest exit code 5 (no tests collected) -------------------
def test_pytest_exit_5_no_tests_collected(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["pytest"], returncode=5, stdout="no tests ran", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    artifacts = _artifacts(
        error_repro="x = 1\n",
        pytest_code="# no tests here at all\n",
        fix="x = 2\n",
    )
    result = verify.verify(artifacts, settings)
    assert result.passed is False
    assert "collected no tests" in (result.error_message or "")


# ---- Scenario 7: generated test has syntax error --------------------------
def test_syntactically_invalid_pytest_code_surfaces_cleanly(settings: Settings) -> None:
    artifacts = _artifacts(
        error_repro="x = 1\n",
        pytest_code="def test_x(:\n    this is not python\n",  # syntax error
        fix="x = 2\n",
    )
    result = verify.verify(artifacts, settings)
    assert result.passed is False
    assert result.fails_without_fix is False
    # pytest returns exit 2 on collection errors (SyntaxError is one).
    assert "collection error" in (result.error_message or "") or "exit 2" in (
        result.error_message or ""
    )


# ---- "No module named pytest" message --------------------------------------
def test_pytest_missing_gives_clean_hint(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["python", "-m", "pytest"],
            returncode=1,
            stdout="",
            stderr="/usr/bin/python: No module named pytest\n",
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    artifacts = _artifacts(
        error_repro="x = 1\n", pytest_code="def test_x(): pass\n", fix="x = 2\n"
    )
    result = verify.verify(artifacts, settings)
    assert result.passed is False
    assert "pytest is not installed" in (result.error_message or "")


# ---- Rejection dump --------------------------------------------------------
def test_write_rejection_dump_creates_files(tmp_path: Path) -> None:
    artifacts = _artifacts(
        error_repro="repro code\n", pytest_code="test code\n", fix="fix code\n"
    )
    result = VerificationResult(
        passed=False,
        fails_without_fix=False,
        passes_with_fix=False,
        error_message="never failed",
    )
    target = verify.write_rejection_dump(tmp_path / ".immunize" / "rejected", artifacts, result)
    assert target.is_dir()
    assert (target / "app_under_test.py").read_text() == "repro code\n"
    assert (target / "test_immunity.py").read_text() == "test code\n"
    assert (target / "expected_fix.py").read_text() == "fix code\n"
    assert (target / "reason.txt").read_text() == "never failed"


# ---- verify_artifact_on_disk -----------------------------------------------
def test_verify_artifact_on_disk_happy_path(
    tmp_path: Path, settings: Settings
) -> None:
    pytest_file = tmp_path / "test_x.py"
    pytest_file.write_text("def test_x() -> None:\n    assert 1 + 1 == 2\n")
    result = verify.verify_artifact_on_disk(pytest_file, settings)
    assert result.passed is True


def test_verify_artifact_on_disk_failing(
    tmp_path: Path, settings: Settings
) -> None:
    pytest_file = tmp_path / "test_x.py"
    pytest_file.write_text("def test_x() -> None:\n    assert 1 + 1 == 3\n")
    result = verify.verify_artifact_on_disk(pytest_file, settings)
    assert result.passed is False
    assert "exit 1" in (result.error_message or "")
