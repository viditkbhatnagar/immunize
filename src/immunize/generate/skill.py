from __future__ import annotations

import json
import re

import anthropic

from immunize.config import ConfigError, build_client
from immunize.generate._errors import GenerateError
from immunize.models import CapturePayload, Diagnosis, Settings

SYSTEM_PROMPT = """\
You write SKILL.md files for AI coding assistants following the agentskills.io standard.

Given a diagnosis of a runtime error an AI made, produce a SKILL.md that teaches
assistants (Claude Code, Cursor, Codex, Gemini CLI) to never make the specific
mistake again.

Required structure:

---
name: immunize-<slug>
description: <one paragraph, 30-50 words, suitable for SKILL.md frontmatter>
---

# <concise title>

<body: 100-400 words, focused on this specific error, with one concrete code example>

Rules:
- Return ONLY the markdown content. No code fences wrapping the document.
- The frontmatter name must be exactly "immunize-<slug>" using the slug from the diagnosis.
- The body should teach assistants how to recognize and avoid the mistake.
- Include exactly one short code example that shows the correct pattern.
- Do not invent filenames or repo paths; keep the example self-contained.
"""


def generate_skill_md(
    diagnosis: Diagnosis,
    payload: CapturePayload,
    settings: Settings,
    *,
    client: anthropic.Anthropic | None = None,
) -> str:
    api = client or build_client(settings)
    raw = _call(api, settings.model, _build_user_prompt(diagnosis, payload))
    stripped = _strip_code_fences(raw)
    return _normalize_frontmatter(
        stripped, slug=diagnosis.slug, description=diagnosis.canonical_description
    )


def _call(client: anthropic.Anthropic, model: str, user: str) -> str:
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
        raise ConfigError("Your API key is invalid or lacks permissions") from e
    except anthropic.APIError as e:
        raise GenerateError(f"SKILL.md generation failed: {e}") from e
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""


def _build_user_prompt(diagnosis: Diagnosis, payload: CapturePayload) -> str:
    return json.dumps(
        {
            "diagnosis": diagnosis.model_dump(),
            "stderr_excerpt": payload.stderr[-2000:],
        },
        indent=2,
    )


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    fence = re.match(r"^```(?:markdown|md)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    return stripped


def _normalize_frontmatter(md: str, *, slug: str, description: str) -> str:
    """Replace any emitted frontmatter with a canonical block so the name is correct."""
    body = md.lstrip()
    if body.startswith("---"):
        lines = body.splitlines()
        end = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end = i
                break
        if end is not None:
            body = "\n".join(lines[end + 1 :]).lstrip()
    safe_description = description.replace("\n", " ").replace('"', "'").strip()
    return (
        "---\n"
        f"name: immunize-{slug}\n"
        f"description: {safe_description}\n"
        "---\n\n"
        f"{body.rstrip()}\n"
    )
