# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] — TBD

Flagship: a Claude Code `PostToolUseFailure` hook that auto-captures bash
failures with zero manual intervention. Run `immunize install-hook` once
and every subsequent failed bash tool call inside Claude Code feeds the
matcher automatically. `immunize run <cmd>` provides the same capture
semantics for shells outside Claude Code.

### Added
- `immunize install-hook` — registers a project-scope PostToolUseFailure
  hook in `.claude/settings.json` that pipes hook payloads to
  `immunize capture --source claude-code-hook`. Idempotent; preserves
  existing hook entries on other events or with other matchers.
- `immunize run <cmd>` — subprocess wrapper that tees stdout/stderr live
  to the terminal via reader threads, captures both buffers, and on
  non-zero exit runs the captured bytes through the matcher. Supports
  `--no-capture`, `--source`, `--timeout` (exits 124 on trip, no
  capture). Passes unknown flags through to the child.
- `capture --source claude-code-hook` — new source mode that reads raw
  Claude Code hook JSON from stdin and translates to CapturePayload.
  Non-Bash tool failures emit `{"outcome": "skipped"}` cleanly.
- `IMMUNIZE_DEBUG_HOOK=1` env opt-in: dumps raw hook payloads to
  `.immunize/hook_payloads/<ts>-<session>.json` for contributor
  calibration work.
- End-to-end hook integration test (`tests/test_hook_integration.py`)
  backed by a real captured payload from Claude Code — schema
  regression-pinned against the observed shape.
- `_planning/MATCHER_CALIBRATION_V020.md` — per-pattern real-world stderr
  samples, before/after recall tables, false-positive audits, and the
  scope limit kept on `missing-env-var`.

### Changed
- `anthropic` moved from hard dependency to the new `[author]` extra.
  Plain `pip install immunize` no longer pulls the SDK (or `httpx`,
  `jiter`, etc.). Contributors install `immunize[author]` to use
  `immunize author-pattern`; end users never need it.
- Matcher recall calibrated against 35+ real-world stderr samples.
  Aggregate recall 12/40 → 38/40 on the sample set; effective
  single-anchor single-line recall in practice 6/7 patterns
  (`missing-env-var` deliberately kept at two-anchor requirement to
  prevent regular-dict KeyError false-positives).
- `settings.min_match_confidence` default lowered 0.70 → 0.30.
  Per-pattern thresholds are now authoritative; raise the setting via
  `IMMUNIZE_MIN_MATCH_CONFIDENCE` for CI strict-mode.
- `guess_error_class` keyword matching moved from plain lowercase
  substring to word-bounded regex. Fixes a latent cross-class collision
  where `ENOTFOUND` substring-matched inside `ModuleNotFoundError`.
- `verify` and `remove` accept a pattern slug OR an integer id. Slug
  resolves via the `artifacts` table; multi-match on `remove` refuses
  to guess and exits 1 with a candidate-id list; multi-match on
  `verify` operates on all (read-only).
- Matcher and CLI threshold comparisons now use a 1e-9 epsilon to
  defeat IEEE 754 precision tripping `0.3 + 0.15 >= 0.45`.
- `immunize-manager` skill rewritten for the hook-first world: tells
  Claude to check `.claude/settings.json` before invoking immunize
  manually, and suggests `immunize run` as the primary fallback.

### Fixed
- Pre-existing v0.1.x bug: the bundled skill told Claude to pipe
  `--source claude-code-session`, which was never in the `Source`
  enum. Every manual capture path from the skill silently failed
  validation at `_VALID_SOURCES`. The skill now uses `--source manual`.

## [0.1.1] — 2026-04-18

### Fixed
- `immunize --help` (and every other CLI command) crashed on fresh
  installs with `TypeError: Parameter.make_metavar() missing 1
  required positional argument: 'ctx'`. Root cause: Click 8.2 made
  `ctx` a required positional, and Typer <0.15 calls it without
  `ctx`. Our dependency pin (`typer>=0.12`, no Click pin) allowed
  pip to resolve the broken combo. Pinned `typer>=0.15` and
  `click>=8.1.7`.

## [0.1.0] — 2026-04-18

First real release. `immunize` ships as a deterministic, offline pattern
library that stops AI coding assistants from repeating common runtime
errors. No API key required at user-runtime.

### Added
- Deterministic pattern matcher (`src/immunize/matcher.py`) — regex + error-class
  heuristics; no runtime LLM calls, no API key required.
- 7 bundled patterns covering common AI-coding runtime errors:
  `react-hook-missing-dep`, `fetch-missing-credentials`,
  `python-none-attribute-access`, `import-not-found-python`,
  `missing-env-var`, `rate-limit-no-backoff`,
  `async-fn-called-without-await`.
- `immunize capture` — matches → verifies (pytest subprocess) → injects
  a Claude Code skill, a Cursor rule, and a pytest regression test into
  the caller's repo. Atomic per-file replace.
- `immunize list` / `immunize verify` / `immunize remove` — manage
  installed immunities.
- `immunize install-skill` — installs the bundled `immunize-manager`
  Claude Code skill into `<project>/.claude/skills/immunize-manager/`.
- `immunize author-pattern` — contributor-only CLI that uses the
  Anthropic API to draft new patterns from a `CapturePayload` JSON;
  verification runs before save. Requires `ANTHROPIC_API_KEY`; end
  users never do. The `anthropic` import is lazy, scoped to this
  command only — the `capture`, `list`, `verify`, and `remove` code
  paths never touch the SDK.
- Bundled `immunize-manager` skill teaches Claude Code when and how to
  invoke `immunize` on failing commands.
- `scripts/pattern_lint.py` CI gate — every bundled pattern must pass
  `pytest` and YAML shape checks or the build fails.
- End-to-end integration test (`tests/test_e2e_capture.py`) proving
  capture → match → verify → inject on a real bundled pattern with
  no network.

### Changed
- Pivoted from the original LLM-at-runtime design. The previous
  architecture lives on the `phase1-llm-runtime-archive` branch for
  reference. See [_planning/PLAN_1B.md](./_planning/PLAN_1B.md) for the
  full rationale.

### Removed
- `diagnose.py`, `generate/skill.py`, `generate/pytest_gen.py`,
  `generate/semgrep.py`, and the `Diagnosis` / `GeneratedArtifacts` /
  `ErrorClass` models. Runtime LLM calls were replaced by the
  deterministic pattern library.

### Known limitations
- POSIX-only. Windows support planned for v0.2+.
- Verification runner is Python pytest for every pattern — JS/TS
  patterns verify via regex source scanning rather than native test
  runners. Native runners (Jest, Go test, cargo test) are a v0.3 goal.
- No community pattern registry; patterns ship in the package and new
  ones land via `pip install --upgrade immunize`.

## [0.0.1] — 2026-04-17

Initial PyPI name reservation. Not a real release — empty metadata only. Do not install.
