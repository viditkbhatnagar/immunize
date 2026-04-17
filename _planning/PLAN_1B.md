# immunize — Phase 1B (Pivot Plan)

> **Read this before anything else.** This plan replaces the original Phase 1 entirely. The old plan is in `_planning/archive/PLAN.md` for reference only.

## Why we're pivoting

The original Phase 1 called Claude's API at runtime to diagnose errors and generate artifacts. Mid-build, a fundamental product question surfaced:

**If a user already has Claude Code (which does free auto-memory) or can just ask Claude "don't do that again" in their existing session — why would they install a tool that charges them more API spend for essentially the same outcome?**

The answer was: they wouldn't. The original architecture had a fatal adoption problem that made launch futile.

So we pivot. `immunize` becomes a **bundled pattern library** — a curated, open-source registry of known AI-coding runtime errors with pre-verified immunity artifacts. Zero LLM calls at user-runtime. Zero API key required. Zero cost ever. Plus a local-learning mechanism so each user's install grows smarter over time by drafting patterns from their own Claude Code session (no separate API call — piggybacks on the session the user is already running).

The new pitch: **"ESLint for AI coding errors, with your AI assistant as co-author when new errors strike."**

## What survives from Phase 1

We archived the current main branch as `phase1-llm-runtime-archive`. Of the 11 commits on that branch:

| Module | Fate |
|---|---|
| `pyproject.toml`, CI, LICENSE, `.gitignore`, Phase 0 scaffolding | KEEP as-is |
| `src/immunize/__init__.py`, `__main__.py` | KEEP as-is |
| `src/immunize/models.py` | MODIFY — remove `Diagnosis`, `GeneratedArtifacts`; add `Pattern`, `MatchResult`, `AuthoringDraft` |
| `src/immunize/config.py` | SIMPLIFY — remove `build_client()` entirely; runtime never calls Claude |
| `src/immunize/storage.py` | KEEP — schema still works for tracking captures and applied immunities |
| `src/immunize/capture.py` | KEEP — input parsing is unchanged |
| `src/immunize/verify.py` | KEEP — now used at pattern-authoring time and on pattern install |
| `src/immunize/inject.py` | KEEP — atomic writes still needed |
| `src/immunize/cli.py` | MODIFY — same command surface, different orchestration body |
| `src/immunize/diagnose.py` | DELETE |
| `src/immunize/generate/skill.py` | DELETE (logic moves into the authoring tool) |
| `src/immunize/generate/pytest_gen.py` | DELETE (logic moves into the authoring tool) |
| `src/immunize/generate/cursor_rule.py` | KEEP as a utility — deterministic derivation runs at pattern-authoring time |
| `src/immunize/generate/semgrep.py` | DELETE |
| Tests for deleted modules | DELETE |

Rough survival rate: ~60% of the code on `phase1-llm-runtime-archive` lives on in Phase 1B. The rest is archived for reference.

## What we're adding

1. **`src/immunize/patterns/`** — the bundled pattern library directory. One subfolder per pattern containing its SKILL.md, Cursor rule, optional Semgrep rule, pytest template, and pattern.yaml metadata.
2. **`src/immunize/matcher.py`** — the matching engine. Given a `CapturePayload`, scans the bundled and local pattern libraries, returns ranked `MatchResult`s.
3. **`src/immunize/authoring/`** — the pattern-authoring toolkit.
   - `cli_author.py` — the `immunize author-pattern` command (uses Claude at authoring time to help draft, NOT at runtime).
   - `session_author.py` — the runtime local-learning path. Integrates with Claude Code's bundled skill so the user's existing Claude Code session drafts a new local pattern. The Python code NEVER calls Claude directly here; the bundled skill tells Claude Code to do the drafting and write files through the tool.
