from __future__ import annotations

import json
import re

import anthropic
from pydantic import ValidationError

from immunize.config import ConfigError, build_client
from immunize.models import CapturePayload, Diagnosis, Settings

SYSTEM_PROMPT = """\
You are a senior engineer diagnosing a runtime error an AI coding assistant produced.
You will receive the error's stdout, stderr, command, and working directory.
Produce a JSON response matching this exact schema:

{
  "root_cause": <one sentence, <= 30 words>,
  "error_class": <one of: cors, import, auth, rate_limit, type_error, null_ref,
                  config, network, other>,
  "is_generalizable": <true if this pattern will recur, false if one-off>,
  "canonical_description": <30-50 words, suitable as SKILL.md description frontmatter>,
  "fix_summary": <what the developer should do, <= 40 words>,
  "language": <primary language of the affected code>,
  "slug": <kebab-case, <= 40 chars, filename-safe>,
  "semgrep_applicable": <true if the error is a code pattern detectable by Semgrep>
}

Rules:
- Return JSON only. No prose before or after. No code fences.
- If is_generalizable is false, other fields can be best-effort.
- slug should be semantic (e.g., "cors-missing-credentials" not "error-1").
- semgrep_applicable is true ONLY for patterns in source code, not for env/config/network errors.
"""

_RETRY_REMINDER = (
    "Your previous response failed schema validation. "
    "Return ONLY the JSON object matching the schema — "
    "no prose, no code fences, no commentary."
)


class DiagnoseError(Exception):
    """Raised when the diagnose step fails in a way the pipeline cannot recover from."""


# Error classes that are definitionally not source-code patterns.
# Belt-and-suspenders against model drift flipping semgrep_applicable on.
_NON_SOURCE_CLASSES = frozenset({"cors", "network", "auth", "rate_limit", "config"})


def diagnose(
    payload: CapturePayload,
    settings: Settings,
    *,
    client: anthropic.Anthropic | None = None,
) -> Diagnosis:
    api = client or build_client(settings)
    user_prompt = _build_user_prompt(payload)

    first = _call(api, settings.model, SYSTEM_PROMPT, user_prompt)
    try:
        return _finalize(Diagnosis.model_validate_json(_extract_json(first)))
    except (ValidationError, json.JSONDecodeError):
        pass

    retry_system = SYSTEM_PROMPT + "\n\n" + _RETRY_REMINDER
    second = _call(api, settings.model, retry_system, user_prompt)
    try:
        return _finalize(Diagnosis.model_validate_json(_extract_json(second)))
    except (ValidationError, json.JSONDecodeError) as e:
        raise DiagnoseError(
            f"Diagnose response failed validation twice. Last response: {second[:500]}"
        ) from e


def _finalize(diag: Diagnosis) -> Diagnosis:
    """Post-validation corrections for known model drift."""
    if diag.error_class in _NON_SOURCE_CLASSES and diag.semgrep_applicable:
        return diag.model_copy(update={"semgrep_applicable": False})
    return diag


def _call(client: anthropic.Anthropic, model: str, system: str, user: str) -> str:
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
        raise ConfigError("Your API key is invalid or lacks permissions") from e
    except anthropic.APIError as e:
        raise DiagnoseError(f"API call failed: {e}") from e

    for block in resp.content:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""


def _build_user_prompt(payload: CapturePayload) -> str:
    stderr = _smart_truncate(payload.stderr, head=1000, tail=3000)
    stdout = _smart_truncate(payload.stdout, head=2000, tail=2000)
    return json.dumps(
        {
            "source": payload.source,
            "tool_name": payload.tool_name,
            "command": payload.command,
            "exit_code": payload.exit_code,
            "cwd": payload.cwd,
            "stdout": stdout,
            "stderr": stderr,
        },
        indent=2,
    )


def _smart_truncate(text: str, *, head: int, tail: int, total_cap: int = 4000) -> str:
    if len(text) <= total_cap:
        return text
    dropped = len(text) - head - tail
    return f"{text[:head]}\n... [{dropped} chars truncated] ...\n{text[-tail:]}"


def _extract_json(text: str) -> str:
    """Strip code fences and any prose around the JSON object."""
    stripped = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    if fence:
        stripped = fence.group(1).strip()
    first = stripped.find("{")
    if first > 0:
        stripped = stripped[first:]
    last = stripped.rfind("}")
    if last >= 0:
        stripped = stripped[: last + 1]
    return stripped
