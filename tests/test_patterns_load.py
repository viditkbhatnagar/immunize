"""Sanity tests for the bundled pattern library.

Proves matcher.load_patterns() finds every pattern shipped under
src/immunize/patterns/ and that each pattern is structurally sound on
disk: pattern.yaml parses, origin is bundled, directory is populated,
the verification pytest target exists, and the fixtures directory has
exactly one repro.* and exactly one fix.* file. The strict
exactly-one-of check prevents repro_v1.py / repro_v2.py creep.
"""

from __future__ import annotations

from pathlib import Path

import immunize
from immunize.matcher import load_patterns

BUNDLED_DIR = Path(immunize.__file__).parent / "patterns"

EXPECTED_IDS = {
    "react-hook-missing-dep",
    "fetch-missing-credentials",
    "python-none-attribute-access",
    "import-not-found-python",
    "missing-env-var",
    "rate-limit-no-backoff",
    "async-fn-called-without-await",
}


def test_bundled_patterns_load_exact_set() -> None:
    patterns = load_patterns(BUNDLED_DIR)
    ids = {p.id for p in patterns}
    assert (
        ids == EXPECTED_IDS
    ), f"bundled pattern id set mismatch. expected {EXPECTED_IDS}, got {ids}"


def test_each_bundled_pattern_has_origin_bundled_and_directory() -> None:
    for pattern in load_patterns(BUNDLED_DIR):
        assert (
            pattern.origin == "bundled"
        ), f"{pattern.id}: origin must be 'bundled', got {pattern.origin!r}"
        assert pattern.directory is not None, f"{pattern.id}: directory is None"
        assert (
            pattern.directory.is_dir()
        ), f"{pattern.id}: directory {pattern.directory} does not exist"


def test_each_bundled_pattern_resolves_its_verification_target() -> None:
    for pattern in load_patterns(BUNDLED_DIR):
        assert pattern.directory is not None
        target = pattern.directory / pattern.verification.pytest_relative_path
        assert target.is_file(), f"{pattern.id}: verification target {target} is not a file"
        fixtures = pattern.directory / "fixtures"
        assert fixtures.is_dir(), f"{pattern.id}: fixtures/ dir missing"
        repros = list(fixtures.glob("repro.*"))
        fixes = list(fixtures.glob("fix.*"))
        assert (
            len(repros) == 1
        ), f"{pattern.id}: expected exactly one repro.* fixture, found {repros}"
        assert len(fixes) == 1, f"{pattern.id}: expected exactly one fix.* fixture, found {fixes}"
