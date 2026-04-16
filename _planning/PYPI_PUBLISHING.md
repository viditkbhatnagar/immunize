# Publishing `immunize` to PyPI

Complete guide from zero to `pip install immunize`. Free for everyone. No approval required.

## Quick answers

- **Cost:** Free. PyPI is run by the Python Software Foundation as a non-profit service.
- **Who can publish:** Anyone with a verified email.
- **How long until it's live:** Usually under 60 seconds after `twine upload`.
- **Can the name be taken while I build?** Yes. Reserve it this week by publishing a placeholder (see below).
- **Approval process?** None. You publish, it's live.

## Step 1 — Create PyPI and TestPyPI accounts

1. Go to https://pypi.org/account/register/ and create an account.
2. Verify your email.
3. Enable 2FA (required for all accounts since 2024). Use a TOTP app like Aegis or 1Password.
4. Repeat for TestPyPI at https://test.pypi.org/account/register/. This is the sandbox you'll use to dry-run releases before going to production PyPI.

**Tip:** Use the same username on both. Makes things easier.

## Step 2 — Reserve the name `immunize` with a placeholder (do this in the first week)

You want the name locked in so nobody else grabs it while you build. Ship a minimal `0.0.1` placeholder now.

Create a tiny project:

```
immunize-placeholder/
├── pyproject.toml
└── README.md
```

**`pyproject.toml`:**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "immunize"
version = "0.0.1"
description = "Under active development. Real 0.1.0 release coming soon."
readme = "README.md"
requires-python = ">=3.10"
license = { text = "Apache-2.0" }
authors = [{ name = "Vidit Bhatnagar" }]

[project.urls]
Homepage = "https://github.com/viditkbhatnagar/immunize"

[tool.hatch.build.targets.wheel]
bypass-selection = true
```

**`README.md`:** One line. "Under active development — real release coming soon. See https://github.com/viditkbhatnagar/immunize."

Then publish:

```bash
pip install build twine
python -m build
python -m twine upload dist/*
```

You'll be prompted for an API token (see Step 3). Once uploaded, the name `immunize` is permanently yours as long as you publish at least once a year.

## Step 3 — Set up authentication

Two options, both free:

### Option A: API token (simplest for first publish)

1. Go to https://pypi.org/manage/account/token/
2. Create a token scoped to "Entire account" for the first upload. After your first publish, regenerate it scoped to just the `immunize` project.
3. Save it somewhere safe (password manager). PyPI only shows it once.
4. Configure `~/.pypirc`:

```ini
[pypi]
username = __token__
password = pypi-AgENdGVzdC5weXBpLm9yZwIkZDE...  # your token

[testpypi]
repository = https://test.pypi.org/legacy/
username = __token__
password = pypi-AgENdGVzdC5weXBpLm9yZwIkZDE...  # separate TestPyPI token
```

Permission `chmod 600 ~/.pypirc` so others on the system can't read it.

### Option B: Trusted Publishing via GitHub Actions (recommended for real releases)

More secure — no long-lived tokens. Ties publishing to a specific GitHub repo + workflow.

1. Go to https://pypi.org/manage/account/publishing/
2. Add a "pending publisher" with:
   - PyPI project name: `immunize`
   - Owner: `viditkbhatnagar`
   - Repository name: `immunize`
   - Workflow name: `release.yml`
   - Environment name: `pypi` (optional but recommended)
3. In your repo, create `.github/workflows/release.yml`:

```yaml
name: Release to PyPI

on:
  push:
    tags:
      - 'v*'

permissions:
  contents: read

jobs:
  build-and-publish:
    runs-on: ubuntu-latest
    environment:
      name: pypi
      url: https://pypi.org/p/immunize
    permissions:
      id-token: write  # required for trusted publishing
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install build tools
        run: python -m pip install build

      - name: Build distributions
        run: python -m build

      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
```

After that, every `git tag v0.2.0 && git push --tags` automatically publishes to PyPI. Zero manual steps.

## Step 4 — The real release (Phase 4 of the build plan)

Once `immunize` 0.1.0 is actually ready:

### Option A: Manual publish

```bash
# Make sure your pyproject.toml version says 0.1.0
rm -rf dist/ build/ *.egg-info
python -m build
python -m twine check dist/*   # catches common metadata issues
python -m twine upload --repository testpypi dist/*   # dry-run to TestPyPI first

# Verify on TestPyPI
pip install -i https://test.pypi.org/simple/ immunize
# smoke test it, then:

python -m twine upload dist/*   # the real thing
```

### Option B: GitHub tag-triggered (if you set up trusted publishing)

```bash
git tag v0.1.0
git push --tags
```

Watch GitHub Actions. PyPI will have it live in ~2 minutes.

## Version bumping strategy

Follow SemVer:
- `0.0.x` — placeholder, throwaway.
- `0.1.0` — first real usable release.
- `0.1.x` — bug fixes.
- `0.2.0` — first feature additions after launch (git team tier polish, etc.).
- `1.0.0` — only when the API is stable and you're committed to backwards compatibility.

For pre-release testing, use `0.2.0a1`, `0.2.0b1`, `0.2.0rc1`. Install with `pip install --pre immunize`.

## Common gotchas

1. **Name conflicts with normalized forms.** PyPI normalizes names: `immunize`, `Immunize`, `IMMUNIZE`, `im-mu-nize` all collide. Use exactly `immunize` everywhere.
2. **Description too long / markdown not rendering.** Set `readme = "README.md"` and ensure the README is under ~200KB.
3. **Missing classifiers.** PyPI won't reject you but the project page looks unprofessional without them. The `pyproject.toml` in SPEC.md includes good defaults.
4. **Forgot to bump version.** Uploading the same version twice is rejected. Bump before each upload.
5. **Old wheels in dist/.** Always `rm -rf dist/` before `python -m build`, or twine will upload stale files.
6. **2FA on by default.** If you forget to set up TOTP before publishing, you'll be locked out of the UI. Use an API token / trusted publishing and you're fine either way.

## Post-publish housekeeping

1. Add a PyPI badge to your README:
   ```markdown
   [![PyPI](https://img.shields.io/pypi/v/immunize.svg)](https://pypi.org/project/immunize/)
   [![Downloads](https://static.pepy.tech/badge/immunize)](https://pepy.tech/project/immunize)
   ```
2. Watch download stats at https://pepy.tech/project/immunize (3rd-party, more reliable than PyPI's own stats).
3. Add a GitHub release with changelog every time you publish a tagged version.

## What PyPI doesn't do for you

- It doesn't promote your package. Launch on Hacker News, Reddit r/Python, Twitter / X, and dev.to.
- It doesn't guarantee quality. Your users will.
- It doesn't handle issues or PRs — those are on GitHub.
- It won't warn you if a dependency you ship is vulnerable. Use `pip-audit` or GitHub Dependabot.

## Your first-week checklist

- [ ] Create PyPI + TestPyPI accounts with 2FA.
- [ ] Create GitHub repo at `github.com/viditkbhatnagar/immunize`.
- [ ] Publish `0.0.1` placeholder to reserve the name.
- [ ] Set up trusted publishing for future releases.
- [ ] Start building v0.1.0 per PLAN.md.

That's it. PyPI is refreshingly simple once you've done it once.
