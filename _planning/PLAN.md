# immunize — Build Plan

> **For Claude Code plan mode.** Read this entire document before proposing a plan. Also read `ARCHITECTURE.md` and `SPEC.md` in this folder. Do not start coding until the plan is approved.

## What we are building

`immunize` is a Python CLI tool that makes AI coding assistants (Claude Code, Cursor, Codex CLI, Gemini CLI) learn permanently from errors they cause. The biological metaphor: once your immune system sees a pathogen, it remembers. Once `immunize` sees an error, the AI never makes it again.

**The core loop:**

1. Developer is working with Claude Code (or plain terminal).
2. An error occurs — a failed bash command, a CORS error, a broken import, a wrong API call.
3. `immunize` detects the error (via Claude Code hook, or shell wrapper).
4. `immunize` sends the error + context to the Claude API for diagnosis.
5. `immunize` generates FOUR artifacts from the diagnosis:
   - `SKILL.md` (agentskills.io standard — works in Claude Code, Cursor, Codex, Gemini)
   - `.cursor/rules/*.mdc` (Cursor native rule format)
   - `.semgrep/*.yml` (linter rule, when error is a code pattern)
   - `tests/immunized/test_*.py` (pytest regression test — this is our moat)
6. `immunize` **verifies the test actually fails without the fix and passes with it** before accepting the artifact. Unverified artifacts are rejected.
7. All artifacts are written to the user's repo, where Claude Code and Cursor pick them up automatically next session.

## What makes this different from everything else

Read `ARCHITECTURE.md` section "Competitive landscape" for the full analysis. The short version:

- **Cursor Bugbot Learned Rules** — rules only steer Bugbot, not other tools. Cursor-only.
- **Claude Code auto memory** — Claude-only. No tests, no linter rules, no team sharing.
- **ClawHub `self-improving-agent`** — produces notes, not verified regression tests. Single-tool.
- **Sentry Seer / CodeRabbit** — detect + diagnose but don't emit persistent cross-tool rules.

**immunize is the only tool that produces verified, cross-tool, team-shareable immunity from runtime errors.** The regression test verification is the key differentiator. Do not cut it to save time — it is the product.

## Scope for v1 (2 weeks of evening work)

**IN SCOPE:**

