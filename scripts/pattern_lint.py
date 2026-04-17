"""Dev/CI lint for bundled patterns under src/immunize/patterns/.

For every pattern directory:

1. Structural checks — required files present, pattern.yaml validates under
   ``Pattern.model_validate``, slug matches directory name, SKILL.md and
   cursor_rule.mdc carry required frontmatter keys, and fixtures/ holds
   exactly one ``repro.*`` and one ``fix.*``.
2. Behavioral verification — runs the pattern's test_template.py three
   times: once with the committed ``repro.*`` (must fail), once with the
   ``fix.*`` bytes swapped into the ``repro.*`` path (must pass), and
   once after restoring the original ``repro.*`` bytes (must fail again).
   The swap is atomic: an in-memory bytes backup is written back in a
   ``finally`` block so a crash can never leave a pattern dirty.

Allowed imports: stdlib + pyyaml + pydantic + rich + immunize.models.
NOT allowed: anthropic, immunize.cli, immunize.matcher, anything that
opens the network. This file lives under scripts/ and is excluded from
the published wheel.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError
from rich.console import Console

from immunize.models import Pattern

REQUIRED_TOP_LEVEL = ("pattern.yaml", "SKILL.md", "cursor_rule.mdc", "test_template.py")
SKILL_FRONTMATTER_KEYS = ("name", "description")
CURSOR_FRONTMATTER_KEYS = ("description", "globs", "alwaysApply")


@dataclass(frozen=True)
class PatternLintResult:
    pattern_id: str
    ok: bool
    errors: list[str] = field(default_factory=list)


def lint_pattern(pattern_dir: Path) -> PatternLintResult:
    pattern_id = pattern_dir.name
    pattern, structural_errors = _check_structure(pattern_dir)
    if pattern is None:
        return PatternLintResult(pattern_id=pattern_id, ok=False, errors=structural_errors)

    behavioral_errors = _verify_fixture_swap(pattern_dir, pattern)
    errors = [*structural_errors, *behavioral_errors]
    return PatternLintResult(
        pattern_id=pattern.id,
        ok=not errors,
        errors=errors,
    )


def lint_all(patterns_dir: Path) -> list[PatternLintResult]:
    if not patterns_dir.is_dir():
        raise FileNotFoundError(f"patterns directory not found: {patterns_dir}")
    results: list[PatternLintResult] = []
    for child in sorted(patterns_dir.iterdir()):
        if not child.is_dir() or child.name.startswith((".", "__")):
            continue
        results.append(lint_pattern(child))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lint bundled immunize patterns.")
    parser.add_argument(
        "--patterns-dir",
        type=Path,
        default=Path("src/immunize/patterns"),
        help="Directory containing pattern subfolders (default: src/immunize/patterns)",
    )
    args = parser.parse_args(argv)

    console = Console(soft_wrap=True)
    try:
        results = lint_all(args.patterns_dir)
    except FileNotFoundError as e:
        console.print(f"[red]error:[/red] {e}")
        return 2

    if not results:
        console.print("[yellow]no patterns found[/yellow]")
        return 2

    passed = 0
    for r in results:
        if r.ok:
            passed += 1
            console.print(f"[green]OK[/green] {r.pattern_id}")
        else:
            console.print(f"[red]FAIL[/red] {r.pattern_id}: {r.errors[0]}")
            for extra in r.errors[1:]:
                console.print(f"    {extra}")

    total = len(results)
    if passed == total:
        console.print(f"\n[green]{passed}/{total} patterns passed[/green]")
        return 0
    console.print(f"\n[red]{passed}/{total} patterns passed; {total - passed} failed[/red]")
    return 1


def _check_structure(pattern_dir: Path) -> tuple[Pattern | None, list[str]]:
    errors: list[str] = []

    for name in REQUIRED_TOP_LEVEL:
        if not (pattern_dir / name).exists():
            errors.append(f"missing required file: {name}")
    fixtures_dir = pattern_dir / "fixtures"
    if not fixtures_dir.is_dir():
        errors.append("missing required directory: fixtures/")

    yaml_path = pattern_dir / "pattern.yaml"
    pattern: Pattern | None = None
    if yaml_path.is_file():
        try:
            data = yaml.safe_load(yaml_path.read_text())
            pattern = Pattern.model_validate(data)
        except (yaml.YAMLError, ValidationError, OSError) as e:
            errors.append(f"pattern.yaml failed to validate: {e}")

    if pattern is not None and pattern.id != pattern_dir.name:
        errors.append(
            f"pattern.id '{pattern.id}' does not match directory name '{pattern_dir.name}'"
        )

    skill_path = pattern_dir / "SKILL.md"
    if skill_path.is_file():
        errors.extend(_check_frontmatter(skill_path, SKILL_FRONTMATTER_KEYS, "SKILL.md"))

    cursor_path = pattern_dir / "cursor_rule.mdc"
    if cursor_path.is_file():
        errors.extend(_check_frontmatter(cursor_path, CURSOR_FRONTMATTER_KEYS, "cursor_rule.mdc"))

    if fixtures_dir.is_dir():
        repros = sorted(p for p in fixtures_dir.iterdir() if p.is_file() and p.stem == "repro")
        fixes = sorted(p for p in fixtures_dir.iterdir() if p.is_file() and p.stem == "fix")
        if len(repros) != 1:
            errors.append(f"fixtures/ must contain exactly one repro.* file, found {len(repros)}")
        if len(fixes) != 1:
            errors.append(f"fixtures/ must contain exactly one fix.* file, found {len(fixes)}")

    return pattern, errors


def _check_frontmatter(md_path: Path, required_keys: tuple[str, ...], label: str) -> list[str]:
    fm = _read_frontmatter(md_path)
    if fm is None:
        return [f"{label} missing or malformed YAML frontmatter"]
    missing = [k for k in required_keys if k not in fm]
    return [f"{label} missing frontmatter key '{k}'" for k in missing]


def _read_frontmatter(md_path: Path) -> dict[str, str] | None:
    # Line-based key:value scanner, not a strict YAML parse. Cursor and
    # Claude Code extract frontmatter via the same regex-y approach;
    # strict PyYAML trips on unquoted glob patterns (``**/*.jsx`` reads
    # as an alias) and on colons embedded in prose descriptions. Matching
    # downstream parser behavior is more useful here than YAML purity.
    try:
        text = md_path.read_text()
    except OSError:
        return None
    lines = text.splitlines()
    idx = 0
    while idx < len(lines) and lines[idx].strip() == "":
        idx += 1
    if idx >= len(lines) or lines[idx].strip() != "---":
        return None
    start = idx + 1
    end = start
    while end < len(lines) and lines[end].strip() != "---":
        end += 1
    if end >= len(lines):
        return None
    out: dict[str, str] = {}
    for line in lines[start:end]:
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        out[key.strip()] = value.strip()
    return out


def _verify_fixture_swap(pattern_dir: Path, pattern: Pattern) -> list[str]:
    fixtures_dir = pattern_dir / "fixtures"
    if not fixtures_dir.is_dir():
        # Already reported by _check_structure; skip behavioral phase.
        return []
    repros = [p for p in fixtures_dir.iterdir() if p.is_file() and p.stem == "repro"]
    fixes = [p for p in fixtures_dir.iterdir() if p.is_file() and p.stem == "fix"]
    if len(repros) != 1 or len(fixes) != 1:
        # Already reported by _check_structure; skip behavioral phase.
        return []

    repro = repros[0]
    fix = fixes[0]
    test = pattern_dir / pattern.verification.pytest_relative_path
    if not test.is_file():
        return [f"test file not found: {test.relative_to(pattern_dir)}"]
    timeout = pattern.verification.timeout_seconds

    original = repro.read_bytes()
    errors: list[str] = []
    try:
        rc_a = _run_pytest(test, timeout)
        if rc_a == 0:
            errors.append("test_template.py passed with repro in place; expected failure")

        repro.write_bytes(fix.read_bytes())
        rc_b = _run_pytest(test, timeout)
        if rc_b != 0:
            errors.append(
                f"test_template.py failed with fix content in place (rc={rc_b}); expected pass"
            )

        repro.write_bytes(original)
        rc_c = _run_pytest(test, timeout)
        if rc_c == 0:
            errors.append("test_template.py passed after restoring repro; non-deterministic")
    finally:
        repro.write_bytes(original)
    return errors


def _run_pytest(test_path: Path, timeout: int) -> int:
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                str(test_path),
                "-x",
                "-q",
                "--no-header",
                "-p",
                "no:cacheprovider",
            ],
            timeout=timeout,
            capture_output=True,
        )
        return completed.returncode
    except subprocess.TimeoutExpired:
        return 124


if __name__ == "__main__":
    sys.exit(main())
