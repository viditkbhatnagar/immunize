# immunize — Component Specifications

> Detailed specs for each file. Claude Code should treat these as authoritative during implementation.

## Project layout

```
immunize/
├── pyproject.toml
├── README.md
├── LICENSE
├── .gitignore
├── src/
│   └── immunize/
│       ├── __init__.py            # exports __version__
│       ├── cli.py                 # Typer app + command handlers
│       ├── capture.py             # input parsing + SQLite insert
│       ├── diagnose.py            # Claude API call (structured)
│       ├── verify.py              # pytest verification harness
│       ├── inject.py              # file writing with atomic moves
│       ├── storage.py             # SQLite schema + queries
│       ├── models.py              # Pydantic data models
│       ├── config.py              # settings resolution
│       ├── generate/
│       │   ├── __init__.py
│       │   ├── skill.py           # SKILL.md generator
│       │   ├── cursor_rule.py     # .mdc generator
│       │   ├── semgrep.py         # YAML generator
│       │   └── pytest_gen.py      # pytest + fix snippet generator
│       └── skill_assets/
│           └── immunize-manager/
│               └── SKILL.md       # bundled skill shipped with package
├── hooks/
│   └── posttooluse_failure.sh     # Claude Code hook entry point
├── tests/
│   ├── test_capture.py
│   ├── test_diagnose.py
│   ├── test_generate.py
│   ├── test_verify.py
│   ├── test_inject.py
│   └── fixtures/
│       ├── cors_error.json
│       ├── import_error.json
│       └── type_error.json
└── docs/
    ├── quickstart.md
    └── demo_script.md
```

## CLI surface (`src/immunize/cli.py`)

Five commands only. No more in v1.

### `immunize init`

