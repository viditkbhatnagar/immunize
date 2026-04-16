# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Real `pyproject.toml` replacing the name-reservation placeholder: hatchling backend, Python 3.10+, real dependency set (typer, rich, anthropic, pydantic, pyyaml), dev extras (pytest, pytest-mock, ruff, build, twine), `immunize` console script entry point, ruff and pytest configuration.
- Apache-2.0 `LICENSE` with 2026 copyright.
- `README.md` describing the project, status, and planned install flow; links to the planning documents.
- `.gitignore` covering virtualenvs, caches, build output, local `.immunize/` state, and `.env` files.
- Empty project layout under `src/immunize/` (including `generate/` and `skill_assets/immunize-manager/`), `hooks/`, `tests/fixtures/`, and `docs/`, per `_planning/SPEC.md`.
- Smoke test at `tests/test_smoke.py` so CI runs a real assertion until Phase 1 delivers real tests.
- `.github/workflows/ci.yml` — ruff and pytest on every push and pull request across Python 3.10, 3.11, and 3.12.
- `.github/workflows/release.yml` — PyPI publish on `v*` tags via trusted publishing.
- `CONTRIBUTING.md` covering setup, common tasks, issue and PR guidance, and release discipline.
- `CHANGELOG.md` (this file).
- `Makefile` with `install`, `test`, `lint`, `format`, `build`, `clean` targets.

## [0.0.1] — 2026-04-17

Initial PyPI name reservation. Not a real release — empty metadata only. Do not install.
