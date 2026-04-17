# Contributing to immunize

Thanks for your interest. `immunize` is an open-source pattern library that stops AI coding assistants from repeating common runtime errors. Contributions that expand the pattern library, sharpen the matcher, or improve the developer experience are all welcome.

Assumes you're a competent developer comfortable with Python, Git, and pytest. When in doubt, open an issue before writing code — I'd rather spend five minutes on alignment than have you rework a PR.

## Development setup

The project uses plain `pip` + `venv`. [`uv`](https://docs.astral.sh/uv/) works as a drop-in replacement.

```bash
git clone https://github.com/viditkbhatnagar/immunize.git
cd immunize
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
```

This installs `immunize` in editable mode plus the dev extras (`pytest`, `pytest-mock`, `ruff`, `build`, `twine`) and wires up the pre-commit hook that runs `ruff` on every staged change.

## Common tasks

Most daily commands have a [Makefile](./Makefile) target:

| Task | Make target | Underlying command |
|---|---|---|
| Run the full test suite | `make test` | `pytest` |
| Lint | `make lint` | `ruff check .` |
| Format | `make format` | `ruff format .` |
| Build wheel + sdist | `make build` | `python -m build` |
| Clean caches + build output | `make clean` | — |

Pattern-library-specific:

```bash
python scripts/pattern_lint.py    # validates every bundled pattern end-to-end
```

`pattern_lint.py` is a CI gate. Each bundled pattern's pytest runs in a subprocess against a scratch project; if any pattern's verified fix no longer passes, the script exits non-zero and CI fails. Run it locally before opening a pattern PR.

## Authoring a new pattern

The authoring workflow has two paths. Both end with the same five-file shape on disk and must satisfy the ["Ten Commandments"](./_planning/PATTERN_AUTHORING.md#the-ten-commandments-of-good-patterns) in [_planning/PATTERN_AUTHORING.md](./_planning/PATTERN_AUTHORING.md) before merging.

### Path 1 — LLM-assisted (`immunize author-pattern`)

`immunize author-pattern` is a contributor-only CLI that uses the Anthropic API to draft pattern files from a real error and runs verification before saving. It requires an API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
immunize author-pattern \
    --from-error path/to/error.json \
    --output src/immunize/patterns/
```

- `--from-error` takes a `CapturePayload`-shaped JSON file — a real error you want to build a pattern from. Any payload captured by `immunize capture` (look for unmatched captures under `.immunize/` or construct one by hand matching the shape in [src/immunize/models.py](./src/immunize/models.py)) works here.
- `--output` is the parent directory where the new pattern directory will be created. The tool picks the slug and writes the full five-file layout underneath it.

This is the fastest way to produce a first draft. The draft still needs human review — the Ten Commandments exist precisely because LLM-generated patterns can be subtly wrong.

**End users never run this.** `author-pattern` is a developer tool. The shipped pattern library is fully deterministic and needs no API key at user-runtime.

### Path 2 — manual

Every pattern is just a directory under [src/immunize/patterns/](./src/immunize/patterns/) with five files:

```
<slug>/
  pattern.yaml        # metadata: id, language, error class, match rules, verification
  SKILL.md            # the Claude Code skill that teaches the model to avoid this error
  cursor_rule.mdc     # the equivalent Cursor rule
  test_template.py    # the pytest that proves fix-passes / repro-fails
  fixtures/
    repro.py          # the bug form
    fix.py            # the corrected form
```

Copy an existing pattern (e.g. [python-none-attribute-access](./src/immunize/patterns/python-none-attribute-access/)) as a starting point and adapt. Run `python scripts/pattern_lint.py` locally to confirm the pattern passes before opening a PR.

### Review checklist

Read PATTERN_AUTHORING.md's Ten Commandments in full before submitting, but the common failure modes to self-check against are:

1. Does the pytest actually *fail* without the fix and *pass* with it? (Not the same as "runs clean".)
2. Is `pattern.yaml`'s `match_rules` regex tight enough to avoid false positives on unrelated errors?
3. Does `SKILL.md` tell Claude Code what to do *next time* (prevention), not just what the bug was (diagnosis)?
4. Is the slug stable? (Used for filenames, skill IDs, storage keys — renaming later is a breaking change.)

## PR requirements

- **One pattern per PR** is strongly preferred. Bundle unrelated patterns separately; reviewers need to reason about each pattern's correctness independently.
- **CI must be green** before review. That means `pytest`, `ruff check .`, and `python scripts/pattern_lint.py` all pass.
- **One logical change per PR** for non-pattern work too. Unrelated cleanup belongs in a separate PR.
- **Atomic commits with descriptive messages.** Prefer many small commits over one large squash. The `Phase 1B step N:` prefix is a maintainer convention — use plain descriptive prefixes for your PRs.
- **Prefer editing existing files over adding new ones.** If you're adding a file, say why in the PR description.
- Reviewer: [@viditkbhatnagar](https://github.com/viditkbhatnagar).

## Filing issues

Open an issue at https://github.com/viditkbhatnagar/immunize/issues with:

- A one-paragraph description: what you tried, what happened, what you expected.
- Environment: OS, Python version, `immunize --version`, which tool the error came from (Claude Code, Cursor, manual).
- A minimal reproduction if you can produce one — ideally a JSON capture payload that demonstrates the mis-match or mis-inject.

For proposed new patterns, the issue template is even simpler: the failing command's stderr, the correct fix, and why you think it's a recurring AI-coding mistake rather than a one-off bug.

## Releases

Only the maintainer ships releases. Specifically:

- **Do not** modify `version` in [pyproject.toml](./pyproject.toml).
- **Do not** create git tags. Tags trigger the PyPI publish pipeline via `.github/workflows/release.yml`.
- **Do not** modify `.github/workflows/release.yml`. If you think it needs a change, open an issue first.

If you find yourself needing a release cadence faster than the maintainer provides, raise it in an issue.

## Code style

- Python 3.10+. Use modern syntax (`|` for unions, `match` where it reads naturally).
- Type hints on every public function and model. Pydantic v2 for data models.
- Keep the dependency surface tight. The user-runtime tree has zero LLM dependencies at all. The Anthropic SDK is used only by the contributor `author-pattern` tool (kept behind a lazy import boundary). No LangChain, no LlamaIndex, no orchestration frameworks.
- Keep commits atomic and descriptive.

## License

By contributing you agree that your contributions will be licensed under Apache-2.0 (see [LICENSE](./LICENSE)).
