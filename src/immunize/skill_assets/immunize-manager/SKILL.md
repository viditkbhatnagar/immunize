---
name: immunize-manager
description: Use when a bash tool call fails with a runtime error AND the user might want a persistent guardrail against that error recurring. Also use when the user asks about preventing AI-generated errors, managing .immunize/ state, or invoking immunize directly.
---

# immunize-manager

The user has installed `immunize` — a pattern library that turns runtime errors into verified guardrails for AI coding assistants. When a command you run fails with a runtime error that could plausibly recur, check whether `immunize` has a matching pattern and, if so, apply it.

## When to invoke immunize

Invoke `immunize capture` when ALL of the following hold:

1. A bash tool call you just ran exited non-zero.
2. The error looks like a runtime failure (stack trace, CORS rejection, auth failure, missing module, null/undefined reference, etc.) — something the user would want to prevent from happening again.
3. The user has not immediately identified and corrected it (e.g. they did not type the fix or say "that's a typo, let me redo it").

## When NOT to invoke

- Compilation errors / type errors that the user is actively iterating on.
- Test failures where the test is *supposed* to fail (expected-fail tests, red-green TDD moments, `pytest -x` exploration).
- Transient errors (network blip, a flaky dependency's rate limit).
- Errors the user has already acknowledged and said they'll fix manually.
- Errors in code the user is deliberately probing.

If unsure, skip. A silent skip is better than a noisy false positive.

## How to invoke

Construct a JSON payload matching this shape and pipe it on stdin:

```json
{
  "source": "claude-code-session",
  "stderr": "<full stderr from the failing command>",
  "stdout": "<full stdout>",
  "command": "<the command that failed>",
  "exit_code": 1,
  "cwd": "<absolute working directory>",
  "timestamp": "<ISO 8601 UTC>",
  "project_fingerprint": "<short stable id, e.g. a git remote url hash>"
}
```

Then:

```bash
echo '<payload-json>' | immunize capture --source claude-code-session
```

Read exactly one line of JSON from stdout. Ignore stderr (human-readable Rich output that's not for you).

## Outcome handling

The response has an `outcome` field with one of three values.

### `outcome: "matched_and_verified"`

```json
{"outcome": "matched_and_verified", "matched": true, "verified": true,
 "pattern_id": "<slug>", "pattern_origin": "bundled|local|community",
 "confidence": 0.92,
 "artifacts": {"skill": "<abs>", "cursor_rule": "<abs>", "pytest": "<abs>"}}
```

immunize matched a known pattern, verified it in this environment, and injected three files. Tell the user something like:

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

No bundled or local pattern matches this error. `can_author_locally: true` means a future release will let you draft a local pattern inline via `immunize author-local-from-session` — but that subcommand is not available in the currently installed version. Tell the user:

> immunize has no bundled pattern for this error. A future release will let me draft a local pattern inline. For now, a contributor could run `immunize author-pattern` (uses their Anthropic API key) to draft one and send it upstream.

Do not attempt to invoke `immunize author-local-from-session` yet — it will fail with "command not found".

## Design constraints you should know

- immunize's Python code NEVER calls the Anthropic API at runtime. Matching and verification are purely deterministic regex + subprocess.
- `immunize author-pattern` (contributor-only) does call Claude — but end users never need it.
- Bundled patterns shipped with a release are immutable. Users get new patterns by upgrading the package (`pip install --upgrade immunize`).
