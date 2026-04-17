# How to use these pivot docs

Four new planning documents, all with `_1B` suffix to distinguish from the archived originals:

| File | Purpose |
|---|---|
| `PLAN_1B.md` | Master plan for the pivot — what changes, what's kept, phase steps |
| `ARCHITECTURE_1B.md` | New system design — pattern library, matcher, local-learning via skill |
| `PATTERN_AUTHORING.md` | The content-creation playbook for every bundled pattern |
| `LAUNCH_LIBRARY.md` | Prioritized list of 20 patterns to ship in v0.1 |

## Branching strategy for the pivot

The pivot will NOT rewrite `main` directly. Instead:

- `main` — stays on its current 11-commit Phase 1 state during the rebuild. Protected. No direct commits.
- `phase1-llm-runtime-archive` — permanent reference snapshot of the old architecture. Never deleted.
- `phase-1b-pivot` — the new feature branch where all Phase 1B work happens, step by step.

When Phase 1B is complete AND fully working AND verified end-to-end, you merge `phase-1b-pivot` into `main` as a single reviewable unit. Until then, `main` is safe to check out at any time if you need to show someone the "before" state or roll back completely.

This is how real teams handle pivots. It also means you can abandon Phase 1B without damage if something goes sideways.

## Pre-flight — do these in order

### 1. Create the archive branch (preserves the old work)

In your terminal:

```bash
cd ~/codes/immunize
git status                  # must be clean; commit or stash anything loose first
git checkout main
git pull

# Create the permanent archive
git checkout -b phase1-llm-runtime-archive
git push -u origin phase1-llm-runtime-archive
```

This branch is now a permanent snapshot of Phase 1 as it exists today. Never delete it. If anyone (future you, a hiring manager, a curious contributor) ever wants to see the original LLM-runtime architecture, it lives on this branch forever.

### 2. Create the pivot feature branch

```bash
git checkout main           # back to main
git checkout -b phase-1b-pivot
git push -u origin phase-1b-pivot
```

**All Phase 1B work happens on `phase-1b-pivot`.** Nothing touches `main` until the pivot is fully done and verified.

### 3. Archive the old planning docs on the pivot branch

You're on `phase-1b-pivot` now. Move the old planning docs out of the way:

```bash
mkdir -p _planning/archive
git mv _planning/PLAN.md _planning/archive/PLAN_v1.md
git mv _planning/ARCHITECTURE.md _planning/archive/ARCHITECTURE_v1.md
git mv _planning/SPEC.md _planning/archive/SPEC_v1.md
git mv _planning/HOW_TO_USE.md _planning/archive/HOW_TO_USE_v1.md
# Keep _planning/PYPI_PUBLISHING.md — that's still accurate
git commit -m "Phase 1B pre-flight: archive v1 planning docs"
```

### 4. Drop in the new planning docs

Copy the five new files I generated into your `_planning/` folder:

```bash
# Assuming the files are at /path/to/pivot/plan-1b/
cp /path/to/pivot/plan-1b/*.md _planning/
git add _planning/PLAN_1B.md _planning/ARCHITECTURE_1B.md _planning/PATTERN_AUTHORING.md _planning/LAUNCH_LIBRARY.md _planning/HOW_TO_USE_1B.md
git commit -m "Phase 1B pre-flight: add pivot planning docs"
git push
```

You should now see both branches on GitHub at `https://github.com/viditkbhatnagar/immunize/branches`. `main` still points at commit d0b29d4 (Phase 1 complete). `phase-1b-pivot` is 2 commits ahead.

### 5. Open a fresh Claude Code session

Important: use the `+` icon or close/reopen the Claude Code panel. Fresh context is essential — the old session has several hours of "old architecture" context in it that could confuse the pivot.

## The Phase 1B kickoff prompt

Paste this verbatim into the fresh Claude Code session in plan mode:

---

I'm pivoting the `immunize` project mid-build. The original Phase 1 shipped 11 commits of LLM-runtime architecture that I've decided is wrong for the product. The pivot goal: `immunize` becomes a bundled pattern library (zero LLM calls at user-runtime, zero API key required) plus a local-learning path that piggybacks on the user's existing Claude Code session.