- Creates `.immunize/` directory and `state.db`.
- Writes/merges `.claude/settings.json` to register the PostToolUseFailure hook.
- Adds `.immunize/` to `.gitignore` (creates `.gitignore` if missing).
- Copies bundled `immunize-manager` skill into `~/.claude/skills/` (user-level, so it's available in all projects).
- Prints a friendly setup summary.

Flags:
- `--no-hook` — skip Claude Code hook registration (for users who only want shell wrapper).
- `--force` — overwrite existing `.immunize/` directory.

### `immunize run <cmd> [args...]`

- Executes the command via `subprocess.run` capturing stdout, stderr, exit code.
- Streams output to the terminal in real time (use Rich live display).
- If exit code is non-zero, builds a capture payload and calls the capture pipeline.
- Always exits with the same exit code as the wrapped command (so CI still fails correctly).

### `immunize capture`

- Reads a JSON payload from stdin (this is what hooks pipe in).
- Alternative: `--stdin-plain` reads raw stderr text and wraps it into a payload.
- Runs the full pipeline: diagnose → generate → verify → inject.
- Prints a compact Rich summary.
- Always exits 0, even on internal errors (we never want to block the parent session).

Flags:
- `--source {claude-code-hook,shell-wrapper,manual}` (default: `manual`).
- `--dry-run` — diagnose and generate but do not inject.

### `immunize list`

- Prints a table of all active immunities in the current project.
- Columns: ID, date, error class, slug, has_test, verified.

### `immunize remove <id>`

- Deletes the artifacts associated with the given immunity ID.
- Removes from SQLite.
- Prompts for confirmation unless `--yes`.

### `immunize verify [<id>]`

- Re-runs pytest verification on an existing immunity (or all, if no ID given).
- Useful for CI to ensure immunities still work after dependency updates.

## Data models (`src/immunize/models.py`)

Use Pydantic BaseModel for all. Example key models:

```python
class CapturePayload(BaseModel):
    source: Literal["claude-code-hook", "shell-wrapper", "manual"]
    tool_name: str | None = None
    command: str | None = None
    stdout: str = ""
    stderr: str
    exit_code: int
    cwd: str
    timestamp: datetime
    project_fingerprint: str
    session_id: str | None = None

class Diagnosis(BaseModel):
    root_cause: str
    error_class: Literal["cors", "import", "auth", "rate_limit",
                          "type_error", "null_ref", "config", "other"]
    is_generalizable: bool
    canonical_description: str
    fix_summary: str
    language: str
    slug: str  # validated as kebab-case
    semgrep_applicable: bool

class GeneratedArtifacts(BaseModel):
    skill_md: str
    cursor_rule: str
    semgrep_yaml: str | None
    pytest_code: str
    expected_fix_snippet: str
    error_repro_snippet: str  # code that reproduces the error (for verification)

class VerificationResult(BaseModel):
    passed: bool
    fails_without_fix: bool
    passes_with_fix: bool
    error_message: str | None = None
```

## Diagnose prompt (`src/immunize/diagnose.py`)

Single Claude API call. Use `claude-sonnet-4-6` by default.

System prompt (rough outline — refine during implementation):

```
You are a senior engineer diagnosing a runtime error an AI coding assistant produced.
You will receive the error's stdout, stderr, command, and working directory.
Produce a JSON response matching this exact schema:

{
  "root_cause": <one sentence, <= 30 words>,
  "error_class": <one of: cors, import, auth, rate_limit, type_error, null_ref, config, other>,
  "is_generalizable": <true if this pattern will recur, false if one-off>,
  "canonical_description": <30-50 words, suitable as SKILL.md description frontmatter>,
  "fix_summary": <what the developer should do, <= 40 words>,
  "language": <primary language of the affected code>,
  "slug": <kebab-case, <= 40 chars, filename-safe>,
  "semgrep_applicable": <true if the error is a code pattern detectable by Semgrep>
}

Rules:
- Return JSON only. No prose before or after.
- If is_generalizable is false, other fields can be best-effort.
- slug should be semantic (e.g., "cors-missing-credentials" not "error-1").
- semgrep_applicable is true ONLY for patterns in source code, not for env/config/network errors.
```

User prompt: the capture payload serialized as JSON, with stdout/stderr truncated to 4000 chars each.

Validate response with `Diagnosis.model_validate_json()`. Retry once on validation failure with a tighter "return valid JSON matching schema" reminder.

## Generator prompts

### `generate/skill.py`

Produces SKILL.md matching agentskills.io standard. Frontmatter must include `name`, `description`, and optionally `when_to_use`. Body should teach the AI how to avoid the specific error.

Output example for a CORS error:

```markdown
---
name: immunize-cors-missing-credentials
description: Prevents CORS errors when fetching authenticated endpoints by ensuring credentials: 'include' is set on fetch calls and the server responds with Access-Control-Allow-Credentials: true.
---

# Avoid CORS credential errors on authenticated fetches

When writing fetch() or axios calls to cross-origin authenticated endpoints:

1. Always set `credentials: 'include'` on fetch options (or `withCredentials: true` for axios).
2. Verify the server sends both `Access-Control-Allow-Credentials: true` AND a specific `Access-Control-Allow-Origin` (not `*`).
3. For preflight OPTIONS responses, include `Access-Control-Allow-Headers` covering any custom headers (e.g., Authorization).

Example:

```javascript
fetch('https://api.example.com/user', {
  credentials: 'include',
  headers: { 'Authorization': `Bearer ${token}` }
})
```

Reject any code that omits credentials handling when hitting an authenticated cross-origin endpoint.
```

### `generate/cursor_rule.py`

Emits `.mdc` file. Format:

```
---
description: <same description as SKILL.md>
globs: <relevant file patterns, e.g., "**/*.ts,**/*.tsx">
alwaysApply: false
---

<same body as SKILL.md, minus the markdown heading>
```

### `generate/semgrep.py`

Only called if `diagnosis.semgrep_applicable` is true.

```yaml
rules:
  - id: immunize-<slug>
    pattern: <Semgrep pattern>
    message: <canonical_description>
    severity: WARNING
    languages: [<language>]
```

The LLM generates the pattern. Keep this conservative — a too-broad pattern creates noise. Rule should have at least one literal token to anchor matching.

### `generate/pytest_gen.py`

Produces THREE outputs in one LLM call:

1. `pytest_code` — the test file.
2. `expected_fix_snippet` — a minimal code snippet that, when applied to a reproduction case, makes the test pass.
3. `error_repro_snippet` — the code that reproduces the original error (so verification can confirm the test fails without the fix).

The test should be self-contained — no external fixtures, minimal dependencies beyond stdlib + pytest + mocks. If the error involves a network call or environment variable, mock it.

## Verification harness (`src/immunize/verify.py`)

```
def verify(artifacts: GeneratedArtifacts) -> VerificationResult:
    with tempfile.TemporaryDirectory() as scratch:
        # Write error_repro_snippet + pytest_code, run pytest, expect FAIL.
        # Write expected_fix_snippet on top, run pytest again, expect PASS.
        # Use subprocess with timeout (default 30s).
        # Parse pytest exit codes: 0=pass, 1=fail, 2=error, 5=no tests.
        ...
```

Key behaviors:
- Use `subprocess.run` with `timeout` parameter.
- Use an isolated venv? No — too slow. Instead, rely on the developer's existing environment and document the assumption.
- If pytest returns exit 5 (no tests collected), treat as verification failure.
- On verification failure, retry diagnose + generate ONCE before giving up. Rejected artifacts go to `.immunize/rejected/` with a timestamped name.

## Injection (`src/immunize/inject.py`)

Atomic writes:
1. Write to `<target>.tmp`.
2. `os.replace(tmp, target)`.

Path handling:
- All paths resolved relative to `cwd` from the capture payload.
- Create parent directories with `mkdir(parents=True, exist_ok=True)`.

Collision handling:
- If an immunity with the same slug already exists, append a numeric suffix (`cors-missing-credentials-2`).
- Never silently overwrite.

## Storage (`src/immunize/storage.py`)

SQLite schema (use raw SQL, not an ORM — keeps dependencies thin):

```sql
CREATE TABLE IF NOT EXISTS errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payload_json TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    project_fingerprint TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS diagnoses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    error_id INTEGER NOT NULL REFERENCES errors(id),
    diagnosis_json TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    diagnosis_id INTEGER NOT NULL REFERENCES diagnoses(id),
    slug TEXT NOT NULL,
    skill_path TEXT,
    cursor_rule_path TEXT,
    semgrep_path TEXT,
    pytest_path TEXT,
    verified INTEGER NOT NULL,  -- 0 or 1
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rejections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    diagnosis_id INTEGER REFERENCES diagnoses(id),
    reason TEXT NOT NULL,
    rejected_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_artifacts_slug ON artifacts(slug);
```

## Bundled skill (`src/immunize/skill_assets/immunize-manager/SKILL.md`)

Install target: `~/.claude/skills/immunize-manager/SKILL.md` (copied during `immunize init`).

Purpose: teach Claude Code when to proactively invoke `immunize capture` beyond what the hook catches.

```markdown
---
name: immunize-manager
description: Use this skill when a command produces a runtime error and the user asks Claude to "remember this" or "make sure this never happens again." Also use when the user runs `immunize` commands manually and wants guidance on reviewing, testing, or removing immunities.
---

# immunize — error immunity manager

The user has installed `immunize` (github.com/viditkbhatnagar/immunize), a tool that turns runtime errors into permanent guardrails for AI coding assistants.

## When to invoke immunize

- User says "remember this error" / "never make this mistake again" / "immunize this": pipe the error output to `immunize capture --source manual`.
- User asks "what immunities do I have": run `immunize list`.
- User says "remove that rule" or similar: help them identify the ID from `immunize list`, then run `immunize remove <id>`.
- User asks "does this still work": run `immunize verify`.

## When NOT to invoke immunize

- The error is a one-off (user made a typo, network glitch, etc.). Let them fix manually.
- The user is actively debugging and hasn't asked for permanent prevention.
- You're inside a PostToolUseFailure hook run — that path is already automated.

## How artifacts are organized

After a successful capture, the user's project gains:
- `.claude/skills/immunize-<slug>/SKILL.md` — for Claude Code.
- `.cursor/rules/<slug>.mdc` — for Cursor.
- `.semgrep/<slug>.yml` — for CI linting (sometimes).
- `tests/immunized/test_<slug>.py` — verified regression test.

All four are committed to git — this is how team sharing works. When a teammate clones or pulls, their AI assistants automatically respect the new rules.
```

## Hook script (`hooks/posttooluse_failure.sh`)

```bash
#!/usr/bin/env bash
# PostToolUseFailure hook for Claude Code.
# Reads JSON from stdin, pipes to immunize capture.
# Always exits 0 so the user's Claude session is never blocked.

set +e  # never fail
immunize capture --source claude-code-hook 2>/dev/null || true
exit 0
```

## Tests (`tests/`)

Use `pytest-mock` to stub out the Anthropic SDK. Provide canned responses in `tests/fixtures/*.json`.

Minimum coverage for v1:
- Capture: handles malformed stdin gracefully, persists to SQLite.
- Diagnose: handles schema validation failure, retries once.
- Generate: each generator produces expected shape from a known diagnosis.
- Verify: correctly identifies fail-without-fix and pass-with-fix states.
- Inject: atomic writes, collision handling.
- CLI: each command handles --help, --version correctly.

## Demo script (`docs/demo_script.md`)

90 seconds, recorded with asciinema or OBS. Storyboard:

- **0:00–0:10** — Terminal. `npm run dev`. CORS error appears. Voice: "You've hit this error before, right?"
- **0:10–0:25** — Run `immunize capture < error.log`. Rich output shows: diagnosing → generating 4 artifacts → verifying pytest → ✓ immunity created. Voice: "immunize reads the error, diagnoses it, generates four guardrails, and verifies the regression test actually works."
- **0:25–0:40** — `cat .claude/skills/immunize-cors-*/SKILL.md` — show the generated skill. `cat tests/immunized/test_*.py` — show the verified test.
- **0:40–0:60** — Open Claude Code. Ask it to "fix the auth bug." Claude reads the new SKILL.md, writes code WITH credentials handling. Voice: "Fresh session. Claude never makes the mistake again."
- **0:60–0:80** — Open Cursor on the same project. Same scenario. Cursor reads `.cursor/rules/*.mdc`. Also avoids the mistake. Voice: "Same immunity, two tools. This is the cross-tool moment no other tool gives you."
- **0:80–0:90** — `git push`. "Teammate pulls. Their AI now has the immunity too. That's how team defenses work."

## Things Claude Code should NOT do during implementation

- Do not add LangChain / LangGraph. Direct Anthropic SDK only.
- Do not build a web UI or dashboard.
- Do not add a server component.
- Do not implement the community registry — that's v3.
- Do not skip the verification harness. It is the product differentiator.
- Do not use setuptools — use hatchling.
- Do not use argparse — use Typer.
- Do not write to files outside the project's working directory (except `~/.claude/skills/immunize-manager/` during init, which is explicit and user-consented).
