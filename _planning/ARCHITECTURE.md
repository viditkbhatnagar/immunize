# immunize — Architecture

## System overview

Three conceptual layers:

```
┌─────────────────────────────────────────────────────────┐
│  LAYER 3: Generated artifacts (the "antibodies")        │
│  .claude/skills/immunize-<slug>/SKILL.md                │
│  .cursor/rules/<slug>.mdc                               │
│  .semgrep/<slug>.yml                                    │
│  tests/immunized/test_<slug>.py                         │
│  → Live in user's repo, committed to git                │
└─────────────────────────────────────────────────────────┘
                       ▲ produces
┌─────────────────────────────────────────────────────────┐
│  LAYER 2: Python package (the factory)                  │
│  immunize CLI (Typer) → capture → diagnose → generate   │
│                      → verify → inject                  │
│  State: SQLite at .immunize/state.db                    │
│  → One install per developer machine                    │
└─────────────────────────────────────────────────────────┘
                       ▲ invoked by
┌─────────────────────────────────────────────────────────┐
│  LAYER 1: Triggers (the sensors)                        │
│  a) Claude Code PostToolUseFailure hook                 │
│  b) Bundled skill SKILL.md (teaches Claude when to run) │
│  c) Shell wrapper: immunize run <cmd>                   │
│  d) Manual CLI: immunize capture < error.log            │
└─────────────────────────────────────────────────────────┘
```

## Data flow for a single error

```
┌──────────┐      ┌──────────┐      ┌───────────┐     ┌──────────┐
│  Error   │─────▶│ capture  │─────▶│ diagnose  │────▶│ generate │
│ occurs   │      │ (stdin)  │      │ (Claude)  │     │ (4 files)│
└──────────┘      └──────────┘      └───────────┘     └────┬─────┘
                                                           │
                                                           ▼
                  ┌──────────┐      ┌──────────┐     ┌──────────┐
                  │   git    │◀─────│  inject  │◀────│  verify  │
                  │  (user)  │      │ (write)  │     │ (pytest) │
                  └──────────┘      └──────────┘     └────┬─────┘
                                                          │
                                                    reject on fail
```

### Step-by-step

1. **Capture** — a JSON payload enters our system. Shape:
   ```json
   {
     "source": "claude-code-hook" | "shell-wrapper" | "manual",
     "tool_name": "Bash" | "Edit" | "Write" | null,
     "command": "npm run dev",
     "stdout": "...",
     "stderr": "...",
     "exit_code": 1,
     "cwd": "/path/to/project",
     "timestamp": "2026-04-17T12:34:56Z",
     "project_fingerprint": "sha256 of cwd",
     "session_id": "optional claude session id"
   }
   ```
   This is persisted to SQLite and passed to diagnose.

2. **Diagnose** — single Claude API call with structured output. Prompt (see SPEC.md for full text) asks for:
   ```json
   {
     "root_cause": "one-sentence explanation",
     "error_class": "cors" | "import" | "auth" | "rate_limit" | "type_error" | "null_ref" | "other",
     "is_generalizable": true,
     "canonical_description": "description suitable for SKILL.md frontmatter",
     "fix_summary": "what the user should do",
     "language": "python" | "typescript" | "javascript" | "bash" | ...,
     "slug": "kebab-case-slug-for-filenames",
     "semgrep_applicable": true | false
   }
   ```
   If `is_generalizable: false`, we skip artifact generation and just log to history.

3. **Generate** — four parallel calls. Each is a separate Claude API call with a tight single-purpose prompt:
   - `generate/skill.py` — emits `SKILL.md` content as a string.
   - `generate/cursor_rule.py` — emits `.mdc` content.
   - `generate/semgrep.py` — emits YAML (only called if `semgrep_applicable`).
   - `generate/pytest_gen.py` — emits BOTH the test file AND an "expected fix" code snippet.

4. **Verify** — the critical step. For the pytest artifact:
   - Create a scratch directory.
   - Apply the "unfixed" state (which is the original error-producing code, if available, else a minimal repro the LLM generates).
   - Run pytest. Confirm the test FAILS.
   - Apply the "fix" snippet.
   - Run pytest again. Confirm the test PASSES.
   - If either check is wrong, the artifact is rejected. Retry the LLM call once. If still wrong, abandon — log to `.immunize/rejected/`.

5. **Inject** — write accepted artifacts to the user's project:
   - SKILL.md → `.claude/skills/immunize-<slug>/SKILL.md`
   - Cursor rule → `.cursor/rules/<slug>.mdc`
   - Semgrep → `.semgrep/<slug>.yml`
   - Pytest → `tests/immunized/test_<slug>.py`
   - Also write a summary entry to `.immunize/manifest.json` listing all active immunities.