4. **`src/immunize/skill_assets/immunize-manager/SKILL.md`** — the bundled skill, now substantially richer. Teaches Claude Code how to invoke `immunize` on errors AND how to help author new local patterns when no bundled pattern matches.
5. **`src/immunize/patterns_local/`** — runtime state directory (gitignored at package level; each user's install gets their own). Local patterns get saved here.
6. **`scripts/pattern_lint.py`** — dev-only. Validates every bundled pattern on CI: YAML shape, verified pytest passes, no broken markdown.

## Scope for v0.1 — what ships

- 15–20 bundled patterns covering common AI-coding errors (detailed list in `LAUNCH_LIBRARY.md`)
- Matcher working against both bundled and local patterns
- `immunize capture` — hits matcher, applies matching pattern, runs verification, injects artifacts
- `immunize author-pattern` — dev/contributor tool that uses Claude to help draft a new pattern (requires `ANTHROPIC_API_KEY`, only for contributors)
- `immunize list` / `verify` / `remove` — unchanged from original plan
- Bundled `immunize-manager` skill that supports both known-match path AND unknown-error local-authoring path
- Windows guard: unchanged (POSIX-only for v0.1)

## Out of scope for v0.1

- Community registry / central pattern repo (v0.3+)
- Backend infrastructure of any kind
- Pattern versioning/migration (patterns are immutable; bump the package version to ship updates)
- Native-language test runners (still Python pytest for verification; limitation documented)
- Any runtime LLM call from the Python code

## Commit strategy for Phase 1B

**Branch discipline**: all Phase 1B work happens on a feature branch named `phase-1b-pivot`, NOT on `main`. `main` stays frozen at the Phase 1 state during the pivot. When Phase 1B is complete and fully verified, `phase-1b-pivot` gets merged into `main` as a single reviewable unit. This is how real teams handle architectural pivots.

- `main` — frozen Phase 1 state. Protected. No commits during Phase 1B.
- `phase1-llm-runtime-archive` — permanent reference snapshot. Never touched.
- `phase-1b-pivot` — active feature branch. All Phase 1B commits land here.

**API key discipline**: by the end of Step 2, `import anthropic` and `ANTHROPIC_API_KEY` must be absent from all user-runtime code. An explicit audit runs in Steps 1 and 2 to catch any leftover references. The ONLY allowed occurrences in the post-pivot tree are:
- `src/immunize/authoring/cli_author.py` (contributor tool, Step 7)
- `scripts/pattern_lint.py` (dev/CI tool)
- `pyproject.toml` dependencies (keep `anthropic` as a dep so the authoring tool works)
- `_planning/archive/*` (reference material, never executed)

Any other occurrence is a bug and must be removed before the step's commit.

**Step sequence**: not a fresh Phase 0. We revert-or-modify on top of the archived `phase1-llm-runtime-archive` branch, landing on `phase-1b-pivot`. Sequence:

1. **Archive + prune** — archive branch is already pushed; now on main, delete `diagnose.py`, `generate/skill.py`, `generate/pytest_gen.py`, `generate/semgrep.py` and their tests.
2. **Trim `config.py` + `models.py`** — remove `build_client`, remove unused models, add `Pattern` / `MatchResult` / `AuthoringDraft`.
3. **Add `matcher.py` + tests** — core matching engine.
4. **Add `patterns/` library directory + first 3 patterns** — prove the shape before scaling.
5. **Add `scripts/pattern_lint.py` + CI hook** — every pattern must lint and verify or the commit fails.
6. **Rewrite `cli.py` orchestrator** — capture now hits matcher instead of diagnose+generate.
7. **Add `authoring/cli_author.py`** — the `immunize author-pattern` contributor tool.
8. **Add bundled `immunize-manager` SKILL.md** — supports both match path and local-authoring path.
9. **Add `authoring/session_author.py`** — the local-learning runtime receiver (Python side of the skill-driven authoring).
10. **Bulk-author remaining 12–17 patterns** using the authoring tool. One commit per pattern so each can be reverted independently if a pattern regresses.
11. **End-to-end integration test** — `CliRunner` against real capture → real match → real inject → assert artifacts, using bundled patterns only (no LLM in test path).
12. **README + Known Limitations rewrite** — positions `immunize` as a pattern library, not an LLM-powered tool.

Order is load-bearing. Steps 1–9 ship the mechanism. Step 10 ships the content. Step 11 proves it works. Step 12 tells the world.

## Success criteria for v0.1

End-to-end acceptance — run locally:

```bash
pip install immunize
cd /tmp/sandbox-immunize
# Pipe a known CORS error fixture in
cat test_cors_error.json | immunize capture --source manual
```

Must:
- Match a bundled pattern in < 200ms
- Run verification pytest in a subprocess
- Inject 3 artifacts (SKILL.md, Cursor rule, pytest) into the project
- Print Rich summary, exit 0
- **No `ANTHROPIC_API_KEY` set anywhere in the environment**

Plus:
- `immunize list` shows the injected immunity
- All 15–20 bundled patterns lint green and verify green on CI
- CI matrix on Python 3.10/3.11/3.12 stays green

## Success criteria for local-learning path (v0.1 stretch)

Inside an active Claude Code session:
- User hits an error with no bundled pattern match
- The `immunize-manager` skill detects this and offers to draft a local pattern
- Claude Code drafts the SKILL.md, Cursor rule, pytest, and fix snippet inline in its session context
- A tool invocation sends the draft to `immunize author-local-from-session` (or similar)
- Python verifies the draft with the pytest harness
- On success, draft is saved to `src/immunize/patterns_local/<slug>/` in the user's project
- On failure, draft is rejected; Claude Code can iterate one more time in-session

This path uses zero incremental API cost — the user was already paying for that Claude Code turn.

## Hard constraints

- **No LLM call from Python at user-runtime.** Ever. The authoring CLI uses Claude, but that's contributor-only and clearly documented.
- **No new Anthropic SDK imports in matcher / cli / capture / inject / verify / storage / models.** The SDK is imported only in `scripts/` and `src/immunize/authoring/cli_author.py`.
- **Patterns are immutable once shipped in a release.** To update a pattern, bump the package version and ship v0.1.1. Users get updates via `pip install --upgrade`.
- **Every pattern must pass the lint + verify gate** before merging to main. No exceptions. The gate is CI-enforced.
- **Windows-guard stays** (POSIX-only for v0.1).

## What this pivot means for the launch narrative

The new Hacker News pitch becomes:

> **Show HN: immunize – a curated library of patterns that stop AI coding assistants from repeating common runtime errors (no API key needed)**

That title is stronger than the original. "No API key needed" is the phrase that kills every objection a cost-sensitive developer has. Pattern-library framing also gives you a clear moat: bundled patterns are a curated product, not a wrapper around Claude's API.

## What this pivot means for your resume

Before: "Built a Python tool that calls Claude to generate coding rules."

After: "Shipped an open-source registry of curated patterns for AI coding error prevention — 20 verified immunities in v0.1, with a self-extending local-learning mechanism that uses the user's existing Claude Code session to author new patterns at zero incremental cost."

The second version reads like product-engineering work, not API-wrapper work. It's a meaningfully stronger interview story.

## How Claude Code should read this plan

Load order: `PLAN_1B.md` (this file) → `ARCHITECTURE_1B.md` → `PATTERN_AUTHORING.md` → `LAUNCH_LIBRARY.md`. The original Phase 1 docs at `_planning/archive/PLAN.md` are reference material ONLY — do not execute them.

If any instruction in this plan contradicts the original Phase 1 plan, this plan wins. Do not preserve code or behavior from the original just because it was already built. Archiving was the preservation step; the main branch is now a live working tree we're rewriting.
