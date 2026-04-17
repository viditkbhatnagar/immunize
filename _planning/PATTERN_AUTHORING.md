# Pattern Authoring Workflow

> This is the playbook for writing bundled patterns for `immunize`. Since the pattern library IS the product, the quality of each pattern matters more than code quality. Follow this doc carefully when adding a pattern.

## Who uses this

- **You (Vidit)** — authoring the initial 15–20 patterns for v0.1.
- **Community contributors** — adding patterns via PR post-launch.
- **Claude Code** — when reading this plan, to understand what "good pattern" means.

## The 20-30 minute pattern authoring loop

### Step 1: Find or capture a real error

Good patterns come from real errors, not imagined ones. Two ways to source:

**a) From your own coding history**
When Claude Code makes a mistake in your own work, save the error JSON:

```bash
# Redirect the error to a fixture file
npm run dev 2> /tmp/my-error.txt
# Then hand-wrap into a CapturePayload-shaped JSON
immunize capture --from-stderr-file /tmp/my-error.txt --save-fixture > patterns-to-write/error-N.json
```

**b) From the launch library list**
`LAUNCH_LIBRARY.md` has 20 hand-picked error classes to cover for v0.1. Work through them in order. Each entry names the error, the language, and a suggested test approach.

### Step 2: Run the authoring tool

```bash
# Requires your ANTHROPIC_API_KEY (only at authoring time, not at user-runtime)
export ANTHROPIC_API_KEY=sk-ant-...

immunize author-pattern \
  --from-error patterns-to-write/error-N.json \
  --output src/immunize/patterns/
```

The tool will:

1. Send the error to Claude for diagnosis (~$0.003).
2. Propose a slug and error class.
3. Draft SKILL.md, Cursor rule, pytest test, repro snippet, and fix snippet (~$0.02).
4. Write them to a scratch directory.
5. Run the pytest verifier in a subprocess.
6. If verified, move them into `src/immunize/patterns/<slug>/`.
7. If not verified, retry once with a stricter prompt. On second failure, dump to `.immunize/rejected/` and print diagnostics.

Total per-pattern authoring cost: ~$0.03.
Total budget for 20 patterns: ~$0.60.

### Step 3: Review the draft by hand

**This step is critical. Do NOT skip it.**

Open each of the five files the tool created:

```
src/immunize/patterns/<slug>/
├── pattern.yaml
├── SKILL.md
├── cursor_rule.mdc
├── test_template.py
└── fixtures/
    ├── repro.py
    └── fix.py
```

Read each one with a critical eye. Specifically check:

**pattern.yaml**
- Is the `id` semantic and specific? (`cors-missing-credentials` good, `error-1` bad.)
- Are the `stderr_patterns` regex strings correct and reasonably scoped? (Too narrow misses matches; too broad causes false positives.)
- Is the `error_class` correct?
- Are the `languages` accurate?
- Is `min_confidence: 0.70` right for this pattern? (Common errors: keep at 0.70. Very specific errors: lower to 0.60. Highly ambiguous errors: raise to 0.80.)

**SKILL.md**
- Is the frontmatter valid? (`name:` matches `immunize-<slug>`, `description:` is present and accurate.)
- Is the body actionable? (Specific code examples, not vague advice.)
- Is it under 400 words? (Long skills degrade attention; trim if needed.)
- Does it teach the right intuition? (A good skill teaches the *why*, not just the *how*.)

**cursor_rule.mdc**
- Frontmatter has `description:`, `globs:`, `alwaysApply: false`.
- Globs cover the right languages per the hardcoded `LANGUAGE_GLOBS` map.
- Body is substantially the same as SKILL.md's body (derived deterministically, no drift).

**test_template.py**
- Reads `repro.py` or `fix.py` from the `fixtures/` sibling at test time.
- Is genuinely testing the bug, not just assert True.
- Uses stdlib + pytest + unittest.mock only. No network, no external fixtures.
- Uses tmp_path for any file IO.

**fixtures/repro.py and fixtures/fix.py**
- repro.py reproduces the bug when imported/run under pytest.
- fix.py is the minimal correct version.
- When test_template.py runs against fix.py it passes. Against repro.py it fails. This is re-verified automatically by the authoring tool but spot-check by eye.

### Step 4: Run the local verifier

The authoring tool verified once in a scratch directory. Before committing, re-verify with the repository's real test runner:

```bash
pytest scripts/pattern_lint.py::test_pattern_verifies --pattern-id=<slug> -v
```

This runs the same verification but using the committed files (not scratch), catching any subtle path-resolution issues.

### Step 5: Commit and PR

One pattern per commit. Commit message format:

```
Add pattern: <slug> (<error_class>/<language>)

Example error: <one-line description>
```

For v0.1, you're committing directly to main. Post-launch, contributors open PRs and you review.

## The ten commandments of good patterns

1. **A pattern earns its slug.** Generic names like "error-1" or "cors-fix" are rejected. Slugs must name the specific failure mode: `cors-missing-credentials`, `react-hook-missing-dep`, `fastapi-async-in-sync-route`.

