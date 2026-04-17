from __future__ import annotations

import subprocess
import sys
import zipfile
from importlib.resources import files
from pathlib import Path

import pytest
import yaml

SKILL_PATH = files("immunize") / "skill_assets" / "immunize-manager" / "SKILL.md"


def _skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def _frontmatter_and_body(text: str) -> tuple[dict, str]:
    assert text.startswith("---\n"), "SKILL.md must start with YAML frontmatter"
    _, rest = text.split("---\n", 1)
    fm_text, body = rest.split("\n---\n", 1)
    return yaml.safe_load(fm_text), body


def test_skill_file_exists() -> None:
    assert SKILL_PATH.is_file(), f"bundled SKILL.md missing at {SKILL_PATH}"
    text = _skill_text()
    assert text.strip(), "bundled SKILL.md is empty"


def test_frontmatter_valid() -> None:
    fm, _ = _frontmatter_and_body(_skill_text())
    assert fm["name"] == "immunize-manager"
    desc = fm["description"]
    assert isinstance(desc, str) and desc.strip(), "description must be a non-empty string"


def test_required_body_sections() -> None:
    _, body = _frontmatter_and_body(_skill_text())
    required = [
        "## When to invoke",
        "## When NOT to invoke",
        "## How to invoke",
        "## Outcome handling",
        '### `outcome: "matched_and_verified"`',
        '### `outcome: "matched_verify_failed"`',
        '### `outcome: "unmatched"`',
    ]
    missing = [h for h in required if h not in body]
    assert not missing, f"SKILL.md body missing required sections: {missing}"


def test_wheel_ships_skill(tmp_path: Path) -> None:
    """Build the wheel and assert SKILL.md is packaged under immunize/skill_assets/."""
    try:
        import build  # noqa: F401
    except ImportError:
        pytest.skip("`build` not installed; skipping wheel-inclusion check")

    repo_root = Path(__file__).resolve().parents[1]
    outdir = tmp_path / "dist"
    proc = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(outdir)],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"wheel build failed:\n{proc.stdout}\n{proc.stderr}"

    wheels = list(outdir.glob("immunize-*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, got: {wheels}"

    with zipfile.ZipFile(wheels[0]) as zf:
        names = zf.namelist()
    target = "immunize/skill_assets/immunize-manager/SKILL.md"
    assert target in names, (
        f"{target} not found in wheel; got skill_assets entries: "
        f"{[n for n in names if 'skill_assets' in n]}"
    )
