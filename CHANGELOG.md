# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
