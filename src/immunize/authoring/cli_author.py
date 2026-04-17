"""Contributor-only CLI: ``immunize author-pattern``.

This is the ONE module in the runtime src/ tree allowed to import
``anthropic``. End users never run this command; contributors use it with
their own ``ANTHROPIC_API_KEY`` to draft new bundled patterns from a
``CapturePayload``-shaped error JSON.

Flow:

1. Load + validate the error JSON as a ``CapturePayload``.
2. Analysis call — Claude proposes slug, error class, languages, match rules.
3. Drafting call — Claude emits the five content strings that make up a
   pattern (skill, cursor rule, pytest, repro, fix).
4. Write draft to a scratch directory.
5. Verify the scratch draft by invoking ``scripts/pattern_lint.py`` in a
   subprocess — same dual-run (FAIL-with-repro → PASS-with-fix → FAIL-after-restore)
   CI uses.
6. On verification failure, retry the drafting call once with prior errors
   injected as context. On second failure, dump to ``.immunize/rejected/<slug>/``
   and exit 1.
7. On success, move scratch → ``<output>/<slug>/`` and instruct the contributor
   to review before committing.

No auto-commit. No auto-push. The tool writes files; the human commits.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer
import yaml
from pydantic import ValidationError
from rich.console import Console

from immunize.models import AuthoringDraft, CapturePayload

console_err = Console(stderr=True)


class _DraftError(RuntimeError):
    """Drafting pipeline gave up — malformed tool output after retry."""


# --- Language → source-file extension for fixtures/repro.* + fixtures/fix.* --
_LANGUAGE_EXTENSION: dict[str, str] = {
    "python": ".py",
    "javascript": ".js",
    "typescript": ".ts",
    "jsx": ".jsx",
    "tsx": ".tsx",
    "go": ".go",
    "rust": ".rs",
}


# --- System prompts (these are the product; quality of authored patterns
#     depends on quality of these prompts). Keep them in sync with
#     _planning/PATTERN_AUTHORING.md.

ANALYSIS_SYSTEM_PROMPT = """\
You are a pattern-authoring analyst for `immunize`, an open-source library of curated
patterns that stop AI coding assistants from repeating common runtime errors.

You will be given a CapturePayload JSON describing a real error. Your job is to
produce a short JSON analysis that proposes pattern metadata. You are NOT writing
code yet — only classifying the error.

You MUST respond by calling the `propose_pattern_metadata` tool exactly once. Do
not emit any prose. Every field on the tool schema is required.

Rules (from PATTERN_AUTHORING.md, the "Ten Commandments"):

1. A pattern earns its slug. Generic names like "error-1", "fix-me", "common-error"
   are REJECTED. The slug MUST name the specific failure mode. Good: `cors-missing-credentials`,
   `react-hook-missing-dep`, `fastapi-async-in-sync-route`. Bad: `cors-error`, `react-bug`.
   Slug must be kebab-case, <= 40 chars, lowercase letters/digits/hyphens only.

