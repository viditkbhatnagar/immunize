from __future__ import annotations

import anthropic

from immunize.config import build_client
from immunize.generate._errors import GenerateError
from immunize.generate.cursor_rule import generate_cursor_rule
from immunize.generate.pytest_gen import PytestGenOutput, generate_pytest
from immunize.generate.semgrep import generate_semgrep_yaml
from immunize.generate.skill import generate_skill_md
from immunize.models import CapturePayload, Diagnosis, GeneratedArtifacts, Settings


def generate_all(
    diagnosis: Diagnosis,
    payload: CapturePayload,
    settings: Settings,
    *,
    client: anthropic.Anthropic | None = None,
) -> GeneratedArtifacts:
    api = client or build_client(settings)
    skill_md = generate_skill_md(diagnosis, payload, settings, client=api)
    pytest_out = generate_pytest(diagnosis, payload, settings, client=api)
    cursor_rule = generate_cursor_rule(diagnosis, skill_md)
    semgrep_yaml = generate_semgrep_yaml(diagnosis, payload, settings, client=api)
    return GeneratedArtifacts(
        skill_md=skill_md,
        cursor_rule=cursor_rule,
        semgrep_yaml=semgrep_yaml,
        pytest_code=pytest_out.pytest_code,
        expected_fix_snippet=pytest_out.expected_fix_snippet,
        error_repro_snippet=pytest_out.error_repro_snippet,
    )


__all__ = [
    "GenerateError",
    "PytestGenOutput",
    "generate_all",
    "generate_cursor_rule",
    "generate_pytest",
    "generate_semgrep_yaml",
    "generate_skill_md",
]
