# immunize — Architecture 1B (Pattern Library + Local Learning)

## The three layers, redrawn

```
┌──────────────────────────────────────────────────────────────┐
│  LAYER 3: Generated artifacts in the user's repo             │
│  .claude/skills/immunize-<slug>/SKILL.md                     │
│  .cursor/rules/<slug>.mdc                                    │
│  tests/immunized/test_<slug>.py                              │
│  → These files ARE the immunity. Committed to git.           │
└──────────────────────────────────────────────────────────────┘
                         ▲ injected by
┌──────────────────────────────────────────────────────────────┐
│  LAYER 2: immunize Python package                            │
│                                                              │
│  capture.py → matcher.py → verify.py → inject.py             │
│                  │                                           │
│                  ├─ bundled patterns (ships with package)    │
│                  └─ local patterns (user's .immunize/)       │
│                                                              │
│  If matcher returns no match AND Claude Code is the caller,  │
│  the bundled skill takes over authoring.                     │
└──────────────────────────────────────────────────────────────┘
                         ▲ invoked by
┌──────────────────────────────────────────────────────────────┐
│  LAYER 1: Triggers                                           │
│                                                              │
│  • Claude Code PostToolUseFailure hook                       │
│  • immunize-manager bundled SKILL.md (in-session authoring)  │
│  • Shell wrapper: immunize run <cmd>  (Phase 3)              │
│  • Manual CLI: immunize capture < error.log                  │
└──────────────────────────────────────────────────────────────┘
```

## The fundamental change

The old architecture had ONE path: capture → diagnose (LLM) → generate (LLM) → verify → inject.

The new architecture has TWO paths that branch at the matcher:

```
capture
  │
  ▼
matcher ── match found ──▶ verify ──▶ inject ──▶ done (fast, free, offline)
  │
  └── no match ──▶ (IF caller is Claude Code session)
                     │
                     ▼
                   bundled skill tells Claude to draft
                     │
                     ▼
                   Claude writes draft via tool call
                     │
                     ▼
                   authoring/session_author.py receives draft
                     │
                     ▼
                   verify ──▶ save to local library ──▶ inject ──▶ done
                                                           (no extra API cost)
```

The Python package NEVER initiates a Claude API call. When drafting happens, it happens inside the user's existing Claude Code session via the skill mechanism. Cost stays on the user's existing Claude Code usage, which they already have.

## The pattern — anatomy

Each bundled pattern lives at `src/immunize/patterns/<slug>/` and contains:

```
src/immunize/patterns/cors-missing-credentials/
├── pattern.yaml          # match rules + metadata
├── SKILL.md              # copied into user's .claude/skills/
├── cursor_rule.mdc       # copied into user's .cursor/rules/
├── semgrep.yml           # optional; copied into .semgrep/
├── test_template.py      # pytest that verifies the immunity works
└── fixtures/
    ├── repro.py          # code that reproduces the bug
    └── fix.py            # the fix snippet
```

Local patterns live at `.immunize/patterns_local/<slug>/` in the user's project with the identical structure. They're added to `.gitignore` by default (user can un-ignore to share with their team).

### pattern.yaml format

```yaml
id: cors-missing-credentials
version: 1
schema_version: 1              # for future forward-compat
author: "@viditkbhatnagar"
origin: bundled                # "bundled" | "local" | "community"
error_class: cors
languages: [javascript, typescript]
description: "CORS credential header missing on authenticated fetch"

# Matching rules — ALL must be satisfied at the given confidence threshold
match:
  stderr_patterns:             # regex alternatives — ANY match scores
    - "Access-Control-Allow-Credentials"
    - "CORS policy.*credentials"
    - "credentials flag is 'include'"
  stdout_patterns: []
  error_class_hint: cors       # if diagnose heuristic also says "cors", +confidence
  min_confidence: 0.70         # below this, don't apply

# Verification — how we prove the pattern's pytest works
verification:
  pytest_relative_path: test_template.py
  expected_fail_without_fix: true
  expected_pass_with_fix: true
  timeout_seconds: 30
```

## matcher.py — the new core module

This is the module that replaces `diagnose.py` and most of `generate/`. It does ALL the work the LLM used to do, but deterministically.

