from __future__ import annotations

import pytest

from immunize.generate.cursor_rule import LANGUAGE_GLOBS, generate_cursor_rule
from immunize.models import Diagnosis


def _diag(language: str = "typescript") -> Diagnosis:
    return Diagnosis(
        root_cause="rc",
        error_class="cors",
        is_generalizable=True,
        canonical_description=(
            "Cross-origin fetch needs credentials include and server Allow-Credentials."
        ),
        fix_summary="fs",
        language=language,
        slug="cors-missing-credentials",
        semgrep_applicable=False,
    )


_SKILL_MD = (
    "---\n"
    "name: immunize-cors-missing-credentials\n"
    "description: foo\n"
    "---\n\n"
    "# Avoid CORS credential errors\n\n"
    "Always include credentials when fetching authenticated cross-origin endpoints.\n"
)


@pytest.mark.parametrize("language", list(LANGUAGE_GLOBS.keys()))
def test_every_language_in_map_resolves(language: str) -> None:
    rule = generate_cursor_rule(_diag(language=language), _SKILL_MD)
    assert f"globs: {LANGUAGE_GLOBS[language]}" in rule


def test_unknown_language_falls_back_to_default() -> None:
    rule = generate_cursor_rule(_diag(language="cobol"), _SKILL_MD)
    assert "globs: **/*" in rule


def test_strips_skill_frontmatter_and_h1() -> None:
    rule = generate_cursor_rule(_diag(), _SKILL_MD)
    assert "Avoid CORS credential errors" not in rule
    assert "name: immunize-cors-missing-credentials" not in rule
    assert "Always include credentials" in rule


def test_mdc_frontmatter_shape() -> None:
    rule = generate_cursor_rule(_diag(), _SKILL_MD)
    assert rule.startswith("---\n")
    assert "description:" in rule
    assert "alwaysApply: false" in rule
    # Exactly one closing --- before the body.
    assert rule.count("---") == 2


def test_body_only_input_still_works() -> None:
    rule = generate_cursor_rule(_diag(), "Just body, no frontmatter, no heading.\n")
    assert "Just body" in rule
    assert rule.startswith("---\n")


def test_language_case_irrelevant_via_model_validator() -> None:
    # Diagnosis.language is normalized to lowercase (by the field_validator), so
    # "Python" becomes "python" and resolves to **/*.py.
    rule = generate_cursor_rule(_diag(language="Python"), _SKILL_MD)
    assert f"globs: {LANGUAGE_GLOBS['python']}" in rule