2. **Patterns test defaults, not knobs.** The pytest must call the module the way a production consumer would — with defaults in play. Passing the buggy parameter explicitly is wrong; it hides the bug.

3. **repro.py and fix.py must differ observably when called identically.** If the same test code produces the same behavior against both, the pattern is broken.

4. **Stderr regex anchors on signal, not noise.** Match on the actual error identifier (`Access-Control-Allow-Credentials`), not generic English ("error occurred").

5. **Keep `min_confidence` honest.** If a pattern has only one stderr regex and it's a common English phrase, that's a low-confidence signal — set `min_confidence: 0.75+`. If it has three specific regexes, 0.70 is fine. Never tune confidence to "make the test pass in demos."

6. **SKILL.md teaches, doesn't lecture.** Open with what the AI should DO next time. End with one code example. That's it. No essays.

7. **No URLs in SKILL.md.** (Links rot. Principles don't.)

8. **Languages list is precise.** If the pattern is JavaScript-specific, don't also tag TypeScript "for coverage." TypeScript has type-system-specific errors that deserve their own patterns.

9. **Never wrap domain knowledge in a pattern.** "React useState infinite loop" is a good pattern. "Best practices for React" is not — too broad, can't verify.

10. **If the test is flaky, the pattern is wrong.** A pattern that verifies 80% of the time isn't shipped. Either the test is wrong (re-author) or the bug is nondeterministic (abandon; some bugs aren't pattern-able).

## Common authoring failure modes and their fixes

### The test is behaviorally trivial

Symptom: the test passes both with repro and with fix.

Cause: the test overrides the parameter the fix is meant to change.

Fix: rewrite the test to call the module with defaults only. If the bug involves a default value, the test must not pass that parameter explicitly.

### The stderr regex matches too many unrelated errors

Symptom: false positives during testing — the pattern applies to errors it shouldn't.

Fix: add a second, more specific regex to the `stderr_patterns` list. The matcher scores OR logic, but adding more signals raises confidence for true matches more than for false ones.

### The SKILL.md is generic

Symptom: reads like documentation; could apply to a whole category of errors rather than this specific one.

Fix: rewrite focused on the one thing the AI must remember. One sentence. One code example. Delete everything else.

### The pattern only works in one environment

Symptom: verifies on your Mac but fails on CI Linux.

Fix: stop depending on env-specific behavior. Mock network, mock filesystem paths, use tmp_path. If the bug is environment-specific, document that in pattern.yaml with a clear `constraints:` block (optional in v0.1; we'll add it formally if needed).

## How the local-learning workflow differs

When the user's Claude Code session drafts a local pattern (per `ARCHITECTURE_1B.md`), most of the above still applies, but with two important differences:

1. **The contributor is Claude Code, not you.** The drafting quality depends on Claude's in-session work. The bundled skill is engineered to guide it well, but some drafts will fail verification. That's fine — the user just tells Claude "try again" and iterates.

2. **The verification runs on the user's machine immediately.** There's no separate CI step. A local pattern that verifies on the user's machine is sufficient for local use. It never ships with the package unless the user opens an upstream PR.

3. **Local patterns have `origin: local` in their pattern.yaml.** This distinguishes them from bundled patterns in `immunize list` and in SQLite records.

## Pattern library growth cadence

### For v0.1 launch

Ship with 15–20 patterns. See `LAUNCH_LIBRARY.md` for the priority list.

### For v0.2 (first month after launch)

Target 30–40 patterns. Sources:
- Community PRs (should start arriving within a week of a successful launch)
- Your own captured errors from real work
- Feedback from GitHub issues: "it didn't recognize this error"

### For v0.3 (quarter after launch)

Target 75+ patterns. Consider adding:
- `pattern_lint.py` enhancements (e.g., check for duplicate patterns covering the same error)
- A `contrib/` directory for experimental/community-review patterns
- Pattern categories surfaced in `immunize list --category cors`

## The quality bar for bundled patterns

Every pattern in `src/immunize/patterns/` must:

- ✅ Lint clean in `pattern_lint.py` (YAML shape, required fields, slug format).
- ✅ Verify green (pytest fails without fix, passes with fix, reproducible in CI).
- ✅ Have human-reviewed SKILL.md and pattern.yaml (automated drafts are only the starting point).
- ✅ Be tested against at least one realistic error fixture in `tests/patterns/`.

Community PRs that fail any of these get a review comment explaining what's needed, not an immediate rejection. Coaching contributors is part of running the library.

## What to tell Claude Code about pattern authoring

Claude Code will implement the `immunize author-pattern` CLI in Phase 1B Step 7. Make sure it understands:

- The tool's purpose is to help you and contributors draft patterns on your own machines. It REQUIRES `ANTHROPIC_API_KEY`, unlike the user-runtime code which forbids it.
- The tool must ALWAYS run verification before saving a pattern. Unverified drafts go to `.immunize/rejected/`, never to `src/immunize/patterns/`.
- The tool must produce human-readable diagnostics when a draft fails to verify so you can iterate.
- The tool must NEVER auto-commit or auto-push. It writes files; you review and commit.