```python
from pathlib import Path
from immunize.models import CapturePayload, MatchResult, Pattern

BUNDLED_PATTERNS_DIR = Path(__file__).parent / "patterns"

def load_patterns(local_dir: Path | None = None) -> list[Pattern]:
    """Load bundled + local patterns from disk. Parses pattern.yaml for each."""

def match(payload: CapturePayload, patterns: list[Pattern]) -> list[MatchResult]:
    """
    Score each pattern against the payload. Returns matches with confidence >= threshold,
    sorted by confidence descending.
    """

def score_pattern(payload: CapturePayload, pattern: Pattern) -> MatchResult:
    """
    Confidence scoring. Rough algorithm:
    - Start at 0.0
    - +0.3 for each stderr_pattern regex match (up to 0.6 total)
    - +0.2 for each stdout_pattern match (up to 0.4)
    - +0.15 if error_class_hint matches lightweight heuristic (keywords in stderr)
    - +0.1 if language hint from the stderr matches pattern.languages
    - Cap at 1.0
    """
```

The scorer is intentionally simple. When we find we need more sophistication (a year from now, maybe), we can add weighted features or a tiny classifier. For v0.1, boolean regex + heuristics is enough.

## Error class heuristics (lightweight, no LLM)

`matcher.py` ships with a tiny rule-based heuristic that guesses the error class from stderr. This is NOT diagnosing; it's just a hint to narrow matching:

```python
ERROR_CLASS_HINTS: dict[str, list[str]] = {
    "cors": ["CORS", "Access-Control-Allow", "preflight"],
    "import": ["ModuleNotFoundError", "ImportError", "Cannot find module"],
    "auth": ["401", "403", "Unauthorized", "Forbidden", "authentication"],
    "rate_limit": ["429", "rate limit", "Too Many Requests"],
    "type_error": ["TypeError", "is not a function", "is not iterable"],
    "null_ref": ["NoneType", "Cannot read prop", "undefined is not"],
    "config": ["env var", "environment variable", "not set", "tsconfig"],
    "network": ["ECONNREFUSED", "ENOTFOUND", "ETIMEDOUT", "getaddrinfo"],
}

def guess_error_class(stderr: str) -> str:
    """Returns the class whose keywords have the most stderr hits, or 'other'."""
```

Cheap, explainable, no magic. Good enough for match narrowing.

## Config changes

`config.py` after the pivot is much smaller. Remove everything Claude-related:

```python
# REMOVED
# def build_client(settings) -> anthropic.Anthropic: ...

# KEPT
@dataclass
class Settings:
    verify_timeout_seconds: int = 30
    verify_retry_count: int = 1
    project_dir: Path
    state_db_path: Path
    min_match_confidence: float = 0.70   # NEW
    local_patterns_dir: Path              # NEW — defaults to project_dir/.immunize/patterns_local
```

## Models changes

Remove: `Diagnosis`, `GeneratedArtifacts`
Keep: `CapturePayload`, `VerificationResult`, `Settings`, `InjectedPaths`
Add:

```python
class MatchRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stderr_patterns: list[str] = []
    stdout_patterns: list[str] = []
    error_class_hint: str | None = None
    min_confidence: float = 0.70

class Verification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pytest_relative_path: str
    expected_fail_without_fix: bool = True
    expected_pass_with_fix: bool = True
    timeout_seconds: int = 30

class Pattern(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    version: int
    schema_version: int = 1
    author: str
    origin: Literal["bundled", "local", "community"]
    error_class: str
    languages: list[str]
    description: str
    match: MatchRules
    verification: Verification
    # NOT in YAML — populated at load time
    directory: Path | None = None

class MatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pattern: Pattern
    confidence: float
    matched_stderr_patterns: list[str]
    matched_stdout_patterns: list[str]
    # Confidence breakdown for debuggability
    score_breakdown: dict[str, float]

class AuthoringDraft(BaseModel):
    """Used only in local-learning path via session_author.py."""
    model_config = ConfigDict(extra="forbid")
    proposed_slug: str
    skill_md: str
    cursor_rule_mdc: str
    pytest_code: str
    expected_fix_snippet: str
    error_repro_snippet: str
    error_class: str
    languages: list[str]
    description: str
```

## The bundled skill — now doing more work

`src/immunize/skill_assets/immunize-manager/SKILL.md` becomes the critical piece of the local-learning path. It's both documentation for Claude Code AND the mechanism that lets Claude author patterns inside a user's session.

