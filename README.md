<div align="center">

# immunize

### Curated, verified guardrails that stop AI coding assistants from repeating runtime errors.

**Offline · Deterministic · Cross-tool · Team-shareable · No API key at runtime.**

[![PyPI version](https://img.shields.io/pypi/v/immunize.svg)](https://pypi.org/project/immunize/)
[![Python versions](https://img.shields.io/pypi/pyversions/immunize.svg)](https://pypi.org/project/immunize/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](./LICENSE)
[![CI](https://github.com/viditkbhatnagar/immunize/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/viditkbhatnagar/immunize/actions/workflows/ci.yml)
[![Patterns](https://img.shields.io/badge/bundled%20patterns-7-success)](#bundled-pattern-library)
[![Status](https://img.shields.io/badge/status-beta-yellow)](#)

</div>

---

## Table of Contents

1. [What is immunize?](#what-is-immunize)
2. [Why it exists](#why-it-exists)
3. [How it compares](#how-it-compares)
4. [Architecture at a glance](#architecture-at-a-glance)
5. [End-to-end pipeline](#end-to-end-pipeline)
6. [Quickstart](#quickstart)
7. [The four trigger paths](#the-four-trigger-paths)
8. [Pattern matching internals](#pattern-matching-internals)
9. [Verification harness](#verification-harness)
10. [Artifact injection](#artifact-injection)
11. [Bundled pattern library](#bundled-pattern-library)
12. [CLI reference](#cli-reference)
13. [Configuration](#configuration)
14. [Project layout](#project-layout)
15. [Data model](#data-model)
16. [Authoring new patterns](#authoring-new-patterns)
17. [State storage](#state-storage)
18. [Security & privacy](#security--privacy)
19. [Continuous integration](#continuous-integration)
20. [Roadmap](#roadmap)
21. [Contributing](#contributing)
22. [License](#license)

---

## What is immunize?

`immunize` is a Python CLI and pattern library that turns the runtime errors your AI coding assistant produces into **verified, durable, cross-tool guardrails** committed to your repository.

When a bash command fails inside Claude Code (or any shell wrapped via `immunize run`), `immunize`:

1. Captures the failure payload.
2. Matches it against a curated regex/heuristic library — *no LLM call at runtime*.
3. Runs the matched pattern's pytest in a subprocess to confirm the fix is sound *in this environment*.
4. Injects three artifacts into your repo:
    - A **Claude Code skill** (`.claude/skills/immunize-<slug>/SKILL.md`)
    - A **Cursor rule** (`.cursor/rules/<slug>.mdc`)
    - A **pytest regression test** (`tests/immunized/<slug>/test_template.py`)

Commit them. Your team — and every AI session anyone runs against the repo — picks the immunity up automatically.

> **Mental model.** Your immune system remembers pathogens it has met. `immunize` does the same for AI coding assistants: once it sees an error, the AI never repeats that *class* of error in your project again.

---

## Why it exists

AI assistants repeat the same mistakes every session. You fix the stale-closure bug in `useEffect` on Monday; by Wednesday the assistant has rewritten it in a different file. The model has no durable memory of what you corrected.

Existing answers each fall short:

| Approach | Limitation |
|---|---|
| Claude Code memory / Cursor rules | Single-tool. Per-user. **Untested** — no build-time check that the rule prevents the error it claims to. |
| "Don't do that again" in chat | Survives one session, dies on `/clear` or a new teammate joining. |
| Linters / type checkers | Catch what their authors imagined — not what the AI specifically over-produces. |
| Sentry-style triagers | Detect & diagnose, but emit no persistent rules other tools can read. |

`immunize` makes a different bet: **a small, curated, *verified* library** of patterns covering the mistakes that matter, shipping artifacts in formats every assistant already reads, with a pytest that proves each fix works.

---

## How it compares

```mermaid
%%{init: {'theme':'base'}}%%
flowchart LR
    classDef yes fill:#16a34a,stroke:#166534,color:#fff
    classDef no fill:#dc2626,stroke:#7f1d1d,color:#fff
    classDef partial fill:#f59e0b,stroke:#92400e,color:#fff

    subgraph Capabilities[" "]
        direction TB
        C1[SKILL.md emit]
        C2[Cursor rule emit]
        C3[Verified pytest]
        C4[Cross-tool]
        C5[Team-shareable via git]
        C6[Zero API key at runtime]
    end

    immunize:::yes --> C1 & C2 & C3 & C4 & C5 & C6
    Cursor_Bugbot:::partial --> C2
    Claude_Memory:::partial --> C1
    Sentry_Seer:::partial --> C2
    Semgrep_Assistant:::partial --> C2
    CodeRabbit:::partial --> C5
```

Only `immunize` ships **all six** at once. Verified regression tests are the structural moat — every other tool in this space stops at "we found a problem"; `immunize` proves the fix.

---

## Architecture at a glance

Three layers separate concerns cleanly: triggers, the engine, and the artifacts that land in your repo.

```mermaid
%%{init: {'theme':'base', 'flowchart': {'curve': 'basis'}}}%%
flowchart TB
    subgraph L1["LAYER 1 — Triggers (sensors)"]
        direction LR
        T1["Claude Code<br/>PostToolUseFailure hook"]
        T2["Shell wrapper<br/>immunize run &lt;cmd&gt;"]
        T3["Bundled skill<br/>immunize-manager"]
        T4["Manual CLI<br/>immunize capture &lt;json"]
    end

    subgraph L2["LAYER 2 — Engine (Python package)"]
        direction LR
        E1[capture.py] --> E2[matcher.py]
        E2 --> E3[verify.py]
        E3 --> E4[inject.py]
        E5[(SQLite<br/>.immunize/state.db)]
        E1 -.persist.-> E5
        E4 -.record.-> E5
    end

    subgraph L3["LAYER 3 — Generated artifacts (in your repo, committed)"]
        direction LR
        A1[".claude/skills/immunize-&lt;slug&gt;/<br/>SKILL.md"]
        A2[".cursor/rules/&lt;slug&gt;.mdc"]
        A3["tests/immunized/&lt;slug&gt;/<br/>test_template.py"]
    end

    L1 --> L2
    L2 --> L3

    style L1 fill:#eff6ff,stroke:#1e40af
    style L2 fill:#f0fdf4,stroke:#166534
    style L3 fill:#fef3c7,stroke:#92400e
```

- **Layer 1** is plural by design. A single failure can arrive from a Claude Code hook, a `immunize run` subprocess, the bundled skill nudging the model, or a manual JSON pipe.
- **Layer 2** is one pipeline: capture → match → verify → inject. Pure Python. No network, no API key.
- **Layer 3** is the durable output — committed to git, picked up automatically on `git pull` by every assistant the team uses.

---

## End-to-end pipeline

The same five-step pipeline runs no matter which trigger fires:

```mermaid
%%{init: {'theme':'base'}}%%
sequenceDiagram
    autonumber
    participant Tool as AI tool / shell
    participant CLI as immunize CLI
    participant Match as matcher.py
    participant Verify as verify.py
    participant Inject as inject.py
    participant Repo as Your repo (.claude/, .cursor/, tests/)
    participant DB as .immunize/state.db

    Tool->>CLI: failure JSON on stdin<br/>(Bash exit ≠ 0)
    CLI->>DB: persist CapturePayload
    CLI->>Match: load_patterns() + match()
    Match-->>CLI: ranked MatchResult[]
    alt no pattern clears threshold
        CLI-->>Tool: {"outcome":"unmatched"}
    else top pattern clears
        CLI->>Verify: run pytest in subprocess<br/>(swap fix→repro fixture)
        alt verify fails
            CLI-->>Tool: {"outcome":"matched_verify_failed", reason}
        else verify passes
            CLI->>Inject: atomic write 3 artifacts
            Inject->>Repo: SKILL.md + cursor_rule + test_template
            CLI->>DB: insert artifacts row
            CLI-->>Tool: {"outcome":"matched_and_verified", artifacts}
        end
    end
```

Stdout is a **strict one-line JSON contract**; Rich console output goes to stderr. Hook handlers can trust the shape.

### Decision tree at the matcher

```mermaid
%%{init: {'theme':'base'}}%%
flowchart TD
    A[CapturePayload arrives] --> B[Compile regex rules per pattern<br/>cached by pattern.id]
    B --> C[Score each pattern<br/>= stderr + stdout + class hint + language]
    C --> D{confidence ≥<br/>per-pattern<br/>min_confidence?}
    D -->|no| E[drop]
    D -->|yes| F{confidence ≥<br/>global floor<br/>IMMUNIZE_MIN_MATCH_CONFIDENCE?}
    F -->|no| E
    F -->|yes| G[sort desc by confidence]
    G --> H[take top 1]
    H --> I[verify in subprocess]
    I -->|pass| J[inject + persist]
    I -->|fail| K[emit matched_verify_failed]
    E --> L[emit unmatched]
```

Each gate is documented in [`src/immunize/matcher.py`](./src/immunize/matcher.py) and [`src/immunize/cli.py`](./src/immunize/cli.py).

---

## Quickstart

```bash
pip install immunize        # core wheel — zero LLM dependencies
cd your-project
immunize install-skill      # drops .claude/skills/immunize-manager/SKILL.md
immunize install-hook       # registers .claude/settings.json PostToolUseFailure hook
```

Restart Claude Code. From this point on, every failed `Bash` tool call inside Claude Code feeds `immunize capture` automatically. When a known error class hits — `AttributeError: 'NoneType'`, `ModuleNotFoundError`, a 429 crash, a CORS preflight rejection — three files appear in your repo. Commit them.

**Outside Claude Code** (Cursor, plain shells, CI):

```bash
immunize run pytest tests/
immunize run npm test
immunize run python manage.py migrate
```

`immunize run` tees output live, propagates exit codes, and on non-zero exit feeds the same matcher pipeline.

---

## The four trigger paths

Four entry points, one engine. Picking the right one is just a matter of where your failures originate.

```mermaid
%%{init: {'theme':'base'}}%%
flowchart LR
    subgraph In["Where the failure happens"]
        direction TB
        F1["Claude Code<br/>(Bash tool call)"]
        F2["Cursor / plain shell<br/>(your terminal)"]
        F3["Claude Code<br/>(no hook configured)"]
        F4["Existing log<br/>or scripted replay"]
    end

    subgraph Triggers["Trigger path"]
        direction TB
        T1["PostToolUseFailure hook<br/>--source claude-code-hook"]
        T2["immunize run &lt;cmd&gt;<br/>--source shell-wrapper"]
        T3["immunize-manager skill<br/>nudges Claude to call"]
        T4["echo '{...}' | immunize capture<br/>--source manual"]
    end

    F1 --> T1
    F2 --> T2
    F3 --> T3
    F4 --> T4

    T1 & T2 & T3 & T4 --> ENGINE[("capture → match → verify → inject")]
    style ENGINE fill:#10b981,color:#fff
```

| Path | Set up by | Streams output? | Best for |
|---|---|---|---|
| **Hook** | `immunize install-hook` | n/a (Claude shows it) | Zero-touch automation in Claude Code |
| **`immunize run`** | nothing — invoke per command | Yes (live tee) | CI, Cursor, bare shells |
| **Bundled skill** | `immunize install-skill` | n/a | Falls back to `immunize run` when no hook |
| **Manual `capture`** | hand-built JSON | n/a | Replays, scripted captures, testing |

The hook payload is translated by [`payload_from_claude_code_hook`](./src/immunize/capture.py) into a `CapturePayload` — non-Bash failures are skipped cleanly, never producing noisy unmatched captures.

---

## Pattern matching internals

A `Pattern` is a five-file directory under [`src/immunize/patterns/<slug>/`](./src/immunize/patterns/) and a YAML descriptor. The matcher scores each candidate by combining four signals:

```mermaid
%%{init: {'theme':'base'}}%%
flowchart LR
    P[CapturePayload<br/>stderr + stdout] --> S1["stderr regex hits<br/>(min 0.6, +0.3 each)"]
    P --> S2["stdout regex hits<br/>(min 0.4, +0.2 each)"]
    P --> S3["error class hint<br/>+0.15 if matches"]
    P --> S4["language detection<br/>+0.10 if pattern lang ∈ detected"]
    S1 & S2 & S3 & S4 --> SUM[["Σ capped at 1.0"]]
    SUM --> CMP{≥ pattern.min_confidence<br/>and<br/>≥ global floor?}
    CMP -->|yes| RANK[ranked candidate]
    CMP -->|no| DROP[dropped]
```

Implementation references:

- Score breakdown — [`score_pattern`](./src/immunize/matcher.py)
- Error class keyword set — [`ERROR_CLASS_HINTS`](./src/immunize/matcher.py) (`cors`, `import`, `auth`, `rate_limit`, `type_error`, `null_ref`, `config`, `network`)
- Language signatures — [`_LANGUAGE_SIGNATURES`](./src/immunize/matcher.py) (`python`, `javascript`, `typescript`, `go`, `rust`)
- Word-bounded keyword regex — fixes the latent collision where `ENOTFOUND` substring-matched inside `ModuleNotFoundError`.
- Float epsilon (`1e-9`) — defends `0.3 + 0.15 ≥ 0.45` from IEEE-754 imprecision.

### Two thresholds, one authoritative source

| Layer | Field | Default | Purpose |
|---|---|---|---|
| Per-pattern | `pattern.match.min_confidence` | varies (0.30–0.50) | Authored against real-world stderr |
| Global floor | `Settings.min_match_confidence` | `0.30` | Operator escape hatch (raise via `IMMUNIZE_MIN_MATCH_CONFIDENCE` for CI strict mode) |

Pre-`v0.2.0` the global floor was `0.70` and silently shadowed every per-pattern threshold below it; calibration data and the rationale live in [`_planning/MATCHER_CALIBRATION_V020.md`](./_planning/MATCHER_CALIBRATION_V020.md).

---

## Verification harness

A pattern only ships if its pytest **fails** without the fix and **passes** with it. The harness re-checks the *passes-with-fix* half on the user's machine before injecting, catching environment drift (missing optional deps, pytest version skew):

```mermaid
%%{init: {'theme':'base'}}%%
flowchart TB
    Start([verify.verify pattern]) --> Has{fixtures/ has<br/>repro.* + fix.* pair?}
    Has -->|no| Run[run pytest as-is]
    Has -->|yes| Backup[read repro.* bytes<br/>into memory]
    Backup --> Swap[write fix.* bytes<br/>over repro.* path]
    Swap --> Run
    Run --> Sub[python -m pytest -x -q<br/>cwd = pattern dir<br/>timeout = 30s]
    Sub --> Code{exit code?}
    Code -->|0| Pass([VerificationResult passed=True])
    Code -->|1, 2, 5| Fail([VerificationResult passed=False<br/>+ truncated diagnostic])
    Code -->|TimeoutExpired| TO([passed=False<br/>error: pytest timed out])
    Sub --> Restore[finally: write original<br/>repro.* bytes back]
    Restore --> Pass
    Restore --> Fail
    Restore --> TO
```

Reference: [`verify.verify`](./src/immunize/verify.py) (user-runtime swap), [`scripts/pattern_lint.py`](./scripts/pattern_lint.py) (CI dual-run: FAIL → PASS → FAIL-after-restore).

The CI path is stricter than runtime — it runs the full three-phase swap so a broken pattern can never be merged in the first place.

---

## Artifact injection

Three files land in fixed paths inside the user's project, each via an atomic write (PID-suffixed temp + `os.replace`):

```mermaid
%%{init: {'theme':'base'}}%%
flowchart LR
    Pattern[("src/immunize/patterns/&lt;slug&gt;/")]
    Pattern --> SKILL[SKILL.md] --> O1[".claude/skills/immunize-&lt;slug&gt;/SKILL.md"]
    Pattern --> CR[cursor_rule.mdc] --> O2[".cursor/rules/&lt;slug&gt;.mdc"]
    Pattern --> TEST[test_template.py] --> O3["tests/immunized/&lt;slug&gt;/test_template.py"]
    Pattern --> FIX["fixtures/repro.* + fix.*"] --> O4["tests/immunized/&lt;slug&gt;/fixtures/<br/>(repro slot receives FIX bytes)"]
    Pattern --> SG[semgrep.yml<br/>optional] --> O5[".semgrep/&lt;slug&gt;.yml"]
```

Two subtleties matter and are guarded by tests:

1. **Repro-slot rewrite.** `test_template.py` reads `fixtures/repro.*`. If we copied the pattern's buggy repro verbatim, the injected guardrail would *fail* against itself. [`_copy_fixtures_with_repro_rewrite`](./src/immunize/inject.py) writes the **fix** bytes into the repro path — keeping the test's path expression unchanged while shipping a passing regression test. Source-tree repros stay intact for `pattern_lint`.
2. **Slug collision.** [`resolve_slug`](./src/immunize/inject.py) probes 99 candidates (`base`, `base-2`, …, `base-99`) against both the SQLite `artifacts` table and the on-disk paths. If exhausted, `SlugExhaustedError` instructs the user to run `immunize remove`.

---

## Bundled pattern library

Seven patterns ship in `v0.2.x`, calibrated against 35+ real-world stderr samples. Recall details in [`_planning/MATCHER_CALIBRATION_V020.md`](./_planning/MATCHER_CALIBRATION_V020.md).

| ID | Languages | Class | Threshold | Catches |
|---|---|---|---|---|
| [`react-hook-missing-dep`](./src/immunize/patterns/react-hook-missing-dep/) | js, ts | lint | 0.30 | `useEffect`/`useCallback`/`useMemo` referencing reactive values not in deps array (matches the canonical `react-hooks/exhaustive-deps` rule ID) |
| [`fetch-missing-credentials`](./src/immunize/patterns/fetch-missing-credentials/) | js, ts | cors | 0.45 | Cross-origin authenticated `fetch` without `credentials: 'include'` (Chrome + Firefox phrasings) |
| [`python-none-attribute-access`](./src/immunize/patterns/python-none-attribute-access/) | python | null_ref | 0.30 | `AttributeError: 'NoneType' object has no attribute …` and `TypeError: 'NoneType' object is not subscriptable` |
| [`import-not-found-python`](./src/immunize/patterns/import-not-found-python/) | python | import | 0.50 | `ModuleNotFoundError` and `ImportError: cannot import name` |
| [`missing-env-var`](./src/immunize/patterns/missing-env-var/) | python | config | 0.40 | `KeyError: 'UPPER_SNAKE'` from `os.environ['…']` access |
| [`rate-limit-no-backoff`](./src/immunize/patterns/rate-limit-no-backoff/) | python | rate_limit | 0.45 | `429 Too Many Requests`, `RateLimitError`, `HTTPError … 429`, `rate_limit_error` SDK responses |
| [`async-fn-called-without-await`](./src/immunize/patterns/async-fn-called-without-await/) | python | async | 0.30 | `coroutine '<name>' was never awaited` |

Each directory contains:

```
<slug>/
├── pattern.yaml         # metadata + match rules + verification config
├── SKILL.md             # Claude Code skill (frontmatter: name, description)
├── cursor_rule.mdc      # Cursor rule  (frontmatter: description, globs, alwaysApply)
├── test_template.py     # pytest assertion that proves the fix
└── fixtures/
    ├── repro.<ext>      # buggy form  — test fails against this
    └── fix.<ext>        # correct form — test passes against this
```

---

## CLI reference

`immunize` ships eight commands. Help on each: `immunize <cmd> --help`.

```mermaid
%%{init: {'theme':'base'}}%%
flowchart LR
    classDef cap fill:#3b82f6,color:#fff
    classDef mgmt fill:#a855f7,color:#fff
    classDef setup fill:#10b981,color:#fff
    classDef contrib fill:#f59e0b,color:#fff

    capture[capture]:::cap
    run[run]:::cap
    list[list]:::mgmt
    verify[verify]:::mgmt
    remove[remove]:::mgmt
    install_skill[install-skill]:::setup
    install_hook[install-hook]:::setup
    author_pattern[author-pattern]:::contrib
```

| Command | Purpose |
|---|---|
| `immunize capture [--source S] [--stdin-plain] [--dry-run]` | Match → verify → inject from a JSON or plain-stderr stdin payload. Emits one JSON line on stdout. |
| `immunize run [--timeout N] [--no-capture] -- <cmd> [args]` | Spawn `<cmd>`, tee output live, propagate exit code, auto-capture on non-zero exit. |
| `immunize list` | Table of every immunity active in the project. |
| `immunize verify [<id\|slug>]` | Re-run pytest against one (or all) injected immunities. |
| `immunize remove <id\|slug> [--yes]` | Delete artifacts and SQLite row for an immunity. |
| `immunize install-skill [--project-dir PATH] [--force]` | Copy bundled `immunize-manager` skill into `.claude/skills/`. |
| `immunize install-hook [--project-dir PATH] [--force]` | Register the `PostToolUseFailure` hook in `.claude/settings.json`. |
| `immunize author-pattern --from-error E.json --output DIR [--model M]` | **Contributor-only.** Drafts a new bundled pattern via Claude API; lives behind `pip install 'immunize[author]'`. |

### `immunize capture` JSON output contract

Exactly one of these shapes on stdout (always exit 0 unless the CLI itself is broken):

```jsonc
// matched + verified → 3 files written
{
  "outcome": "matched_and_verified",
  "matched": true,
  "verified": true,
  "pattern_id": "python-none-attribute-access",
  "pattern_origin": "bundled",
  "confidence": 0.55,
  "artifacts": {
    "skill":       "/abs/.claude/skills/immunize-python-none-attribute-access/SKILL.md",
    "cursor_rule": "/abs/.cursor/rules/python-none-attribute-access.mdc",
    "pytest":      "/abs/tests/immunized/python-none-attribute-access/test_template.py"
  }
}

// matched but verify failed in this env (e.g. pytest missing) → no files written
{ "outcome": "matched_verify_failed", "matched": true, "verified": false,
  "pattern_id": "...", "pattern_origin": "bundled",
  "confidence": 0.55, "reason": "pytest is not installed in this environment. Run: pip install pytest" }

// no pattern cleared threshold
{ "outcome": "unmatched", "matched": false, "can_author_locally": true }

// hook fired but it wasn't a Bash failure
{ "outcome": "skipped", "reason": "non-Bash tool failure", "tool_name": "Edit" }
```

Rich-formatted, human-readable output goes to **stderr**. Stdout is for machines.

---

## Configuration

Settings resolve highest-priority first:

```mermaid
%%{init: {'theme':'base'}}%%
flowchart TB
    A[CLI flags] --> M{merge}
    B[Environment vars<br/>IMMUNIZE_*] --> M
    C[Project config<br/>.immunize/config.toml] --> M
    D[User config<br/>~/.config/immunize/config.toml] --> M
    E[Built-in defaults] --> M
    M --> S[Settings]
```

| Setting | TOML key | Env var | Default |
|---|---|---|---|
| LLM model (authoring only) | `model` | `IMMUNIZE_MODEL` | `claude-sonnet-4-6` |
| Verify timeout (seconds) | `[verify] timeout_seconds` | `IMMUNIZE_VERIFY_TIMEOUT_SECONDS` | `30` |
| Verify retry count | `[verify] retry_count` | `IMMUNIZE_VERIFY_RETRY_COUNT` | `1` |
| Global match floor | `[match] min_confidence` | `IMMUNIZE_MIN_MATCH_CONFIDENCE` | `0.30` |
| Local patterns dir | `[match] local_patterns_dir` | `IMMUNIZE_LOCAL_PATTERNS_DIR` | `.immunize/patterns_local/` |
| Generate semgrep YAML | `[generate] semgrep` | `IMMUNIZE_GENERATE_SEMGREP` | `false` |

Two operational toggles:

- **`IMMUNIZE_DEBUG_HOOK=1`** — dump every Claude Code hook payload to `.immunize/hook_payloads/<ts>-<session>.json` for offline inspection (auto-gitignored).
- **`IMMUNIZE_MIN_MATCH_CONFIDENCE=0.6`** — global floor knob; useful in CI strict mode.

---

## Project layout

```text
immunize/
├── pyproject.toml                       # hatchling build, runtime deps, [author]/[dev] extras
├── README.md                            # this file
├── CHANGELOG.md                         # Keep-a-Changelog formatted history
├── CONTRIBUTING.md                      # dev setup + pattern authoring workflow
├── LICENSE                              # Apache-2.0
├── Makefile                             # install / test / lint / format / build / clean
├── .pre-commit-config.yaml              # ruff (check + format)
├── .github/workflows/
│   ├── ci.yml                           # pytest matrix (3.10/3.11/3.12) + pattern_lint
│   └── release.yml                      # tag-driven PyPI publish via OIDC
├── _planning/                           # design docs (architecture, spec, calibration, …)
├── scripts/
│   └── pattern_lint.py                  # CI gate: structural + behavioral pattern check
├── src/immunize/
│   ├── __init__.py                      # __version__
│   ├── __main__.py                      # `python -m immunize`
│   ├── cli.py                           # Typer app + 8 commands
│   ├── capture.py                       # stdin parsing, hook translation, fingerprinting
│   ├── matcher.py                       # regex compile + score + threshold
│   ├── verify.py                        # pytest subprocess + fix→repro swap
│   ├── inject.py                        # atomic writes + slug collision resolution
│   ├── runner.py                        # `immunize run` subprocess wrapper (tee threads)
│   ├── hook_installer.py                # idempotent merge into .claude/settings.json
│   ├── skill_install.py                 # copy bundled skill into project
│   ├── storage.py                       # SQLite schema, in-place migration, queries
│   ├── config.py                        # toml + env + CLI override merge
│   ├── models.py                        # Pydantic v2: CapturePayload, Pattern, Settings, …
│   ├── authoring/
│   │   └── cli_author.py                # `author-pattern` (lazy-imports anthropic)
│   ├── patterns/                        # 7 bundled patterns (slug-named dirs)
│   └── skill_assets/
│       └── immunize-manager/SKILL.md    # bundled skill
└── tests/                               # 19 test modules covering every module
```

---

## Data model

Pydantic v2 models in [`src/immunize/models.py`](./src/immunize/models.py) define the contract:

```mermaid
%%{init: {'theme':'base'}}%%
classDiagram
    class CapturePayload {
        +Source source
        +str|None tool_name
        +str|None command
        +str stdout
        +str stderr
        +int exit_code
        +str cwd
        +datetime timestamp
        +str project_fingerprint
        +str|None session_id
    }

    class Pattern {
        +str id «kebab-case ≤40»
        +int version
        +int schema_version
        +str author
        +Literal origin «bundled|local|community»
        +str error_class
        +list~str~ languages
        +str description
        +MatchRules match
        +Verification verification
        +Path|None directory
    }

    class MatchRules {
        +list~str~ stderr_patterns
        +list~str~ stdout_patterns
        +str|None error_class_hint
        +float min_confidence
    }

    class Verification {
        +str pytest_relative_path
        +bool expected_fail_without_fix
        +bool expected_pass_with_fix
        +int timeout_seconds
    }

    class MatchResult {
        +Pattern pattern
        +float confidence
        +list~str~ matched_stderr_patterns
        +list~str~ matched_stdout_patterns
        +dict score_breakdown
    }

    class Settings {
        +str model
        +bool generate_semgrep
        +int verify_timeout_seconds
        +int verify_retry_count
        +Path project_dir
        +Path state_db_path
        +float min_match_confidence
        +Path|None local_patterns_dir
    }

    class VerificationResult {
        +bool passed
        +str|None error_message
    }

    Pattern *-- MatchRules
    Pattern *-- Verification
    MatchResult o-- Pattern
```

Source enum: `"claude-code-hook" | "shell-wrapper" | "manual"`. The CLI rejects any other value before persisting.

---

## Authoring new patterns

Two paths produce the same five-file directory shape on disk:

### Path 1 — LLM-assisted (contributor only)

```bash
pip install 'immunize[author]'
export ANTHROPIC_API_KEY=sk-ant-...
immunize author-pattern \
  --from-error path/to/error.json \
  --output src/immunize/patterns/
```

Internally:

```mermaid
%%{init: {'theme':'base'}}%%
sequenceDiagram
    participant CLI as author-pattern
    participant API as Anthropic API (Claude)
    participant Tmp as scratch dir
    participant Lint as pattern_lint.py

    CLI->>API: 1. analysis call (slug + error_class + languages + regex + confidence)
    API-->>CLI: tool_use response (forced JSON)
    CLI->>API: 2. drafting call (skill, cursor rule, pytest, repro, fix)
    API-->>CLI: tool_use response
    CLI->>Tmp: write 5 files
    CLI->>Lint: subprocess pattern_lint --patterns-dir scratch
    alt verifier rejects
        CLI->>API: 3. retry drafting with prior errors injected
        API-->>CLI: revised draft
        CLI->>Tmp: rewrite 5 files
        CLI->>Lint: re-run
    end
    alt still failing
        CLI->>CLI: dump to .immunize/rejected/<slug>/
    else passing
        CLI->>CLI: shutil.move scratch → output/<slug>/
    end
```

The Anthropic SDK is **only** imported here. End-user installs of `immunize` never pull `anthropic`, `httpx`, or `jiter` — it is gated behind the `[author]` extra.

### Path 2 — manual

Copy an existing pattern (e.g. [`python-none-attribute-access`](./src/immunize/patterns/python-none-attribute-access/)), adapt the YAML, SKILL, rule, test, and fixtures. Then:

```bash
python scripts/pattern_lint.py
```

`pattern_lint` enforces the **Ten Commandments** of pattern quality (full text in [`_planning/PATTERN_AUTHORING.md`](./_planning/PATTERN_AUTHORING.md)). The most consequential:

> 1. A pattern earns its slug. Generic names rejected.
> 2. Patterns test defaults, not knobs.
> 3. `repro.*` and `fix.*` must differ observably under the same test.
> 4. Stderr regex anchors on signal, not noise.
> 5. `min_confidence` is honest.
> 6. SKILL.md teaches, doesn't lecture.
> 7. No URLs in SKILL.md.
> 8. Languages list is precise.
> 9. Never wrap domain knowledge.
> 10. If the test is flaky, the pattern is wrong.

---

## State storage

A SQLite database at `<project>/.immunize/state.db` tracks captures and injections. Schema (see [`storage.py`](./src/immunize/storage.py)):

```mermaid
erDiagram
    errors ||--o{ artifacts : "fingerprints"
    errors {
        int id PK
        text payload_json
        text captured_at
        text project_fingerprint
    }
    artifacts {
        int id PK
        text pattern_id
        text pattern_origin
        text slug
        text skill_path
        text cursor_rule_path
        text semgrep_path
        text pytest_path
        int verified
        text created_at
    }
    diagnoses {
        int id PK
        int error_id FK
        text diagnosis_json
        text model
        text created_at
    }
    rejections {
        int id PK
        int diagnosis_id FK
        text reason
        text rejected_at
    }
```

`diagnoses` survives from the pre-`v0.1` LLM-at-runtime architecture for backward compat; the matcher pipeline writes only to `errors` and `artifacts`. An in-place migration in [`_migrate_artifacts_if_needed`](./src/immunize/storage.py) upgrades legacy schemas on first connect.

The DB is **local state only** — auto-`.gitignore`d via the install-hook flow. Shared state is the committed artifact files.

---

## Security & privacy

| Concern | Stance |
|---|---|
| LLM at runtime | **Never.** The matcher is regex; verify is pytest in subprocess; inject is `os.replace`. The Anthropic SDK is unreachable from the `capture` import graph. |
| Network calls | **Never** at user-runtime. `author-pattern` (contributor) is the sole exception, gated behind the `[author]` extra and an explicit `ANTHROPIC_API_KEY`. |
| Stderr exfiltration | Stderr is persisted only to local SQLite under `.immunize/`. Hook payload dumps are off by default and gitignored. |
| Atomic writes | Every artifact write is PID-suffixed temp + `os.replace`. Concurrent immunize processes (e.g. a hook firing during a manual capture) never observe a partial file. |
| Hook scope | We modify project-scope `.claude/settings.json` only, never user-scope `~/.claude/settings.json` (a global hook would fire in unrelated projects). |
| Idempotence | `install-hook` and `install-skill` are no-ops on identical re-invocation; `--force` is required to overwrite drifted entries. |
| OS support | POSIX only (macOS/Linux). The CLI guard refuses to run on `win32` with a clear message. Windows on the roadmap. |

---

## Continuous integration

```mermaid
%%{init: {'theme':'base'}}%%
flowchart LR
    Push[push / PR] --> CI[ci.yml]
    Tag[tag v*] --> Rel[release.yml]
    CI --> Test[matrix 3.10 / 3.11 / 3.12<br/>pytest + ruff]
    CI --> PLint[pattern_lint.py<br/>FAIL → PASS → FAIL-after-restore]
    Test & PLint --> Green((green))
    Rel --> Build[python -m build]
    Build --> Pub[pypa/gh-action-pypi-publish<br/>OIDC trusted publisher]
```

- **`ci.yml`** — installs `[dev]` extras, runs `ruff check .`, `pytest`, and `python scripts/pattern_lint.py` on three Python versions in parallel.
- **`release.yml`** — fires on `v*` tag pushes, builds wheel + sdist, and publishes to PyPI via OIDC trusted publishing (no API tokens stored).

---

## Roadmap

Tracked in [`_planning/LAUNCH_LIBRARY.md`](./_planning/LAUNCH_LIBRARY.md) and CHANGELOG entries.

| Version | Theme | Status |
|---|---|---|
| `v0.1.x` | Core pipeline, 7 bundled patterns, manual capture | shipped |
| `v0.2.x` | Claude Code hook automation, `immunize run`, calibrated matcher | **current** |
| `v0.3.x` | Native test runners (Jest/Go/cargo), Windows support, more patterns | planned |
| `v0.4+` | Community pattern registry, IDE-side telemetry opt-in | exploratory |

Explicit non-goals: web dashboard, MCP server, always-on shell daemon, IDE extensions. The premise is to *emit files the existing tools already read*.

---

## Contributing

Contributions — especially new patterns — are warmly welcomed. Start with [`CONTRIBUTING.md`](./CONTRIBUTING.md) for dev setup and [`_planning/PATTERN_AUTHORING.md`](./_planning/PATTERN_AUTHORING.md) for the Ten Commandments.

```bash
git clone https://github.com/viditkbhatnagar/immunize.git
cd immunize
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
make test                              # full pytest suite
python scripts/pattern_lint.py         # validate every bundled pattern
```

PRs land via GitHub. One pattern per PR. CI must be green.

---

## License

Apache-2.0 — see [LICENSE](./LICENSE).

<div align="center">

<sub>Built with Python 3.10+, Typer, Pydantic v2, Rich, and pytest. No LangChain. No daemons. No telemetry.</sub>

</div>