4. Stderr regex anchors on signal, not noise. Match on the concrete error identifier
   the runtime emits (e.g., "Access-Control-Allow-Credentials", "TypeError: Cannot
   read property", "React Hook useEffect has a missing dependency"). Never match on
   generic English like "error occurred" or "something went wrong".

   GOOD: ["React Hook useEffect has a missing dependency"]
   GOOD: ["AttributeError: 'NoneType' object has no attribute"]
   BAD:  ["error"], ["failed"], ["Error:"]

5. min_confidence is honest. One specific regex -> 0.75. Two or three specific
   regexes -> 0.70. If the only signal is a short generic phrase, raise to 0.80.

8. Languages list is precise. If the error is JavaScript-specific, do NOT also tag
   TypeScript "for coverage." TypeScript has type-system errors that deserve their
   own patterns. Use lowercase canonical names: `python`, `javascript`, `typescript`,
   `jsx`, `tsx`, `go`, `rust`.

9. Never wrap domain knowledge. "React useState missing dep" is patternable.
   "Best practices for React" is not.

error_class is a free-form string describing the failure kind ("runtime",
"lint", "typecheck", "network", "build", "import", ...). error_class_hint is
OPTIONAL and must match an existing ERROR_CLASS_HINTS key in matcher.py, or be
null. If unsure, set it to null; a null hint just means the confidence scorer
adds zero from the hint term.

description is one sentence, <= 140 chars, stating the failure mode precisely.
"""

DRAFTING_SYSTEM_PROMPT = """\
You are a pattern author for `immunize`. You will be given a CapturePayload error
and a prior analysis (slug, error_class, languages, description). Your job is to
draft the five content strings that make up a bundled pattern.

You MUST respond by calling the `emit_pattern_draft` tool exactly once. No prose.
Every field on the tool schema is required.

Output fields:

- `skill_md`: full SKILL.md content INCLUDING the YAML frontmatter block. The
  frontmatter MUST contain `name: immunize-<slug>` and a `description:` line;
  slug comes from the prior analysis. Body <= 400 words. Open with what the AI
  should DO next time. End with one code example. No URLs. Teach the why, not
  just the how.

- `cursor_rule_mdc`: full cursor_rule.mdc content INCLUDING frontmatter. Frontmatter
  MUST contain `description:`, `globs:`, `alwaysApply: false`. Globs cover the
  languages from the analysis only (e.g., `**/*.jsx, **/*.tsx` for javascript/jsx).
  Body is substantially the same prose as SKILL.md's body, minus the frontmatter.

- `pytest_code`: full test_template.py content. Constraints:
    * Stdlib + pytest + unittest.mock ONLY. No network, no requests, no third-party.
    * Fixture read path: `Path(__file__).parent / "fixtures" / "repro.<ext>"`.
      The extension is fixed by the language (`.py`, `.jsx`, `.ts`, ...).
    * MUST test defaults, not knobs. The test calls the module/fixture the way
      a production consumer would. If the bug is about a default argument, the
      test MUST NOT pass that argument explicitly — that would hide the bug.
    * repro.<ext> and fix.<ext> MUST differ observably when this same test runs
      against them. The matcher-side verifier will confirm FAIL-with-repro,
      PASS-with-fix, FAIL-after-restore. If you cannot construct such a test,
      the pattern is not patternable — fail loudly in this field rather than
      emit trivial code.
    * Use tmp_path for any file IO the test performs on top of the fixture.

- `error_repro_snippet`: full fixtures/repro.<ext> content. The BUGGY example.
  Self-contained. Must cause the test above to FAIL when executed against it.

- `expected_fix_snippet`: full fixtures/fix.<ext> content. The FIXED example.
  Same module/API surface as repro — importable the same way, named the same
  functions / exports. Must cause the test above to PASS when its bytes are
  swapped into the repro path. If repro uses `def handler(request):` then fix
  MUST also expose `def handler(request):`.

Hard negatives (these trigger rejection):

- pytest_code that does `assert True` or otherwise ignores the fixture.
- pytest_code that passes the buggy parameter explicitly to avoid the bug.
- repro and fix that differ only in comments or whitespace.
- SKILL.md or cursor_rule.mdc without valid frontmatter.
- Any `import requests`, `import httpx`, network, or external-fixture access.
"""


# --- Tool schemas (Anthropic's "JSON mode" = tool-use with forced tool_choice)

ANALYSIS_TOOL_SCHEMA: dict[str, Any] = {
    "name": "propose_pattern_metadata",
    "description": "Propose pattern slug, error class, languages, and match rules.",
    "input_schema": {
        "type": "object",
        "properties": {
            "proposed_slug": {
                "type": "string",
                "pattern": "^[a-z0-9]+(-[a-z0-9]+)*$",
                "maxLength": 40,
            },
            "error_class": {"type": "string"},
            "languages": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
            "description": {"type": "string", "maxLength": 160},
            "stderr_patterns": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
            "error_class_hint": {"type": ["string", "null"]},
            "min_confidence": {"type": "number", "minimum": 0.5, "maximum": 1.0},
        },
        "required": [
            "proposed_slug",
            "error_class",
            "languages",
            "description",
            "stderr_patterns",
            "error_class_hint",
            "min_confidence",
        ],
    },
}

DRAFTING_TOOL_SCHEMA: dict[str, Any] = {
    "name": "emit_pattern_draft",
    "description": "Emit the five content strings that make up a bundled pattern.",
    "input_schema": {
        "type": "object",
        "properties": {
            "skill_md": {"type": "string"},
            "cursor_rule_mdc": {"type": "string"},
            "pytest_code": {"type": "string"},
            "error_repro_snippet": {"type": "string"},
            "expected_fix_snippet": {"type": "string"},
        },
        "required": [
            "skill_md",
            "cursor_rule_mdc",
            "pytest_code",
            "error_repro_snippet",
            "expected_fix_snippet",
        ],
    },
}


@dataclass(frozen=True)
class _AnalysisResult:
    proposed_slug: str
    error_class: str
    languages: list[str]
    description: str
    stderr_patterns: list[str]
    error_class_hint: str | None
    min_confidence: float


def author_pattern_cmd(
    from_error: Path,
    output: Path,
    model: str | None = None,
) -> None:
    """Draft a bundled pattern from a CapturePayload error JSON using Claude."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        console_err.print(
            "[red]ANTHROPIC_API_KEY is required.[/red] "
            "immunize author-pattern is a contributor-only tool; "
            "set the key to continue."
        )
        raise typer.Exit(1)

    payload = _load_capture_payload(from_error)

    # Lazy import: the SINGLE allowed runtime import of `anthropic` in src/.
    # Keeps `immunize capture`, `list`, `verify`, and `remove` anthropic-free
    # even transitively through the cli.py command table.
    import anthropic

    from immunize.config import load_settings

    settings = load_settings()
    chosen_model = model or settings.model
    client = anthropic.Anthropic(api_key=api_key)

    try:
        analysis = _run_analysis_call(client, chosen_model, payload)
    except _DraftError as exc:
        console_err.print(f"[red]analysis call failed: {exc}[/red]")
        raise typer.Exit(1) from exc

    try:
        draft = _run_drafting_call(client, chosen_model, payload, analysis)
    except _DraftError as exc:
        rejected = _dump_rejected_stub(analysis.proposed_slug, [f"drafting call failed: {exc}"])
        console_err.print(f"[red]drafting call failed; dumped to {rejected}[/red]")
        raise typer.Exit(1) from exc

    scratch = Path(tempfile.mkdtemp(prefix="immunize-author-"))
    try:
        pattern_dir = _write_draft_files(scratch, draft, analysis)
        lint_errors = _verify_scratch(scratch)

        if lint_errors:
            console_err.print(
                "[yellow]first-pass verification failed; "
                "retrying drafting call with prior errors as context.[/yellow]"
            )
            try:
                draft = _run_drafting_call(
                    client, chosen_model, payload, analysis, prior_errors=lint_errors
                )
            except _DraftError as exc:
                rejected = _dump_rejected(
                    pattern_dir, [f"retry drafting call failed: {exc}", *lint_errors]
                )
                console_err.print(f"[red]retry drafting failed; dumped to {rejected}[/red]")
                raise typer.Exit(1) from exc

            shutil.rmtree(pattern_dir)
            pattern_dir = _write_draft_files(scratch, draft, analysis)
            lint_errors = _verify_scratch(scratch)

        if lint_errors:
            rejected = _dump_rejected(pattern_dir, lint_errors)
            console_err.print(f"[red]verification failed after retry; dumped to {rejected}[/red]")
            for err in lint_errors:
                console_err.print(f"  - {err}")
            raise typer.Exit(1)

        final_dir = output / draft.proposed_slug
        if final_dir.exists():
            console_err.print(f"[red]{final_dir} already exists; refusing to overwrite[/red]")
            raise typer.Exit(1)
        output.mkdir(parents=True, exist_ok=True)
        shutil.move(str(pattern_dir), str(final_dir))
        console_err.print(
            f"[green]draft written to {final_dir}.[/green] review, edit if needed, then git commit."
        )
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# --- input loading ----------------------------------------------------------