```markdown
---
name: immunize-manager
description: Use when a runtime error occurs during a Claude Code session and the user wants to prevent recurrence. Also use when helping the user author, review, or remove error patterns for the immunize tool.
---

# immunize-manager

The user has installed `immunize` — a pattern library that turns runtime errors into verified guardrails for AI coding assistants.

## Workflow when an error occurs

1. Extract the error's stdout, stderr, command, exit code, and cwd.
2. Call the tool `immunize capture --source claude-code-session`, piping the payload as JSON on stdin.
3. Read the JSON response from the tool:
   - If `"matched": true`, the tool already applied a bundled pattern. Tell the user what was immunized.
   - If `"matched": false` AND `"can_author_locally": true`, the tool is inviting you to draft a new local pattern. Proceed to the authoring workflow below.
   - If `"matched": false` AND `"can_author_locally": false`, the error was captured but no pattern fits. Tell the user and stop.

## Authoring workflow (only when tool returns can_author_locally: true)

You're going to draft a new local pattern for this user's project. This costs nothing extra — you're already in this Claude Code session, so drafting stays within the session the user is already paying for.

**Ask the user's consent first**: "I can draft a local pattern so this error never recurs in future sessions. Want me to proceed?"

If yes:

1. Analyze the error (root cause, language, error class).
2. Draft the following four strings:
   - `skill_md`: A SKILL.md body (no frontmatter — the tool adds frontmatter deterministically).
   - `cursor_rule_mdc`: A Cursor rule body (same relationship to frontmatter).
   - `pytest_code`: A self-contained pytest that fails without the fix and passes with it.
   - `expected_fix_snippet` / `error_repro_snippet`: Minimal code showing the bug vs. the fix.
3. Call `immunize author-local-from-session` with a JSON payload containing all four.
4. The tool runs the pytest verifier in a subprocess and reports back:
   - On verification success, the pattern is saved locally and artifacts are injected.
   - On failure, the tool returns diagnostic output. You get one retry to fix the draft.
5. Tell the user the outcome.

## Rules for drafted patterns

- The pytest test must call the module the same way a production consumer would. Don't override internal parameters that the fix is supposed to change.
- error_repro_snippet and expected_fix_snippet must differ in behavior when invoked identically.
- Tests must be self-contained — stdlib + pytest + unittest.mock only, no network, use tmp_path for files.

## What NOT to invoke immunize for

- One-off errors (typo, network blip). Let the user fix manually.
- Errors already solved by a bundled pattern (the tool handles this automatically).
```

This skill is the trick. It makes Claude Code *itself* do the drafting work, inside the user's session, spending the user's existing session budget. The Python package is never the one making the API call.

## The authoring path for contributors (YOU, not users)

There's a second authoring path for when you or a community contributor wants to add a NEW bundled pattern. This one DOES call Claude directly, from a CLI tool you run on your own machine:

```bash
# You're writing a new pattern based on an error fixture
$ immunize author-pattern --from-error tests/fixtures/new_error.json --output src/immunize/patterns/

[1/5] Analyzing error with Claude ($0.003 of your Anthropic key)...
[2/5] Proposing slug: react-hook-missing-dep ...
[3/5] Drafting SKILL.md, Cursor rule, pytest, fix snippet...
[4/5] Running verification in sandbox...
      ✓ Test fails without fix
      ✓ Test passes with fix
[5/5] Writing pattern to src/immunize/patterns/react-hook-missing-dep/

Review the draft, edit as needed, then:
  git add src/immunize/patterns/react-hook-missing-dep/
  git commit -m "Add pattern: react-hook-missing-dep"
```

This CLI requires an `ANTHROPIC_API_KEY` — but it's explicitly a contributor tool, clearly documented as such, and completely optional for end users. Contributors opt in by running this command; users never see it.

## Storage changes

SQLite schema barely changes. Add one column to `artifacts`:

```sql
ALTER TABLE artifacts ADD COLUMN pattern_id TEXT;
ALTER TABLE artifacts ADD COLUMN pattern_origin TEXT;  -- 'bundled' | 'local' | 'community'
```

Now `immunize list` can show which pattern produced which immunity.

## Verification gate at pattern-authoring time vs. user-runtime

Two distinct verification moments:

