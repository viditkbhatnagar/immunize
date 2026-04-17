from __future__ import annotations

import json

import anthropic
from pydantic import BaseModel, ConfigDict, ValidationError

from immunize.config import ConfigError, build_client
from immunize.diagnose import _extract_json
from immunize.generate._errors import GenerateError
from immunize.models import CapturePayload, Diagnosis, Settings

SYSTEM_PROMPT = """\
You produce a pytest regression test that proves a specific runtime error is fixed.

Given a diagnosis and stderr excerpt, output a JSON object with EXACTLY three keys:

{
  "error_repro_snippet": "<Python code saved as app_under_test.py that reproduces the bug>",
  "pytest_code": "<A self-contained pytest test saved as test_immunity.py that
     imports from app_under_test and FAILS against error_repro_snippet but
     PASSES against expected_fix_snippet>",
  "expected_fix_snippet": "<Python code that, when it REPLACES app_under_test.py,
     makes pytest_code pass>"
}

Rules:
- Return ONLY the JSON object. No prose before or after. No code fences.
- All three snippets must be valid Python modules.
- error_repro_snippet and expected_fix_snippet must define the SAME public names
  (functions, classes, constants) so pytest_code imports remain valid across swap.
- pytest_code may import from `app_under_test` plus stdlib, pytest, and unittest.mock ONLY.
- No network calls, no real file I/O beyond pytest's tmp_path fixture.
- For non-Python errors (TypeScript, Go, etc.), simulate the error pattern in Python:
  e.g., a function that raises a ValueError unless a flag is set, with pytest asserting
  the flag-checking behavior. This is a pattern-based sanity check, not a language VM.
- Keep each snippet under 40 lines; prefer the smallest repro that exercises the bug.

Test-design rules (the bug is structural, not parameter-driven):

1. Test default behavior, not parameterized behavior. Call functions the way a
   consumer would in production — with their defaults in play. Do NOT override
   internal parameters that the fix is meant to change.

2. Do not parameterize around the bug. If the bug is "the default value is wrong,"
   the test must not pass that parameter explicitly. The test must exercise the
   default path.

3. Assert observable behavior, not internal state. Check return values, exceptions
   raised, or side effects. Do not introspect module internals via __dict__,
   getattr on private attributes, etc.

4. Self-check before responding: error_repro_snippet and expected_fix_snippet must
   differ in observable behavior when invoked identically. If calling both with the
   same test inputs produces the same result, the snippets are wrong — revise them.
"""


class PytestGenOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pytest_code: str
    expected_fix_snippet: str
    error_repro_snippet: str


def generate_pytest(
    diagnosis: Diagnosis,
    payload: CapturePayload,
    settings: Settings,
    *,
    client: anthropic.Anthropic | None = None,
) -> PytestGenOutput:
    api = client or build_client(settings)
    raw = _call(api, settings.model, _build_user_prompt(diagnosis, payload))
    try:
        return PytestGenOutput.model_validate_json(_extract_json(raw))
    except (ValidationError, json.JSONDecodeError) as e:
        raise GenerateError(f"pytest_gen: invalid JSON response: {raw[:500]}") from e


def _call(client: anthropic.Anthropic, model: str, user: str) -> str:
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
        raise ConfigError("Your API key is invalid or lacks permissions") from e
    except anthropic.APIError as e:
        raise GenerateError(f"pytest_gen API call failed: {e}") from e
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""


def _build_user_prompt(diagnosis: Diagnosis, payload: CapturePayload) -> str:
    return json.dumps(
        {
            "diagnosis": diagnosis.model_dump(),
            "command": payload.command,
            "stderr_excerpt": payload.stderr[-2000:],
        },
        indent=2,
    )
