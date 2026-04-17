"""Verification harness.

User-runtime verification proves the pattern's test_template.py passes in
the user's Python environment. The bundled fixtures/ directory ships both
a buggy `repro.*` file (the test is designed to FAIL against this) and a
correct `fix.*` file (the test PASSES against this). We temporarily swap
the `fix.*` bytes into the `repro.*` path, run the test once, then
restore the original repro bytes via a `finally` block. Same swap
strategy as `scripts/pattern_lint.py`, shrunk to a single direction —
the authoring-time dual-run (fails-with-repro, passes-with-fix) lives in
pattern_lint and CI; at user-runtime we only re-verify the passes-with-fix
half to catch environment drift (missing optional deps, pytest version
skew).
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from immunize.models import Pattern, Settings, VerificationResult

# Pytest exit codes we interpret explicitly:
# 0 = all passed
# 1 = some tests failed
# 2 = test execution errored (collection/conftest error, syntax error, etc.)
# 5 = no tests collected
_PYTEST_MISSING_MARKER = "No module named pytest"


def verify(pattern: Pattern, settings: Settings) -> VerificationResult:
    """Run a pattern's test_template.py in a subprocess rooted at its directory."""
    if pattern.directory is None:
        return VerificationResult(
            passed=False,
            error_message=(
                f"Pattern {pattern.id!r} has no directory set " "(load_patterns must populate it)"
            ),
        )
    pytest_rel = pattern.verification.pytest_relative_path
    pytest_path = pattern.directory / pytest_rel
    if not pytest_path.is_file():
        return VerificationResult(
            passed=False,
            error_message=f"Pattern {pattern.id!r} missing test file at {pytest_rel}",
        )

    timeout = pattern.verification.timeout_seconds or settings.verify_timeout_seconds
    try:
        with _swap_fix_over_repro(pattern.directory):
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-x",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    "--rootdir",
                    str(pattern.directory),
                    pytest_rel,
                ],
                cwd=pattern.directory,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=_subprocess_env(),
            )
    except subprocess.TimeoutExpired:
        return VerificationResult(
            passed=False,
            error_message=f"pytest timed out after {timeout}s verifying pattern {pattern.id!r}",
        )

    if result.returncode == 0:
        return VerificationResult(passed=True)
    return VerificationResult(
        passed=False,
        error_message=_describe(f"verify {pattern.id}", result),
    )


@contextlib.contextmanager
def _swap_fix_over_repro(pattern_dir: Path) -> Iterator[None]:
    """Copy fix.* bytes over repro.* for the duration of the subprocess run,
    then restore. Same swap strategy as scripts/pattern_lint.py, shrunk to
    the pass-with-fix direction. If no repro+fix pair exists (minimal
    hand-built patterns in tests), yield unchanged.
    """
    fixtures_dir = pattern_dir / "fixtures"
    if not fixtures_dir.is_dir():
        yield
        return
    repros = sorted(p for p in fixtures_dir.iterdir() if p.is_file() and p.stem == "repro")
    fixes = sorted(p for p in fixtures_dir.iterdir() if p.is_file() and p.stem == "fix")
    if len(repros) != 1 or len(fixes) != 1:
        yield
        return
    repro = repros[0]
    fix = fixes[0]
    original = repro.read_bytes()
    try:
        repro.write_bytes(fix.read_bytes())
        yield
    finally:
        repro.write_bytes(original)


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
            error_message=f"pytest timed out after {settings.verify_timeout_seconds}s",
        )
    if result.returncode == 0:
        return VerificationResult(passed=True)
    return VerificationResult(
        passed=False,
        error_message=_describe("re-verify", result),
    )


def write_rejection_dump(directory: Path, pattern: Pattern, result: VerificationResult) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = directory / ts
    target.mkdir(exist_ok=True)
    (target / "pattern_id.txt").write_text(pattern.id)
    (target / "pattern_origin.txt").write_text(pattern.origin)
    (target / "pattern_description.txt").write_text(pattern.description)
    (target / "reason.txt").write_text(result.error_message or "unknown")
    return target


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
