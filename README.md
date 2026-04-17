# immunize

> A curated pattern library that stops AI coding assistants from repeating common runtime errors. No API key. No LLM calls at runtime.

[![PyPI version](https://img.shields.io/pypi/v/immunize.svg)](https://pypi.org/project/immunize/)
[![Python versions](https://img.shields.io/pypi/pyversions/immunize.svg)](https://pypi.org/project/immunize/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](./LICENSE)
[![CI](https://github.com/viditkbhatnagar/immunize/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/viditkbhatnagar/immunize/actions/workflows/ci.yml)

- **Deterministic pattern library.** Every immunity is a pre-verified bundle of a Claude Code skill, a Cursor rule, and a pytest regression test.
- **No API key required.** Matching and verification are pure regex + subprocess; the Python runtime never calls an LLM.
- **Works where you already are.** Ships a skill for Claude Code and rules for Cursor; commit the injected artifacts and your whole team picks them up on `git pull`.

## 30-second tour

```bash
pip install immunize
cd your-project
immunize install-skill        # drops .claude/skills/immunize-manager/SKILL.md

# Pipe any failing command's output in — directly, from your own shell
# wrapper, or from the bundled Claude Code skill.
cat <<'EOF' | immunize capture --source manual
{
  "source": "manual",
  "stderr": "CORS policy: No 'Access-Control-Allow-Credentials' header",
  "exit_code": 1,
  "cwd": "/abs/path/to/your-project",
  "timestamp": "2026-04-18T00:00:00Z",
  "project_fingerprint": "your-project"
}
EOF
```

One line of JSON comes back on stdout. On a match you'll see `outcome: matched_and_verified` and three new files in your repo:

```
.claude/skills/immunize-<pattern-id>/SKILL.md
.cursor/rules/<pattern-id>.mdc
tests/immunized/<pattern-id>/test_template.py
```

Commit them. Next Claude Code or Cursor session automatically picks the guardrails up.

## Why?

AI coding assistants repeat the same mistakes every session. You fix the stale-closure bug in your `useEffect` on Monday, and by Wednesday Claude has written the same bug in a different file. The model has no durable memory of what you corrected.

The existing answers each fall short in one way:

- **Claude Code memory / Cursor rules** are single-tool and per-user. They're untested — there's no build-time check that the rule actually prevents the error it claims to prevent — and they're hard to share with a team.
- **Telling the model "don't do that again"** works for one session. It doesn't survive a `/clear` or a new teammate joining.
- **Linters and type checkers** catch the patterns their authors thought of, not the ones that AI models specifically over-produce.

`immunize` is a different bet: a small, curated, *verified* library of patterns covering the mistakes that matter. Each pattern ships with a pytest that proves the fix works and the bug reproduces without it. When you capture an error that matches, the artifacts land in your repo as committed code — durable, team-shared, and cross-tool.

## How it works

Three layers, deliberately thin:

1. **Trigger.** Any failing command's output. The bundled Claude Code skill pipes it for you automatically; a shell wrapper or a manual paste works just as well.
2. **Matcher.** Pure regex + error-class heuristics. Scans the bundled patterns (and any `patterns_local/` you've authored) and returns a ranked `MatchResult`. No network.
3. **Verify + inject.** The matching pattern's pytest runs in a subprocess against a scratch project; if it passes, three artifacts are copied atomically into your repo.

```
failing command's stderr
        │
        ▼
  immunize capture  ─►  matcher  ─►  verify (pytest)  ─►  inject
                          │               │                  │
                          ▼               ▼                  ▼
                 src/immunize/      subprocess on       .claude/skills/
                 patterns/          a tempdir           .cursor/rules/
                 patterns_local/                        tests/immunized/
```

After `immunize install-skill`, the flow is automatic from inside Claude Code: the skill watches for failing bash tool calls, pipes the payload to `immunize capture`, reads the single-line JSON response, and tells you in plain English what it added to your repo.

## What's bundled in v0.1

Seven patterns, chosen to cover the most common AI-coding runtime errors across Python, JavaScript, and TypeScript:

| Pattern ID | Language | What it catches |
|---|---|---|
| `react-hook-missing-dep` | JS/TS | `useEffect` / `useCallback` referencing state not listed in the dep array |
| `fetch-missing-credentials` | JS/TS | Cross-origin authenticated fetch without `credentials: 'include'` |
| `python-none-attribute-access` | Python | `AttributeError: 'NoneType' object has no attribute ...` |
| `import-not-found-python` | Python | `ModuleNotFoundError` from hallucinated or miswritten imports |
| `missing-env-var` | Python | `os.environ['FOO']` used without a safe-default read |
| `rate-limit-no-backoff` | Python | API loops that crash on the first 429 — no exponential backoff |
| `async-fn-called-without-await` | Python | Un-awaited coroutine used as if it were the resolved value |

See [_planning/LAUNCH_LIBRARY.md](./_planning/LAUNCH_LIBRARY.md) for the roadmap. **v0.2 is expected to add**: native-language test runners (Jest, Go test), more bundled patterns, and local learning that drafts new patterns from the user's own Claude Code session at zero incremental cost. A community pattern registry is under consideration for v0.3.

## Contributing

Contributors are warmly welcomed — especially new patterns. See [CONTRIBUTING.md](./CONTRIBUTING.md) for dev setup and the pattern-authoring workflow, and [_planning/PATTERN_AUTHORING.md](./_planning/PATTERN_AUTHORING.md) for the "Ten Commandments" every pattern must satisfy.

Note on API keys: `immunize author-pattern` is an LLM-assisted drafting tool and requires `ANTHROPIC_API_KEY` for contributors who use it. **End users never need an API key** — the shipped pattern library is fully deterministic.

## Known limitations

- **POSIX-only in v0.1.** macOS and Linux are supported; Windows is planned for v0.2+. The CLI refuses to run on `win32` with a clear message.
- **Verification uses Python pytest for every pattern.** Python patterns run as genuine behavioral tests; JS/TS patterns verify via Python-based regex source scanning — a deliberate, documented compromise. Native runners (Jest, Go test, cargo test) are a v0.3 goal.
- **Seven patterns is a starter set.** High-frequency AI-coding mistakes are the first priority; breadth comes with releases.
- **No community registry yet.** Patterns ship inside the package; new ones land via `pip install --upgrade immunize`. PRs adding new patterns are the recommended contribution path.

## License

Apache-2.0 — see [LICENSE](./LICENSE).