**Authoring-time** (runs once, on the contributor's machine or in `scripts/pattern_lint.py` on CI):
- Reads `test_template.py` + `fixtures/repro.py` + `fixtures/fix.py`.
- Subprocess: apply repro, run pytest, expect FAIL.
- Subprocess: apply fix over repro, run pytest, expect PASS.
- If either fails, the pattern is rejected. CI blocks the PR.

**User-runtime** (runs when a pattern is first applied to a user's project):
- Re-runs the same verification in the user's actual environment.
- Catches cases where the pattern works on the contributor's machine but fails in the user's because of environment differences (different pytest version, missing optional dep, etc.).
- On failure, the pattern is NOT applied and the user sees a clear message.

This double-gating is why "verified" is meaningful. It's not just "we wrote a test" — it's "we proved the test works in BOTH the controlled authoring environment AND the user's real environment."

## Flow diagrams

### Inject-time fixture rewrite (the "fix-into-repro" swap)

Each bundled pattern ships two fixture files:

- `fixtures/repro.<ext>` — the BUGGY example. `test_template.py` is authored
  to **FAIL** when run against this file. `scripts/pattern_lint.py` relies
  on that failure for the first leg of its FAIL→PASS→FAIL authoring-time
  dual-run.
- `fixtures/fix.<ext>` — the FIXED example. Same API surface, correct
  behavior. Swapping its bytes over `repro.<ext>` makes the test PASS.

At **inject time**, `inject.py` writes the `fix.<ext>` bytes into the
user's `tests/immunized/<slug>/fixtures/repro.<ext>` slot. `test_template.py`
resolves its fixture via `Path(__file__).parent / "fixtures" / "repro.<ext>"`
— the filename must stay as authored, but the contents need to be the
correct example so the injected test passes in the user's pytest run.

Result: a user who runs `pytest tests/immunized/` after injection gets a
green guardrail test. If an AI assistant later rewrites the fix bytes
with buggy bytes (regression), the test fails and catches it. The
pattern's source tree under `src/immunize/patterns/` is untouched —
`pattern_lint.py` still has the original repro bytes available for its
dual-run.

The rewrite only fires when a pattern ships exactly one `repro.*` and one
`fix.*` at the top of `fixtures/`. Minimal patterns (no repro+fix pair)
fall through to a verbatim copy.

### User-runtime happy path (bundled match)

```
User hits CORS error
        │
        ▼
PostToolUseFailure hook fires
        │
        ▼
immunize capture <payload
        │
        ▼
matcher loads bundled + local patterns
        │
        ▼
matcher scores all patterns; top match = cors-missing-credentials @ 0.92
        │
        ▼
verify runs test_template.py in subprocess → passes
        │
        ▼
inject writes 3 files into user's project
        │
        ▼
Rich summary: "✓ Immunized against cors-missing-credentials"
        │
        ▼
exit 0

Total cost: $0. Total time: < 1 second.
```

### User-runtime unknown-error path (local learning)

```
User hits a novel error Claude Code made
        │
        ▼
PostToolUseFailure hook fires
        │
        ▼
immunize capture <payload
        │
        ▼
matcher: no pattern above confidence threshold
        │
        ▼
response: {matched: false, can_author_locally: true}
        │
        ▼
Claude Code reads response, sees can_author_locally=true
        │
        ▼
Claude Code (guided by the immunize-manager skill) asks user: "Want me to draft a local pattern?"
        │
        ▼ (user says yes)
Claude Code drafts skill_md / cursor_rule / pytest / fix / repro IN ITS OWN SESSION
        │
        ▼
Claude Code calls: immunize author-local-from-session <draft>
        │
        ▼
session_author.py receives draft → writes to temp → runs verification in subprocess
        │
        ▼
If verified: pattern saved to .immunize/patterns_local/<slug>/, injection runs
        │
        ▼
If not verified: tool returns failure diagnostics, Claude Code gets ONE retry to fix the draft
        │
        ▼
Rich summary: "✓ Learned new local pattern: <slug>" OR "✗ Could not verify; dumped to .immunize/rejected/"

Total cost to user: $0 incremental (they were already in the Claude Code session).
```

## Why this architecture is actually cleaner

1. **Separation of concerns.** Python handles: matching, verification, file IO, state. Claude handles: drafting (at authoring time). The two never mix at runtime for end users.

2. **The bundled library is the product.** The package is a delivery mechanism. Users install `immunize` for the patterns, not for the Python code — which is exactly how people install ESLint for the rules, not for the parser.

3. **Local learning costs nothing because it piggybacks.** The genius move is that the user's Claude Code session is already paid for. By making the bundled skill do the drafting work in-session, we get LLM-quality pattern authoring without billing the user twice.

4. **Community patterns become trivial.** Once v0.1 ships with 15–20 patterns, anyone can contribute a pattern via PR using the `immunize author-pattern` CLI. They spend $0.01 of their own Anthropic credit, submit a PR, you review, merge, ship. Network effect without a backend.

## What Claude Code should do when reading this

- Understand the two paths (bundled match vs. local authoring via skill).
- Understand that the Python package NEVER imports `anthropic` outside `authoring/cli_author.py` and `scripts/pattern_lint.py`.
- Understand that the pivot means deleting real code, not just adding new code. If it finds itself preserving `diagnose.py` or `generate/skill.py` behavior "just in case," that's a sign it's misreading the plan.
