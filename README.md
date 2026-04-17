# immunize

> Your AI coding assistant learns permanently from the errors it causes — across Claude Code, Cursor, Codex CLI, and Gemini CLI.

**Status: under active development. Do not install yet.** The name `immunize==0.0.1` is reserved on PyPI as a placeholder. The first usable release is `v0.1.0`, coming soon.

## What it will do

- **Detect** runtime errors via a Claude Code `PostToolUseFailure` hook, a shell wrapper (`immunize run <cmd>`), or manual piping.
- **Diagnose** each error with a single Claude API call that returns a structured root cause.
- **Generate** four artifacts per error — a cross-tool skill (`SKILL.md`), a Cursor rule (`.mdc`), a Semgrep rule (when applicable), and a pytest regression test.
- **Verify** the pytest fails without the fix and passes with it. Unverified artifacts are rejected — this is the moat.
- **Inject** the verified artifacts into your repo, where Claude Code, Cursor, Codex, and Gemini CLI pick them up automatically next session. Commit them, and your whole team gains the same immunity via `git pull`.

## Install (when it's live)

Not yet. Once `v0.1.0` ships, it will be:

```bash
pip install immunize
immunize init
```

Until then, installing `immunize` from PyPI gets you the `0.0.1` placeholder with no functionality.

**POSIX only in v0.1.x.** macOS and Linux are supported. Windows support is tracked as a separate milestone — the CLI currently refuses to run on `win32` with a clear message.

## Known limitations

- **v0.1.x generates Python pytest files for all error classes**, including errors captured from TypeScript, JavaScript, Go, and other languages. Python errors get the strongest verification (real pytest subprocess proves fail-without-fix and pass-with-fix). Non-Python errors are verified via Python simulations of the error shape — a pattern-based sanity check. Native-language test generation (Jest, Go test, cargo test) is a v0.3 goal.
- **Injected pytest files are standalone proofs, not live regression guards over your real code.** Each test has the expected fix inlined at the top of the file so the test runs without capture-time scratch modules. Future phases will generate tests that import from your project's actual modules so they catch regressions in user-authored code.
- **`immunize verify` re-runs the injected pytest file in place.** On non-Python-language immunities, pattern-based tests still pass because the fix is inlined; they document the pattern rather than exercise your code. `immunize verify` exits non-zero if any immunity's test fails.

## Planning docs

The full design is in [_planning/](./_planning/):

- [_planning/PLAN.md](./_planning/PLAN.md) — build plan, phases, scope, success criteria
- [_planning/ARCHITECTURE.md](./_planning/ARCHITECTURE.md) — system design, data flow, competitive landscape
- [_planning/SPEC.md](./_planning/SPEC.md) — per-component specifications
- [_planning/PYPI_PUBLISHING.md](./_planning/PYPI_PUBLISHING.md) — release pipeline

## License

Apache-2.0 — see [LICENSE](./LICENSE).
