# Contributing to immunize

Thanks for your interest. `immunize` is under active development — the public API will stabilise only at `v0.1.0`. Until then, expect churn.

## Development setup

The project uses plain `pip` + `venv` from the standard library. [`uv`](https://docs.astral.sh/uv/) works as a drop-in replacement if you prefer it — no extra configuration needed.

```bash
git clone https://github.com/viditkbhatnagar/immunize.git
cd immunize
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

This installs `immunize` in editable mode plus the dev extras: `pytest`, `pytest-mock`, `ruff`, `build`, `twine`.

## Common tasks

All covered by the [Makefile](./Makefile):

| Task | Make target | Underlying command |
|---|---|---|
| Run tests | `make test` | `pytest` |
| Lint | `make lint` | `ruff check .` |
| Format | `make format` | `ruff format .` |
| Build wheel + sdist | `make build` | `python -m build` |
| Clean caches + build output | `make clean` | — |

CI runs `ruff check` and `pytest` on every push and PR across Python 3.10, 3.11, and 3.12. Formatting is not enforced in CI yet, but please run `make format` before opening a PR.

## Filing issues

Open an issue at https://github.com/viditkbhatnagar/immunize/issues with:

- A one-paragraph description: what you tried, what happened, what you expected.
- Environment: OS, Python version, `immunize --version` (once the CLI exists), tool the error came from (Claude Code, shell, etc.).
- A minimal reproduction if you can produce one.

## Pull requests

- Branch off `main`.
- One logical change per PR. Unrelated cleanup belongs in a separate PR.
- CI must be green before review.
- Prefer editing existing files over adding new ones. If you're adding a file, say why in the PR description.
- Reviewer: [@viditkbhatnagar](https://github.com/viditkbhatnagar).

## Releases

Only the maintainer ships releases. Specifically:

- **Do not** modify `version` in [pyproject.toml](./pyproject.toml).
- **Do not** create git tags. Tags trigger the PyPI publish pipeline via `.github/workflows/release.yml`.
- **Do not** modify `.github/workflows/release.yml`. If you think it needs a change, open an issue first.

If you find yourself needing a release cadence faster than the maintainer provides, raise it in an issue.

## Code style

- Python 3.10+. Use modern syntax (`|` for unions, `match` where it reads naturally).
- Type hints on every public function and model. Pydantic v2 for data models.
- Keep the dependency surface tight. Anthropic SDK directly — no LangChain, no LlamaIndex, no LangGraph.
- Keep commits atomic and descriptive. One change per commit.

## License

By contributing you agree that your contributions will be licensed under Apache-2.0 (see [LICENSE](./LICENSE)).
