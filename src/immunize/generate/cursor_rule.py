from __future__ import annotations

from immunize.models import Diagnosis

LANGUAGE_GLOBS: dict[str, str] = {
    "python": "**/*.py",
    "typescript": "**/*.ts,**/*.tsx",
    "javascript": "**/*.js,**/*.jsx",
    "go": "**/*.go",
    "rust": "**/*.rs",
    "java": "**/*.java",
    "ruby": "**/*.rb",
    "php": "**/*.php",
    "bash": "**/*.sh",
}
_DEFAULT_GLOBS = "**/*"


def generate_cursor_rule(diagnosis: Diagnosis, skill_md: str) -> str:
    """Derive a Cursor .mdc rule from the generated SKILL.md. Pure, no LLM call."""
    body = _extract_body(skill_md)
    globs = LANGUAGE_GLOBS.get(diagnosis.language, _DEFAULT_GLOBS)
    description = diagnosis.canonical_description.replace("\n", " ").replace('"', "'").strip()
    return (
        "---\n"
        f"description: {description}\n"
        f"globs: {globs}\n"
        "alwaysApply: false\n"
        "---\n\n"
        f"{body}"
    )


def _extract_body(skill_md: str) -> str:
    """Strip frontmatter and a leading H1 from SKILL.md."""
    body = skill_md.lstrip()
    if body.startswith("---"):
        lines = body.splitlines()
        end = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end = i
                break
        if end is not None:
            body = "\n".join(lines[end + 1 :]).lstrip()
    lines = body.splitlines()
    if lines and lines[0].startswith("# "):
        rest = lines[1:]
        while rest and rest[0].strip() == "":
            rest = rest[1:]
        body = "\n".join(rest)
    return body.rstrip() + "\n"
