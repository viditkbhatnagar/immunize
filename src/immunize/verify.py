"""Verification harness — the product's moat.

v0.1.x limitation: this harness generates and runs Python pytest files for
*all* error classes, including TypeScript/JavaScript/Go/etc. errors. Python
errors get the strongest verification (real pytest subprocess proves
fail-without-fix and pass-with-fix). Other languages get pattern-based
sanity checks via Python simulations of the error shape. Native-language
test generation (Jest, Go test, cargo test) is a v0.3 goal. See README.md
section "Known limitations".
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from immunize.models import GeneratedArtifacts, Settings, VerificationResult

# Pytest exit codes we interpret explicitly:
# 0 = all passed
# 1 = some tests failed (this is what we *want* from the fails-without-fix check)
# 2 = test execution errored (collection/conftest error, syntax error, etc.)
# 5 = no tests collected
_PYTEST_MISSING_MARKER = "No module named pytest"


def verify(artifacts: GeneratedArtifacts, settings: Settings) -> VerificationResult:
    with tempfile.TemporaryDirectory() as scratch:
        scratch_path = Path(scratch)
        app_path = scratch_path / "app_under_test.py"
        test_path = scratch_path / "test_immunity.py"

        app_path.write_text(artifacts.error_repro_snippet)
        test_path.write_text(artifacts.pytest_code)

        try:
            fail_run = _run_pytest(scratch_path, settings)
        except subprocess.TimeoutExpired:
            return VerificationResult(
                passed=False,
                fails_without_fix=False,
                passes_with_fix=False,
                error_message=(
                    f"pytest timed out after {settings.verify_timeout_seconds}s "
                    "during fails-without-fix check"
                ),
            )

        if fail_run.returncode != 1:
            return VerificationResult(
                passed=False,
                fails_without_fix=False,
                passes_with_fix=False,
                error_message=_describe("fails-without-fix", fail_run),
            )

        app_path.write_text(artifacts.expected_fix_snippet)
        try:
            pass_run = _run_pytest(scratch_path, settings)
        except subprocess.TimeoutExpired:
            return VerificationResult(
                passed=False,
                fails_without_fix=True,
                passes_with_fix=False,
                error_message=(
                    f"pytest timed out after {settings.verify_timeout_seconds}s "
                    "during passes-with-fix check"
                ),
            )

        if pass_run.returncode != 0:
            return VerificationResult(
                passed=False,
                fails_without_fix=True,
                passes_with_fix=False,
                error_message=_describe("passes-with-fix", pass_run),
            )

    return VerificationResult(passed=True, fails_without_fix=True, passes_with_fix=True)


def verify_artifact_on_disk(pytest_path: Path, settings: Settings) -> VerificationResult:
    """Re-run an already-injected test file in place. Used by `immunize verify`."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-x", "-q", str(pytest_path)],
            capture_output=True,
            text=True,
            timeout=settings.verify_timeout_seconds,
            env=_subprocess_env(),
        )
    except subprocess.TimeoutExpired:
        return VerificationResult(
            passed=False,
            fails_without_fix=False,
            passes_with_fix=False,
            error_message=f"pytest timed out after {settings.verify_timeout_seconds}s",
        )
    if result.returncode == 0:
        return VerificationResult(passed=True, fails_without_fix=False, passes_with_fix=True)
    return VerificationResult(
        passed=False,
        fails_without_fix=False,
        passes_with_fix=False,
        error_message=_describe("re-verify", result),
    )


def write_rejection_dump(
    directory: Path, artifacts: GeneratedArtifacts, result: VerificationResult
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = directory / ts
    target.mkdir(exist_ok=True)
    (target / "app_under_test.py").write_text(artifacts.error_repro_snippet)
    (target / "test_immunity.py").write_text(artifacts.pytest_code)
    (target / "expected_fix.py").write_text(artifacts.expected_fix_snippet)
    (target / "reason.txt").write_text(result.error_message or "unknown")
    return target


def _run_pytest(
    scratch: Path, settings: Settings
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-x",
            "-q",
            "-p",
            "no:cacheprovider",
            "--rootdir",
            str(scratch),
            "test_immunity.py",
        ],
        cwd=scratch,
        capture_output=True,
        text=True,
        timeout=settings.verify_timeout_seconds,
        env=_subprocess_env(),
    )


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTEST_ADDOPTS"] = ""
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _describe(stage: str, proc: subprocess.CompletedProcess[str]) -> str:
    combined = (proc.stderr or "") + (proc.stdout or "")
    if _PYTEST_MISSING_MARKER in combined:
        return "pytest is not installed in this environment. Run: pip install pytest"
    if proc.returncode == 0:
        return f"{stage}: pytest passed when it should have failed"
    if proc.returncode == 2:
        return f"{stage}: pytest collection error (exit 2): {combined[-500:]}"
    if proc.returncode == 5:
        return f"{stage}: pytest collected no tests (exit 5)"
    return f"{stage}: pytest exit {proc.returncode}: {combined[-500:]}"
