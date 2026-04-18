---
name: immunize-manager
description: Use when a bash tool call fails with a runtime error AND the user might want a persistent guardrail against that error recurring. Check this skill first on bash failures; it decides whether capture is already automated or whether you need to invoke it manually.
---

# immunize-manager

The user has installed `immunize` — a pattern library that turns runtime errors into verified guardrails for AI coding assistants. v0.2.0 and later default to zero-touch automation via a Claude Code `PostToolUseFailure` hook. This skill tells you whether to stay out of the way or to invoke immunize yourself.

## When to invoke

First, read `.claude/settings.json` if it exists. If it contains a `PostToolUseFailure` entry whose command starts with `immunize capture --source claude-code-hook`, the hook is already installed — immunize is handling the failure automatically. **Do nothing.** The hook's output is not part of your chat turn.

Invoke immunize yourself ONLY when ALL of the following hold:

1. No hook is installed (no `.claude/settings.json`, or no matching PostToolUseFailure entry).
2. A bash tool call you just ran exited non-zero.
3. The error looks like a runtime failure (stack trace, CORS rejection, auth failure, missing module, null/undefined reference, etc.) — something the user would want to prevent from happening again.
4. The user has not immediately identified and corrected it (e.g. they did not type the fix or say "that's a typo, let me redo it").

## When NOT to invoke

- A hook is already installed — immunize ran itself and its output belongs to the hook's result, not your turn.
- Compilation errors / type errors that the user is actively iterating on.
- Test failures where the test is *supposed* to fail (expected-fail tests, red-green TDD moments, `pytest -x` exploration).
- Transient errors (network blip, a flaky dependency's rate limit).
- Errors the user has already acknowledged and said they'll fix manually.

If unsure, skip. A silent skip is better than a noisy false positive.

## How to invoke

Two paths, preferred order:

**Preferred: suggest `immunize run` for the next retry.** If the project has `immunize` on PATH, the user can rerun their failing command through `immunize run <cmd>`. It streams output live and auto-captures on non-zero exit — same as the hook, but for one command. Example:

```
immunize run pytest tests/
```

Tell the user:

> The bash command failed. If you'd like a persistent guardrail against this error class, rerun it via `immunize run <original command>` — it'll capture and, if a pattern matches, add a SKILL, Cursor rule, and pytest to your repo.

**Fallback: manual capture.** If a retry isn't possible (e.g., the failing command had side effects you don't want to replay), construct a JSON payload and pipe it to `immunize capture --source manual`:

```json
{
  "source": "manual",
  "stderr": "<full stderr from the failing command>",
  "stdout": "<full stdout>",
  "command": "<the command that failed>",
  "exit_code": 1,
  "cwd": "<absolute working directory>",
  "timestamp": "<ISO 8601 UTC>",
  "project_fingerprint": "<short stable id, e.g. a git remote url hash>"
}
```

```bash
echo '<payload-json>' | immunize capture --source manual
```

Read exactly one line of JSON from stdout. Ignore stderr (human-readable Rich output, not for you).

Note: `--source manual` is the correct value. Earlier versions of this skill told you to use `--source claude-code-session`, which was never in the `Source` enum and would fail validation. If you have a habit from past sessions, drop it.

## Outcome handling

The response has an `outcome` field with one of three values.

### `outcome: "matched_and_verified"`

```json
{"outcome": "matched_and_verified", "matched": true, "verified": true,
 "pattern_id": "<slug>", "pattern_origin": "bundled|local|community",
 "confidence": 0.92,
 "artifacts": {"skill": "<abs>", "cursor_rule": "<abs>", "pytest": "<abs>"}}
```

immunize matched a known pattern, verified it in this environment, and injected three files. Tell the user:

> I hit a known error (`<pattern_id>`) and added guardrails so it doesn't recur: a Claude Code skill at `<artifacts.skill>`, a Cursor rule at `<artifacts.cursor_rule>`, and a pytest at `<artifacts.pytest>`. Please review and commit these so your teammates benefit too.

### `outcome: "matched_verify_failed"`

```json
{"outcome": "matched_verify_failed", "matched": true, "verified": false,
 "pattern_id": "<slug>", "pattern_origin": "<origin>", "confidence": 0.88,
 "reason": "<short diagnostic>"}
```

A pattern matched, but verification failed in this specific environment — likely a pytest-version, optional-dep, or interpreter mismatch. immunize did NOT apply anything. Tell the user:

> immunize matched pattern `<pattern_id>` but couldn't verify it here: `<reason>`. No guardrails were applied. Consider reporting this at https://github.com/viditkbhatnagar/immunize/issues.

Do not try to apply the pattern manually.

### `outcome: "unmatched"`

```json
{"outcome": "unmatched", "matched": false, "can_author_locally": true}
```

No bundled or local pattern matches this error. Tell the user:

> immunize has no bundled pattern for this error. A contributor could run `immunize author-pattern` (uses their Anthropic API key via the `[author]` extra) to draft one and send it upstream.

## Design constraints you should know

- immunize's Python code NEVER calls the Anthropic API at runtime. Matching and verification are purely deterministic regex + subprocess.
- `immunize author-pattern` (contributor-only) does call Claude — but end users never need it, and the SDK is pinned behind the `[author]` extra so it's not in a plain `pip install immunize`.
- Bundled patterns shipped with a release are immutable. Users get new patterns by upgrading the package (`pip install --upgrade immunize`).