def _load_capture_payload(path: Path) -> CapturePayload:
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        console_err.print(f"[red]failed to read {path}: {exc}[/red]")
        raise typer.Exit(1) from exc
    try:
        return CapturePayload.model_validate(raw)
    except ValidationError as exc:
        console_err.print(f"[red]{path} does not validate as a CapturePayload:[/red]\n{exc}")
        raise typer.Exit(1) from exc


# --- Claude calls -----------------------------------------------------------


def _render_payload_for_user(payload: CapturePayload) -> str:
    # Everything the model needs; datetime becomes isoformat via pydantic's dump.
    return json.dumps(payload.model_dump(mode="json"), indent=2)


def _extract_tool_input(response: Any, tool_name: str) -> dict[str, Any] | None:
    content = getattr(response, "content", None)
    if not content:
        return None
    for block in content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == tool_name:
            input_dict = getattr(block, "input", None)
            if isinstance(input_dict, dict):
                return input_dict
    return None


def _run_analysis_call(client: Any, model: str, payload: CapturePayload) -> _AnalysisResult:
    user_turn = (
        "Analyze this CapturePayload and propose pattern metadata.\n\n"
        f"<capture_payload>\n{_render_payload_for_user(payload)}\n</capture_payload>"
    )
    last_reason = "no response"
    for _ in range(2):
        resp = client.messages.create(
            model=model,
            max_tokens=1024,
            system=ANALYSIS_SYSTEM_PROMPT,
            tools=[ANALYSIS_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": "propose_pattern_metadata"},
            messages=[{"role": "user", "content": user_turn}],
        )
        data = _extract_tool_input(resp, "propose_pattern_metadata")
        if data is None:
            last_reason = "tool_use block missing from analysis response"
            continue
        try:
            return _AnalysisResult(
                proposed_slug=data["proposed_slug"],
                error_class=data["error_class"],
                languages=list(data["languages"]),
                description=data["description"],
                stderr_patterns=list(data["stderr_patterns"]),
                error_class_hint=data.get("error_class_hint"),
                min_confidence=float(data["min_confidence"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            last_reason = f"analysis payload malformed: {exc}"
            continue
    raise _DraftError(last_reason)


def _run_drafting_call(
    client: Any,
    model: str,
    payload: CapturePayload,
    analysis: _AnalysisResult,
    prior_errors: list[str] | None = None,
) -> AuthoringDraft:
    sections = [
        "Draft the five content strings for this pattern.",
        f"<analysis>\n{json.dumps(_analysis_to_dict(analysis), indent=2)}\n</analysis>",
        f"<capture_payload>\n{_render_payload_for_user(payload)}\n</capture_payload>",
    ]
    if prior_errors:
        joined = "\n".join(f"- {e}" for e in prior_errors)
        sections.append(
            "<prior_verification_failure>\n"
            "Your previous draft failed verification with these errors. Fix all of them:\n"
            f"{joined}\n"
            "</prior_verification_failure>"
        )
    user_turn = "\n\n".join(sections)

    last_reason = "no response"
    for _ in range(2):
        resp = client.messages.create(
            model=model,
            max_tokens=4096,
            system=DRAFTING_SYSTEM_PROMPT,
            tools=[DRAFTING_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": "emit_pattern_draft"},
            messages=[{"role": "user", "content": user_turn}],
        )
        data = _extract_tool_input(resp, "emit_pattern_draft")
        if data is None:
            last_reason = "tool_use block missing from drafting response"
            continue
        try:
            return AuthoringDraft(
                proposed_slug=analysis.proposed_slug,
                error_class=analysis.error_class,
                languages=analysis.languages,
                description=analysis.description,
                skill_md=data["skill_md"],
                cursor_rule_mdc=data["cursor_rule_mdc"],
                pytest_code=data["pytest_code"],
                error_repro_snippet=data["error_repro_snippet"],
                expected_fix_snippet=data["expected_fix_snippet"],
            )
        except (KeyError, TypeError, ValidationError) as exc:
            last_reason = f"drafting payload malformed: {exc}"
            continue
    raise _DraftError(last_reason)


def _analysis_to_dict(analysis: _AnalysisResult) -> dict[str, Any]:
    return {
        "proposed_slug": analysis.proposed_slug,
        "error_class": analysis.error_class,
        "languages": analysis.languages,
        "description": analysis.description,
        "stderr_patterns": analysis.stderr_patterns,
        "error_class_hint": analysis.error_class_hint,
        "min_confidence": analysis.min_confidence,
    }


# --- file materialisation ---------------------------------------------------


def _language_extension(languages: list[str]) -> str:
    for lang in languages:
        ext = _LANGUAGE_EXTENSION.get(lang.lower())
        if ext:
            return ext
    # Unknown language — default to .py so the dual-run still produces a
    # readable dump. Verification will almost certainly fail, but the
    # rejected/ dir will show the contributor what went wrong.
    return ".py"


def _build_pattern_yaml(draft: AuthoringDraft, analysis: _AnalysisResult) -> str:
    data = {
        "id": draft.proposed_slug,
        "version": 1,
        "schema_version": 1,
        "author": "@new-contributor",
        "origin": "bundled",
        "error_class": analysis.error_class,
        "languages": list(analysis.languages),
        "description": analysis.description,
        "match": {
            "stderr_patterns": list(analysis.stderr_patterns),
            "stdout_patterns": [],
            "error_class_hint": analysis.error_class_hint,
            "min_confidence": analysis.min_confidence,
        },
        "verification": {
            "pytest_relative_path": "test_template.py",
            "expected_fail_without_fix": True,
            "expected_pass_with_fix": True,
            "timeout_seconds": 30,
        },
    }
    return yaml.safe_dump(data, sort_keys=False)


def _write_draft_files(scratch: Path, draft: AuthoringDraft, analysis: _AnalysisResult) -> Path:
    pattern_dir = scratch / draft.proposed_slug
    fixtures_dir = pattern_dir / "fixtures"
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    ext = _language_extension(analysis.languages)

    (pattern_dir / "pattern.yaml").write_text(_build_pattern_yaml(draft, analysis))
    (pattern_dir / "SKILL.md").write_text(draft.skill_md)
    (pattern_dir / "cursor_rule.mdc").write_text(draft.cursor_rule_mdc)
    (pattern_dir / "test_template.py").write_text(draft.pytest_code)
    (fixtures_dir / f"repro{ext}").write_text(draft.error_repro_snippet)
    (fixtures_dir / f"fix{ext}").write_text(draft.expected_fix_snippet)
    return pattern_dir


# --- verification via scripts/pattern_lint.py -------------------------------


def _find_pattern_lint_script() -> Path:
    # Contributor-only tool: always run from a repo clone. cli_author.py lives
    # at src/immunize/authoring/cli_author.py, so parents[3] is the repo root.
    here = Path(__file__).resolve()
    return here.parents[3] / "scripts" / "pattern_lint.py"


def _verify_scratch(scratch: Path) -> list[str]:
    """Run scripts/pattern_lint.py --patterns-dir <scratch>. Return error lines."""
    script = _find_pattern_lint_script()
    if not script.is_file():
        return [f"pattern_lint script not found at {script} — are you in a repo clone?"]
    result = subprocess.run(
        [sys.executable, str(script), "--patterns-dir", str(scratch)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode == 0:
        return []
    errors: list[str] = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("FAIL "):
            errors.append(stripped[len("FAIL ") :].strip())
        elif errors and stripped and not stripped.startswith("OK "):
            errors.append(stripped)
    if not errors:
        errors.append(
            f"pattern_lint exited with {result.returncode}; stdout: {result.stdout.strip()[:500]}"
        )
    return errors


def _dump_rejected_stub(slug: str, errors: list[str]) -> Path:
    """Dump a REJECTION.md when we never produced a pattern dir (drafting failed)."""
    rejected_root = Path.cwd() / ".immunize" / "rejected"
    dest = rejected_root / slug
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "REJECTION.md").write_text(
        "# Rejected draft (no files produced)\n\n"
        "Drafting failed before any pattern files could be materialised. "
        "Errors:\n\n" + "\n".join(f"- {e}" for e in errors) + "\n"
    )
    return dest


def _dump_rejected(pattern_dir: Path, errors: list[str]) -> Path:
    rejected_root = Path.cwd() / ".immunize" / "rejected"
    rejected_root.mkdir(parents=True, exist_ok=True)
    dest = rejected_root / pattern_dir.name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.move(str(pattern_dir), str(dest))
    (dest / "REJECTION.md").write_text(
        "# Rejected draft\n\n"
        "Verification failed for this draft. Errors:\n\n"
        + "\n".join(f"- {e}" for e in errors)
        + "\n"
    )
    return dest