6. **Git team tier** — nothing to do in code. The convention is simply that all four artifact directories are committed to the user's repo. `immunize init` adds `.immunize/` to `.gitignore` (local state stays local) but does NOT touch the four artifact directories (they should be committed).

## Storage

- **SQLite** at `.immunize/state.db` inside each project (local state, not committed).
  - Tables: `errors`, `diagnoses`, `artifacts`, `verifications`, `rejections`.
- **Artifact files** in their canonical directories (committed to git).
- **Manifest** at `.immunize/manifest.json` (local, regenerable from artifact files — used for fast `immunize list`).

## Configuration

Settings resolution order (highest to lowest priority):
1. CLI flags (e.g., `--model claude-sonnet-4-6`)
2. Environment variables (e.g., `IMMUNIZE_MODEL`)
3. `.immunize/config.toml` in project
4. `~/.config/immunize/config.toml` in user home
5. Built-in defaults

Key config values:
- `model`: default `claude-sonnet-4-6` (good cost/quality balance for generation)
- `api_key`: from `ANTHROPIC_API_KEY` env var only (never written to config files)
- `generate.semgrep`: `true` | `false` (default false for v1 — opt-in)
- `verify.timeout_seconds`: default 30
- `verify.retry_count`: default 1

## Claude Code hook integration

`immunize init` writes to `.claude/settings.json`:

```json
{
  "hooks": {
    "PostToolUseFailure": [
      {
        "matcher": "Bash|Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "immunize capture --source claude-code-hook"
          }
        ]
      }
    ]
  }
}
```

The hook runs `immunize capture` which reads JSON from stdin (what Claude Code pipes in) and triggers the full pipeline asynchronously. **Always exit 0 from the hook** — we never block the Claude session. If immunize crashes, the user's workflow continues uninterrupted.

Bundled skill at `~/.claude/skills/immunize-manager/SKILL.md` also teaches Claude Code about immunize invocations for when the hook alone isn't enough (e.g., errors caught but not classified by the tool system).

## Competitive landscape (for reference)

| Tool | Detect | Diagnose | SKILL.md | Cursor rule | Linter rule | Test | Cross-tool | Team share |
|---|---|---|---|---|---|---|---|---|
| Cursor Bugbot | ✓ | ✓ | ✗ | partial | ✗ | ✗ | ✗ | ✓ |
| Claude auto memory | ✓ | partial | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| ClawHub self-improving-agent | ✓ | ✓ | ✓ | partial | ✗ | ✗ | partial | ✗ |
| Sentry Seer | ✓ | ✓ | consumes | partial | ✗ | partial | ✗ | partial |
| CodeRabbit | ✓ | partial | ✗ | partial | partial | partial | ✗ | ✓ |
| Semgrep Assistant | ✓ | partial | ✗ | ✗ | ✓ | ✗ | ✗ | ✓ |
| **immunize** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ (verified) | ✓ | ✓ |

## Platform risk

Anthropic's Dec 2025 engineering post explicitly names our product surface: "we hope to enable agents to create, edit, and evaluate Skills on their own, letting them codify their own patterns of behavior into reusable capabilities." The KAIROS leak (March 2026) suggests an always-on learning daemon is in flight.

**Probability Anthropic ships first-party error-to-skill distillation in Claude Code in next 12 months: >80%.**

Our defense: first parties will not emit cross-tool artifacts (they'll stay inside Claude Code). First parties won't emit verified regression tests. First parties won't support team-shared memory across Claude Code + Cursor + Codex. Lean into those three as the moat.

## Tech stack rationale

- **Python 3.10+**: broadest compatibility, native on most dev machines.
- **Typer**: modern CLI, auto-help, plays well with `rich` for nice output.
- **Anthropic SDK direct**: no LangChain. A 4-call pipeline doesn't need a framework, and simplicity is a hiring-manager signal.
- **Pydantic for structured output**: use `client.messages.create(...).content` with JSON schema validation via Pydantic models.
- **SQLite**: zero-config local persistence.
- **hatchling**: modern, simple build backend (no setuptools boilerplate).

## What we explicitly are NOT building

- MCP server (hooks do the job more reliably).
- Web dashboard (CLI-first; if traction demands it, it's a v2 decision).
- VS Code / Cursor extension (existing tools already read the files we produce).
- Always-on daemon that watches all terminals (rabbit hole; privacy concerns).
- Community package registry (v3, only if v1/v2 land).
