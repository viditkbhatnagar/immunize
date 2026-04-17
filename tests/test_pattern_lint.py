"""Unit tests for scripts/pattern_lint.py.

Scenario 1 runs lint against the real bundled patterns (integration smoke).
Scenarios 2-6 scaffold minimal fake patterns under tmp_path and mutate one
aspect each, so the real library is never touched by a malformedness case.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# scripts/ is outside the wheel and not on sys.path by default.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import pattern_lint  # noqa: E402

_BUNDLED_PATTERNS_DIR = Path(__file__).resolve().parent.parent / "src" / "immunize" / "patterns"


_VALID_PATTERN_YAML = """\
id: fake-pattern
version: 1
schema_version: 1
author: "@test"
origin: bundled
error_class: other
languages:
  - python
description: "A fake pattern used in unit tests."

match:
  stderr_patterns:
    - "fake"
  stdout_patterns: []
  error_class_hint: null
  min_confidence: 0.70

verification:
  pytest_relative_path: test_template.py
  expected_fail_without_fix: true
  expected_pass_with_fix: true
  timeout_seconds: 30
"""

_VALID_SKILL_MD = """\
---
name: immunize-fake-pattern
description: A fake skill for testing.
---

Body.
"""

_VALID_CURSOR_MDC = """\
---
description: Fake rule for testing.
globs: **/*.py
alwaysApply: false
---

Body.
"""

# test_template reads repro.py as text and asserts it does NOT contain the
# string "BUG". repro.py has "BUG" → fails. fix.py does not → passes.
_VALID_TEST_TEMPLATE = """\
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "repro.py"


def test_no_bug_marker() -> None:
    source = FIXTURE.read_text()
    assert "BUG" not in source, f"found BUG marker in {FIXTURE.name}"
"""

_VALID_REPRO_PY = "# BUG: intentionally broken\nx = 1\n"
_VALID_FIX_PY = "# fixed\nx = 1\n"


def _scaffold_valid_pattern(root: Path, slug: str = "fake-pattern") -> Path:
    pattern_dir = root / slug
    (pattern_dir / "fixtures").mkdir(parents=True)
    (pattern_dir / "pattern.yaml").write_text(_VALID_PATTERN_YAML)
    (pattern_dir / "SKILL.md").write_text(_VALID_SKILL_MD)
    (pattern_dir / "cursor_rule.mdc").write_text(_VALID_CURSOR_MDC)
    (pattern_dir / "test_template.py").write_text(_VALID_TEST_TEMPLATE)
    (pattern_dir / "fixtures" / "repro.py").write_text(_VALID_REPRO_PY)
    (pattern_dir / "fixtures" / "fix.py").write_text(_VALID_FIX_PY)
    return pattern_dir


def test_bundled_patterns_lint_green() -> None:
    results = pattern_lint.lint_all(_BUNDLED_PATTERNS_DIR)
    assert results, "expected at least one bundled pattern"
    failures = [(r.pattern_id, r.errors) for r in results if not r.ok]
    assert not failures, f"bundled patterns failed lint: {failures}"


def test_malformed_pattern_yaml_fails(tmp_path: Path) -> None:
    pattern_dir = _scaffold_valid_pattern(tmp_path)
    # Remove required field `id` from yaml.
    broken = _VALID_PATTERN_YAML.replace("id: fake-pattern\n", "")
    (pattern_dir / "pattern.yaml").write_text(broken)

    result = pattern_lint.lint_pattern(pattern_dir)
    assert not result.ok
    assert any("pattern.yaml failed to validate" in e for e in result.errors)


def test_missing_skill_md_fails(tmp_path: Path) -> None:
    pattern_dir = _scaffold_valid_pattern(tmp_path)
    (pattern_dir / "SKILL.md").unlink()

    result = pattern_lint.lint_pattern(pattern_dir)
    assert not result.ok
    assert any("missing required file: SKILL.md" in e for e in result.errors)


def test_missing_fixtures_dir_fails(tmp_path: Path) -> None:
    pattern_dir = _scaffold_valid_pattern(tmp_path)
    (pattern_dir / "fixtures" / "repro.py").unlink()
    (pattern_dir / "fixtures" / "fix.py").unlink()
    (pattern_dir / "fixtures").rmdir()

    result = pattern_lint.lint_pattern(pattern_dir)
    assert not result.ok
    assert any("fixtures/" in e for e in result.errors)


def test_template_passes_when_it_should_fail_is_rejected(tmp_path: Path) -> None:
    pattern_dir = _scaffold_valid_pattern(tmp_path)
    # Trivial test — passes even with repro in place.
    (pattern_dir / "test_template.py").write_text("def test_trivial() -> None:\n    assert True\n")

    result = pattern_lint.lint_pattern(pattern_dir)
    assert not result.ok
    assert any("passed with repro in place" in e for e in result.errors)


def test_fix_fixture_broken_is_rejected(tmp_path: Path) -> None:
    pattern_dir = _scaffold_valid_pattern(tmp_path)
    # Test imports the fixture as a Python module. Broken fix → import crash → pytest fails.
    (pattern_dir / "test_template.py").write_text(
        "import importlib.util\n"
        "from pathlib import Path\n"
        "\n"
        "FIXTURE = Path(__file__).parent / 'fixtures' / 'repro.py'\n"
        "\n"
        "def test_importable() -> None:\n"
        "    spec = importlib.util.spec_from_file_location('repro', FIXTURE)\n"
        "    assert spec is not None and spec.loader is not None\n"
        "    mod = importlib.util.module_from_spec(spec)\n"
        "    spec.loader.exec_module(mod)\n"
        "    assert getattr(mod, 'FIXED', False) is True\n"
    )
    # Valid repro: importable but lacks FIXED (so fails).
    (pattern_dir / "fixtures" / "repro.py").write_text("FIXED = False\n")
    # Broken fix: syntax error → import crashes → test fails when swapped in.
    (pattern_dir / "fixtures" / "fix.py").write_text("def broken(:\n")

    result = pattern_lint.lint_pattern(pattern_dir)
    assert not result.ok
    assert any("failed with fix content in place" in e for e in result.errors)


@pytest.fixture(autouse=True)
def _restore_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # pytest subprocess invocations inherit cwd; keep it stable for safety.
    monkeypatch.chdir(tmp_path)
