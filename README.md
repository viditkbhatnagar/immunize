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

## Planning docs

The full design is in [_planning/](./_planning/):

- [_planning/PLAN.md](./_planning/PLAN.md) — build plan, phases, scope, success criteria
- [_planning/ARCHITECTURE.md](./_planning/ARCHITECTURE.md) — system design, data flow, competitive landscape
- [_planning/SPEC.md](./_planning/SPEC.md) — per-component specifications
- [_planning/PYPI_PUBLISHING.md](./_planning/PYPI_PUBLISHING.md) — release pipeline

## License

Apache-2.0 — see [LICENSE](./LICENSE).