**Read these files in full before doing anything else:**

1. `_planning/PLAN_1B.md` — master plan for the pivot
2. `_planning/ARCHITECTURE_1B.md` — new system design
3. `_planning/PATTERN_AUTHORING.md` — how patterns are written
4. `_planning/LAUNCH_LIBRARY.md` — the 20 patterns to ship in v0.1

The originals at `_planning/archive/PLAN_v1.md` etc. are reference material ONLY. If they conflict with the new plan, the new plan wins.

**Branch discipline — read this carefully**

All Phase 1B work happens on the `phase-1b-pivot` branch. I've already created and pushed it. The `main` branch is protected during the pivot — do NOT commit to main, do NOT merge into main, do NOT touch main.

Before any work, verify you're on the right branch:

```bash
git branch --show-current   # must output: phase-1b-pivot
```

If it outputs anything else, stop and tell me. Do not proceed until you're on `phase-1b-pivot`.

Every commit lands on `phase-1b-pivot`. When the full pivot is complete (all 12 steps from PLAN_1B.md done, verified end-to-end, tests green), I will personally review the diff and merge `phase-1b-pivot` into `main` as a squash or merge commit. You do not execute that merge.

**Repo state**:
- `main` = 11 commits of Phase 1 LLM-runtime work. Frozen during the pivot.
- `phase1-llm-runtime-archive` = permanent snapshot of Phase 1 state. Never touched again.
- `phase-1b-pivot` = active feature branch where all Phase 1B work happens. This is where you commit.

**Your task right now**: propose a plan for **Step 1 of Phase 1B only** per `PLAN_1B.md` — Archive + prune the LLM-runtime code. Do not code yet. Wait for my approval.

Step 1 means:

1. Confirm you are on branch `phase-1b-pivot` before any action.
2. Delete these files: `src/immunize/diagnose.py`, `src/immunize/generate/skill.py`, `src/immunize/generate/pytest_gen.py`, `src/immunize/generate/semgrep.py`, and their corresponding test files in `tests/` (likely `test_diagnose.py`, `test_generate_skill.py`, `test_generate_pytest.py`, `test_generate_semgrep.py`).
3. Keep `src/immunize/generate/cursor_rule.py` — its deterministic derivation logic lives on in the new architecture.
4. Keep `src/immunize/generate/__init__.py` but strip out any imports of the deleted modules (and the `generate_all` function that orchestrated them).
5. **Audit every remaining file for `anthropic` imports, `ANTHROPIC_API_KEY` references, and `build_client` calls.** List every occurrence. We'll remove them in Step 2, but I want the full inventory now. Grep the codebase with: `git grep -nE "anthropic|ANTHROPIC_API_KEY|build_client" -- 'src/' 'tests/'` and paste the full output in your plan so I can see the scope of the cleanup.
6. Run the test suite after deletions. We expect failures from tests that imported deleted modules — that's fine; Step 2 cleans up further. Count them, report them, don't try to fix them in Step 1.
7. Commit with message: `Phase 1B step 1: archive LLM-runtime modules`. Push to `phase-1b-pivot`.

**Hard rules for the pivot — all 12 steps, not just Step 1**:

- The Python package NEVER imports `anthropic` at user-runtime. After the pivot is complete, the ONLY places `import anthropic` may appear are:
  - `src/immunize/authoring/cli_author.py` (built in Step 7 — contributor-only tool)
  - `scripts/pattern_lint.py` (dev tool, runs on CI, never shipped to users at runtime)
