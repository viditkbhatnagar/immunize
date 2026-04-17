from __future__ import annotations

import json
import re

import anthropic
import yaml

from immunize.config import ConfigError, build_client
from immunize.generate._errors import GenerateError
from immunize.models import CapturePayload, Diagnosis, Settings

SYSTEM_PROMPT = """\
You produce a Semgrep rule targeting a specific source-code pattern.

Return ONLY YAML matching this shape — no code fences, no prose:

rules:
  - id: immunize-<slug>
    pattern: <conservative Semgrep pattern with at least one literal token>
    message: <canonical description>
    severity: WARNING
    languages: [<language>]

Rules:
- The id must be "immunize-<slug>" using the diagnosis slug.
- Keep the pattern conservative; over-broad patterns create noise.
- Severity is always WARNING.
"""


def generate_semgrep_yaml(
    diagnosis: Diagnosis,
    payload: CapturePayload,
    settings: Settings,
    *,
    client: anthropic.Anthropic | None = None,
) -> str | None:
    """Return Semgrep YAML, or None when gated off or validation fails.

    Gated off in v1 because settings.generate_semgrep defaults to False. Even when
    enabled, we never block the pipeline on a bad YAML — downstream inject just
    skips the semgrep path.
    """
    if not (settings.generate_semgrep and diagnosis.semgrep_applicable):
        return None
    api = client or build_client(settings)
    raw = _call(api, settings.model, _build_user_prompt(diagnosis, payload))
    return _validate(raw, slug=diagnosis.slug)


def _call(client: anthropic.Anthropic, model: str, user: str) -> str:
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
        raise ConfigError("Your API key is invalid or lacks permissions") from e
    except anthropic.APIError as e:
        raise GenerateError(f"semgrep generation API call failed: {e}") from e
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""


def _build_user_prompt(diagnosis: Diagnosis, payload: CapturePayload) -> str:
    return json.dumps(
        {"diagnosis": diagnosis.model_dump(), "stderr_excerpt": payload.stderr[-1000:]},
        indent=2,
    )


def _validate(raw: str, *, slug: str) -> str | None:
    stripped = _strip_code_fences(raw)
    try:
        doc = yaml.safe_load(stripped)
    except yaml.YAMLError:
        return None
    if not isinstance(doc, dict):
        return None
    rules = doc.get("rules")
    if not isinstance(rules, list) or not rules:
        return None
    first = rules[0]
    if not isinstance(first, dict) or first.get("id") != f"immunize-{slug}":
        return None
    return stripped


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    fence = re.match(r"^```(?:yaml|yml)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    return stripped
