# immunize

> A curated pattern library that stops AI coding assistants from repeating common runtime errors. No API key. No LLM calls at runtime.

[![PyPI version](https://img.shields.io/pypi/v/immunize.svg)](https://pypi.org/project/immunize/)
[![Python versions](https://img.shields.io/pypi/pyversions/immunize.svg)](https://pypi.org/project/immunize/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](./LICENSE)
[![CI](https://github.com/viditkbhatnagar/immunize/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/viditkbhatnagar/immunize/actions/workflows/ci.yml)

- **Zero-touch automation.** Install one hook; every failed bash command in Claude Code auto-captures.
- **Deterministic pattern library.** Every immunity is a pre-verified bundle of a Claude Code skill, a Cursor rule, and a pytest regression test.
- **No API key required.** Matching and verification are pure regex + subprocess; the Python runtime never calls an LLM.
- **Works where you already are.** Ships a hook for Claude Code, a skill for Claude Code, and rules for Cursor; commit the injected artifacts and your whole team picks them up on `git pull`.

## 30-second tour

```bash
pip install immunize
cd your-project
immunize install-skill        # drops .claude/skills/immunize-manager/SKILL.md
immunize install-hook         # registers .claude/settings.json PostToolUseFailure hook
```

Restart Claude Code. From now on, when Claude runs a bash command that fails with a known error class — CORS preflight rejection, `AttributeError: 'NoneType'`, `ModuleNotFoundError`, rate-limit crash, etc. — immunize automatically:

1. Runs the matcher against the failure.
2. If a pattern matches, runs the pattern's pytest to verify the fix works in this environment.
3. Injects three artifacts into your repo:

```
.claude/skills/immunize-<pattern-id>/SKILL.md
.cursor/rules/<pattern-id>.mdc
tests/immunized/<pattern-id>/test_template.py
```

Commit them. Next Claude Code, Cursor, or CI run automatically picks the guardrails up.

**Not using Claude Code?** `immunize run <cmd>` wraps any shell command and captures failures the same way:

```bash
immunize run pytest tests/
immunize run npm test
immunize run python manage.py migrate
```

## Why?

AI coding assistants repeat the same mistakes every session. You fix the stale-closure bug in your `useEffect` on Monday, and by Wednesday Claude has written the same bug in a different file. The model has no durable memory of what you corrected.

The existing answers each fall short in one way:

- **Claude Code memory / Cursor rules** are single-tool and per-user. They're untested — there's no build-time check that the rule actually prevents the error it claims to prevent — and they're hard to share with a team.
- **Telling the model "don't do that again"** works for one session. It doesn't survive a `/clear` or a new teammate joining.
- **Linters and type checkers** catch the patterns their authors thought of, not the ones that AI models specifically over-produce.

`immunize` is a different bet: a small, curated, *verified* library of patterns covering the mistakes that matter. Each pattern ships with a pytest that proves the fix works and the bug reproduces without it. When you capture an error that matches, the artifacts land in your repo as committed code — durable, team-shared, and cross-tool.

## How it works

Four paths in, one pipeline:

1. **Hook-driven automatic capture (flagship, v0.2.0).** Claude Code's `PostToolUseFailure` event fires on every failed bash tool call; your registered hook runs `immunize capture --source claude-code-hook` with the failure payload on stdin. Zero manual steps after `immunize install-hook`.
2. **Shell wrapper: `immunize run <cmd>`.** For shells outside Claude Code (Cursor, CI, bare terminals). Tees stdout/stderr live to your terminal and auto-captures on non-zero exit. Exit codes propagate; `--timeout N` enforces deadlines; `--no-capture` disables matching for a single run.
3. **Bundled skill.** The `immunize-manager` Claude Code skill teaches Claude when to invoke immunize (and when to stay out of the way because the hook is handling it).
4. **Manual capture.** `echo '<json>' | immunize capture --source manual` — useful for testing, scripting, or replaying an error payload.

All four paths feed the same matcher → verify → inject pipeline:

```
failure payload
        │
        ▼
  immunize capture  ─►  matcher (regex + heuristics)  ─►  verify (pytest)  ─►  inject
                          │                                    │                   │
                          ▼                                    ▼                   ▼
                 src/immunize/patterns/               subprocess on         .claude/skills/
                 src/immunize/patterns_local/         a tempdir             .cursor/rules/
                                                                            tests/immunized/
```

The matcher is pure regex + error-class heuristics — no network, no API key. Bundled patterns ship inside the wheel; local patterns live in `<project>/.immunize/patterns_local/`.

## What `immunize` does NOT do

- **It does not fix your current error.** You still fix the immediate problem yourself. immunize installs guardrails so your AI doesn't repeat the same class of error in future sessions.
- **It's reactive, not proactive.** Patterns only get installed after an error occurs. A clean-history repo gets no artifacts until something fails.
- **It doesn't call an LLM at runtime.** Matching is regex; verification is subprocess pytest; injection is atomic file writes. The only LLM path in the package is `immunize author-pattern` (contributor-only, behind the `[author]` extra).

## What's bundled in v0.2

Seven patterns, calibrated against real-world stderr samples (see [_planning/MATCHER_CALIBRATION_V020.md](./_planning/MATCHER_CALIBRATION_V020.md) for per-pattern sample tables and false-positive audits):

| Pattern ID | Language | What it catches |
|---|---|---|
| `react-hook-missing-dep` | JS/TS | `useEffect` / `useCallback` / `useMemo` referencing state not listed in the dep array (matches on the canonical ESLint rule ID) |
| `fetch-missing-credentials` | JS/TS | Cross-origin authenticated fetch without `credentials: 'include'` (Chrome + Firefox phrasings) |
| `python-none-attribute-access` | Python | `AttributeError: 'NoneType' object has no attribute ...` + `TypeError: 'NoneType' object is not subscriptable` |
| `import-not-found-python` | Python | `ModuleNotFoundError` / `ImportError: cannot import name` |
| `missing-env-var` | Python | `os.environ['FOO']` KeyError on UPPER_SNAKE env-var keys |
| `rate-limit-no-backoff` | Python | HTTP 429 crashes — `RateLimitError`, `requests.HTTPError`, SDK-structured rate-limit responses |
| `async-fn-called-without-await` | Python | Un-awaited coroutine (`coroutine 'X' was never awaited`) |

See [_planning/LAUNCH_LIBRARY.md](./_planning/LAUNCH_LIBRARY.md) for the roadmap. A community pattern registry is under consideration for v0.3.

## Configuration

v0.2.0 adds two environment variables:

- `IMMUNIZE_DEBUG_HOOK=1` — writes every Claude Code hook payload to `.immunize/hook_payloads/<ts>-<session>.json` for offline inspection. Off by default.
- `IMMUNIZE_MIN_MATCH_CONFIDENCE=<float>` — raises the global floor above per-pattern thresholds (useful for CI strict-mode). Default 0.30 — per-pattern thresholds are authoritative.

## Contributing

Contributors are warmly welcomed — especially new patterns. See [CONTRIBUTING.md](./CONTRIBUTING.md) for dev setup and the pattern-authoring workflow, and [_planning/PATTERN_AUTHORING.md](./_planning/PATTERN_AUTHORING.md) for the "Ten Commandments" every pattern must satisfy.

Note on API keys: `immunize author-pattern` is an LLM-assisted drafting tool and lives behind the `[author]` extra (`pip install 'immunize[author]'`). **End users never need an API key** — the shipped pattern library is fully deterministic.

## Known limitations

- **POSIX-only in v0.2.** macOS and Linux are supported; Windows is planned for v0.3+. The CLI refuses to run on `win32` with a clear message.
- **Verification uses Python pytest for every pattern.** Python patterns run as genuine behavioral tests; JS/TS patterns verify via Python-based regex source scanning — a deliberate, documented compromise. Native runners (Jest, Go test, cargo test) remain a future goal.
- **Seven patterns is a starter set.** High-frequency AI-coding mistakes are the first priority; breadth comes with releases.
- **No community registry yet.** Patterns ship inside the package; new ones land via `pip install --upgrade immunize`. PRs adding new patterns are the recommended contribution path.

## License

Apache-2.0 — see [LICENSE](./LICENSE).