- Local tier: single-developer immunity on one machine.
- Git team tier: commit generated artifacts, they propagate via `git pull`.
- Claude Code integration via PostToolUseFailure hook.
- Shell wrapper `immunize run <cmd>` for errors outside Claude Code.
- All four artifact types (SKILL.md, Cursor rule, Semgrep rule, pytest test).
- Pytest verification harness (mandatory gate — artifact rejected if test can't prove the fix works).
- SQLite-backed local history.
- CLI surface: `init`, `run`, `capture`, `list`, `remove`, `verify`.

**OUT OF SCOPE (v2 / v3):**

- Community registry (pip-install-an-antibody) — v3, only if v1 gets traction.
- Web dashboard — never (CLI-first product).
- VS Code / Cursor plugin UI — never (we emit files, the existing tools read them).
- MCP server — maybe v2, but the hook approach is simpler.
- Automatic error detection without hooks (shell daemon) — rabbit hole, skip.

## Build phases

### Phase 0 — Repo setup (30 min)

- Initialize git repo at `github.com/viditkbhatnagar/immunize`.
- Apache-2.0 license.
- Reserve `immunize` name on PyPI by publishing a `0.0.1` placeholder (see `PYPI_PUBLISHING.md`).
- Set up `pyproject.toml`, `.gitignore`, `README.md` stub.

### Phase 1 — Core pipeline (days 1–4)

Build the detect → diagnose → generate → verify → inject pipeline end to end, working from command line only (no hooks yet). Target: by end of phase 1, `immunize capture < error.log` produces all four artifacts with verified pytest.

Components (see `SPEC.md` for details):

- `src/immunize/cli.py` — Typer CLI skeleton.
- `src/immunize/capture.py` — reads error payload from stdin or CLI args.
- `src/immunize/diagnose.py` — Claude API call returning structured diagnosis.
- `src/immunize/generate/skill.py` — emits SKILL.md.
- `src/immunize/generate/cursor_rule.py` — emits `.cursor/rules/*.mdc`.
- `src/immunize/generate/semgrep.py` — emits Semgrep YAML (only for code-pattern errors).
- `src/immunize/generate/pytest_gen.py` — emits pytest file AND verification harness.
- `src/immunize/verify.py` — runs generated test in a subprocess, confirms fail-without-fix and pass-with-fix.
- `src/immunize/inject.py` — writes artifacts to correct paths in the user's project.
- `src/immunize/storage.py` — SQLite persistence of captured errors and their immunities.

### Phase 2 — Claude Code hook integration (days 5–6)

- `hooks/posttooluse_failure.sh` — reads JSON on stdin, extracts tool name + error, pipes to `immunize capture`.
- `immunize init` command — writes `.claude/settings.json` with the hook registered.
- Bundled skill at `src/immunize/skill_assets/immunize-manager/SKILL.md` — teaches Claude Code when to invoke immunize.

### Phase 3 — Shell wrapper + git team tier (days 7–8)

- `immunize run <cmd>` — executes command, captures non-zero exits, auto-triggers capture pipeline.
- Git team tier: document the convention that all immunize artifacts (`.claude/skills/`, `.cursor/rules/`, `.semgrep/`, `tests/immunized/`) are committed to the repo. Add `.immunize/` (local-only state) to `.gitignore` automatically on `init`.

### Phase 4 — Polish + launch (days 9–14)

- Full test suite (unit + integration) using `pytest-mock` for the Claude API calls.
- README with demo GIF at the top.
- Record 90-second launch demo (script in `SPEC.md`).
- PyPI publish (v0.1.0 real release).
- Dev.to / personal blog post.
- Hacker News Show HN on a Tuesday morning US time.

## Success criteria for v1

- `pip install immunize && immunize init` works on a fresh machine.
- A known CORS error, reproduced in a demo project, generates all four artifacts and the pytest passes verification.
- The same error, hit in a fresh Claude Code session on the same project, is avoided because the SKILL.md is in context.
- Total install-to-first-immunity time < 90 seconds.
- Public launch hits 500+ GitHub stars in 30 days.

## Non-goals

- Perfect diagnoses. The LLM will sometimes misdiagnose. That's what `immunize remove <id>` is for.
- Supporting every error class. Start with the common ones: HTTP errors, import errors, type errors, common Python/JS runtime errors. Semgrep rule generation can be skipped for non-code errors.
- Beating Cursor Bugbot at PR review. Different product, different layer.

## Risks and how we handle them

1. **Anthropic ships this natively in Claude Code.** Read ARCHITECTURE.md section "Platform risk." Move fast, own distribution, lean into cross-tool portability as the moat.
2. **Pytest verification is flaky.** Build the verifier to retry on transient failures, but hard-reject if the test itself is ill-formed. No "maybe it works" artifacts.
3. **LLM generates bad Semgrep rules.** Make Semgrep generation opt-in and clearly tagged as experimental.
4. **Hook breaks the user's Claude Code session.** Always fail open — if immunize crashes, exit 0, log to `.immunize/errors.log`, do not block the session.

## How to use this document with Claude Code plan mode

1. Open Claude Code in an empty directory where you want to build this.
2. Copy `PLAN.md`, `ARCHITECTURE.md`, `SPEC.md`, and `PYPI_PUBLISHING.md` into the directory.
3. Run Claude Code and enter plan mode.
4. Prompt: *"Read PLAN.md, ARCHITECTURE.md, and SPEC.md. Then propose a plan for Phase 0 only. Do not code until I approve."*
5. Review the plan, push back where needed, approve.
6. Let it execute Phase 0.
7. Repeat for each phase.

**Important:** Do not let Claude Code skip the pytest verification harness. If it proposes "we'll just generate the test and trust it's correct," reject the plan. The verifier is not optional.