- No code path reachable from `immunize capture`, `immunize list`, `immunize verify`, `immunize remove`, or `immunize author-local-from-session` may import anthropic, reference ANTHROPIC_API_KEY, or make any network call to Anthropic's API. The ONLY LLM use in the user-runtime path is via Claude Code's own session, driven by the bundled skill — never a direct call from the Python code.
- `build_client()` in `config.py` gets deleted entirely. Any reference to it is an error.
- `ANTHROPIC_API_KEY` env var reads are deleted from runtime code. The authoring CLI reads it explicitly (it's a contributor tool); everything else must not.
- Pattern files under `src/immunize/patterns/` are the product. Do not auto-generate them; I'll author them manually with the authoring tool in Step 10 under my supervision.
- Do not bump version. Do not create tags. Do not modify `.github/workflows/release.yml`.
- Do not "preserve" behavior from the archived code just because it was already built. If a pivoted module's behavior differs from the archived version, that's correct.
- Do not merge `phase-1b-pivot` into `main` at any point. That's my call after the pivot is done.

After Step 1 is approved and executed, stop. Wait for my Step 2 prompt.

---

## What to expect from Claude Code's response

It should come back with a plan that:

- ✅ Confirms current branch is `phase-1b-pivot`
- ✅ Lists the exact files to delete
- ✅ Pastes the output of the `git grep` anthropic/ANTHROPIC_API_KEY/build_client audit
- ✅ Mentions the test suite will have failures after deletion (expected)
- ✅ Proposes a single commit with a clear message, pushed to `phase-1b-pivot`
- ✅ Does NOT propose implementing matcher.py or patterns/ yet (that's Step 3 onwards)
- ✅ Does NOT propose merging to main at any point


If it tries to do more than Step 1 in one go, push back. Each step lands as its own atomic commit.

## Step-by-step prompts for subsequent steps

Each subsequent step starts a fresh Claude Code session with context from the new planning docs. Approximate prompts:

### Step 2 prompt

> Phase 1B Step 1 is done — LLM-runtime modules deleted, pushed to `phase-1b-pivot`. Now Step 2 per `_planning/PLAN_1B.md`: trim `config.py` and `models.py`, and complete the API-key purge.
>
> Specifically:
>
> 1. Delete `build_client()` from `config.py`. Remove the `anthropic` import from `config.py`.
> 2. Delete the `ConfigError` if it was only used for missing API key (keep it if it's used elsewhere).
> 3. Remove unused models from `models.py`: `Diagnosis`, `GeneratedArtifacts`, `PytestGenOutput`, and any Pydantic models whose only purpose was LLM-response validation.
> 4. Add new models per `ARCHITECTURE_1B.md` "Models changes" section: `Pattern`, `MatchRules`, `Verification`, `MatchResult`, `AuthoringDraft`. Mind the `extra="forbid"` vs `extra="ignore"` discipline.
> 5. After the model/config changes, re-run the audit: `git grep -nE "anthropic|ANTHROPIC_API_KEY|build_client" -- 'src/' 'tests/'`. The ONLY remaining occurrences should be in `pyproject.toml` dependencies (keep `anthropic` as a dep — Step 7 uses it for the authoring tool) and possibly inside `_planning/archive/` (reference material, ignored). If the audit finds any other occurrences in `src/` or `tests/` outside of these, fix them as part of this step.
> 6. Update tests that referenced deleted models. Delete test files that are now entirely about deleted code.
> 7. Run the test suite. Report the delta from Step 1 — some failures from Step 1 should now be resolved, new tests should cover the added models.
>
> Two commits:
> - `Phase 1B step 2a: trim config.py and models.py for runtime` — the deletions
> - `Phase 1B step 2b: add Pattern / MatchResult / AuthoringDraft models` — the additions
>
> Both pushed to `phase-1b-pivot`. Not main. Propose the plan.

### Step 3 prompt

> Steps 1–2 done. Now Step 3: build `src/immunize/matcher.py` plus its tests. Follow `ARCHITECTURE_1B.md` "matcher.py" and "Error class heuristics" sections. The matcher must be pure — no LLM imports, no network. Tests use fixture payloads and fixture patterns; no real patterns loaded yet. Propose the plan.

### Step 4 prompt

> Step 3 done — matcher works against fake test patterns. Now Step 4: create the `src/immunize/patterns/` directory with the FIRST THREE real patterns from `_planning/LAUNCH_LIBRARY.md` (picks 1, 2, 3: react-hook-missing-dep, fetch-missing-credentials, python-none-attribute-access). For Step 4 you may author these three patterns directly since I'm guiding the conversation — but follow `PATTERN_AUTHORING.md` rules exactly. I'll review each pattern's five files (pattern.yaml, SKILL.md, cursor_rule.mdc, test_template.py, fixtures/repro.py, fixtures/fix.py) before you commit. Propose the plan for authoring all three, but plan to stop for my review after each.

### Step 5 prompt

> Step 4 done — three patterns committed. Now Step 5: `scripts/pattern_lint.py` and a CI hook that runs it on every push. The lint must verify YAML shape, required fields, slug format, AND run every pattern's pytest in subprocess to confirm fail-without-fix and pass-with-fix. CI must fail if any pattern regresses. Propose the plan.

### Step 6 prompt

> Step 5 done. Now Step 6: rewrite `cli.py`'s capture orchestrator per `ARCHITECTURE_1B.md`. The new flow: capture → matcher → (if match) verify → inject → done. (if no match) return `{matched: false, can_author_locally: true}` as JSON to the caller. Windows guard stays. Propose the plan.

### Step 7 prompt

> Step 6 done — capture works against bundled patterns. Now Step 7: build the contributor authoring CLI at `src/immunize/authoring/cli_author.py`. This tool DOES import the anthropic SDK — it's the exception, contributor-only, requires ANTHROPIC_API_KEY. It drafts patterns from fixture files and runs verification before saving. Per `PATTERN_AUTHORING.md`. Propose the plan.

### Step 8 prompt

> Step 7 done — contributor authoring tool works. Now Step 8: the bundled `immunize-manager` skill at `src/immunize/skill_assets/immunize-manager/SKILL.md`. Use the exact structure from `ARCHITECTURE_1B.md` "The bundled skill" section. Also update the package's build config to ensure this skill is shipped with the wheel. Propose the plan.

### Step 9 prompt

> Step 8 done — skill shipped. Now Step 9: `src/immunize/authoring/session_author.py` — the Python-side receiver for drafts from Claude Code's session. This module does NOT import anthropic. It receives draft JSON via a new CLI subcommand (`immunize author-local-from-session`), writes to tmp, runs verification, saves on success. Propose the plan.

### Step 10 prompt

> Steps 1–9 done — mechanism is complete. Now Step 10: content sprint. I'll author patterns 4–20 from LAUNCH_LIBRARY.md using `immunize author-pattern`. Your job is to help me one pattern at a time: review each draft the authoring tool produces, catch quality issues per `PATTERN_AUTHORING.md`'s "Ten Commandments", and only commit when I approve. Don't batch-commit. Don't skip review. Let's start with pattern 4 (import-not-found-python). Wait for me to run the authoring tool first.

### Step 11 prompt

> Content sprint done — 15+ patterns committed. Now Step 11: end-to-end integration test. Test uses `CliRunner`, pipes a real CORS fixture into capture, asserts real bundled pattern matches, real verification runs, real files land in a tempdir project. Propose the plan.

### Step 12 prompt

> Step 11 done. Now Step 12: README rewrite and Known Limitations section. New README positions immunize as a pattern library, not an LLM tool. "No API key required" is the tagline. Link to LAUNCH_LIBRARY.md for contributors. Propose the plan.

## After Step 12 — the merge-back-to-main ceremony

Phase 1B is "done" but the work still lives on `phase-1b-pivot`. Do NOT release yet. First, merge the pivot branch into main in a controlled way.

### Step A: Final verification on the pivot branch

Before merging, run all of these on `phase-1b-pivot` and make sure every one is green:

```bash
git checkout phase-1b-pivot
git pull

# 1. All tests pass, all Python versions
pip install -e ".[dev]"
pytest
ruff check .

# 2. Every bundled pattern lints and verifies
python scripts/pattern_lint.py

# 3. End-to-end smoke test with no API key in the environment
unset ANTHROPIC_API_KEY   # prove immunize works without it
cd /tmp
mkdir immunize-final-check && cd immunize-final-check
cat <<EOF > cors_err.json
{"source": "manual", "stderr": "CORS policy: No 'Access-Control-Allow-Credentials' header", "exit_code": 1, "cwd": "/tmp/immunize-final-check", "timestamp": "2026-04-20T00:00:00Z", "project_fingerprint": "abc123"}
EOF
cat cors_err.json | immunize capture --source manual
# Expected: matches bundled pattern, verifies, injects files, exits 0
ls -la .claude/skills/ .cursor/rules/ tests/immunized/
# Expected: three folders/files present
```

If ANY of this fails, fix it on `phase-1b-pivot` before moving on. Do not merge broken code to main.

### Step B: Open a pull request, review the diff yourself

```bash
gh pr create --base main --head phase-1b-pivot \
  --title "Phase 1B: pivot to pattern library + local learning" \
  --body "Closes the LLM-runtime architecture, opens the bundled-patterns era. See _planning/PLAN_1B.md for rationale. $(git log main..phase-1b-pivot --oneline | wc -l) commits."
```

Then go to GitHub, open the PR, and actually read the diff. This is your last chance to catch mistakes before the pivot becomes the canonical history of the project.

**Specifically verify:**
- [ ] No `import anthropic` outside `src/immunize/authoring/cli_author.py` and `scripts/pattern_lint.py`
- [ ] No `ANTHROPIC_API_KEY` references in user-runtime code
- [ ] No `build_client()` references anywhere
- [ ] All 15+ bundled patterns have the five required files
- [ ] README no longer mentions "requires API key" for end users
- [ ] `CHANGELOG.md` has a clear `[Unreleased]` entry describing the pivot

### Step C: Merge to main

Do a merge commit (not a squash) so the full Phase 1B history is preserved on main as a readable sequence:

```bash
# From the PR page on GitHub, click "Create a merge commit" (not squash, not rebase).
# OR from CLI:
git checkout main
git merge --no-ff phase-1b-pivot -m "Merge Phase 1B: pivot to pattern library architecture"
git push origin main
```

After merge, `phase-1b-pivot` has served its purpose. You can delete it locally; keep the remote branch around for reference:

```bash
git branch -d phase-1b-pivot           # local cleanup
# Leave origin/phase-1b-pivot alone — it's cheap storage and useful history
```

### Step D: Release v0.1.0 from main

Now you're ready to ship to PyPI:

```bash
git checkout main
git pull

# Bump version
# Edit pyproject.toml: version = "0.1.0"

git add pyproject.toml
git commit -m "Release v0.1.0"
git push

# Tag and trigger the release
git tag v0.1.0
git push --tags
```

GitHub Actions will build and publish to PyPI via trusted publishing. Verify at https://pypi.org/project/immunize/0.1.0/ about 2 minutes after the tag push.

### Step E: Launch

1. Record the 90-second demo (lead with pattern 2 / fetch-missing-credentials).
2. Draft the Hacker News post. Title: `Show HN: Immunize – a curated library of patterns that stop AI coding assistants from repeating runtime errors (no API key needed)`.
3. Draft the dev.to post explaining the pivot story (this is actually your strongest content — the pivot narrative is rarer and more memorable than just a launch).
4. Launch Tuesday morning US time (7 AM Pacific = 7:30 PM IST).
5. Respond to every comment within 2 hours for the first 48 hours.

### Step F: Celebrate

You built and pivoted a real open-source tool in two weeks of evenings while doing grad school and two internships. Take a day off before responding to issues.

## Final reminders

**Don't let Claude Code sneak old behavior back in.** If it proposes preserving something "for backward compatibility," ask why. The archived branch handles backward compatibility by existing; `phase-1b-pivot` doesn't need to.

**Don't merge `phase-1b-pivot` to main before every check passes.** The pivot exists precisely to keep `main` safe until you know the new architecture works end-to-end. Rushing the merge defeats the point.

**Don't skip reviews in Step 10.** The 20 patterns ARE the product. A pattern that ships broken undermines trust across the whole library.

**Rest between steps.** Phase 1B should take ~5–7 days of evening work, not a single weekend sprint. Pace yourself.

**When the project launches**: come back here. I'll help you with the Hacker News title, the dev.to post, and responding to the hostile comments (there's always at least one).
