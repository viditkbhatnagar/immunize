# skill_assets

Static markdown shipped inside the `immunize` wheel so end-users can drop
Claude Code skills into their own projects without copying files by hand.

## Layout

```
skill_assets/
└── immunize-manager/
    └── SKILL.md     # the bundled skill that teaches Claude Code to invoke immunize
```

Each direct subdirectory is one installable skill. Today there is exactly
one (`immunize-manager`); more may appear in future phases.

## How it ships

Hatchling's `[tool.hatch.build.targets.wheel]` in `pyproject.toml` declares
`packages = ["src/immunize"]`, which recursively includes every file under
the package tree — `.md`, `.yaml`, `.py`, etc. No `force-include` or
`MANIFEST.in` is needed. See `tests/test_skill_assets.py::test_wheel_ships_skill`
for the regression guard.

## How users consume it

```bash
immunize install-skill                      # → cwd/.claude/skills/immunize-manager/SKILL.md
immunize install-skill --project-dir PATH   # install into PATH instead of cwd
immunize install-skill --force              # overwrite existing content
```

The implementation lives in `src/immunize/skill_install.py` and resolves
the bundled markdown via `importlib.resources.files("immunize")`, so it
works in editable (`pip install -e`) and wheel installs alike.

## Editing a bundled skill

1. Edit the markdown in place (e.g. `immunize-manager/SKILL.md`).
2. Keep the `---`-fenced YAML frontmatter valid — `name` and `description`
   are required. `tests/test_skill_assets.py::test_frontmatter_valid`
   enforces this.
3. Preserve the section headings listed in
   `test_required_body_sections`; Claude Code relies on them.
4. Run `pytest tests/test_skill_assets.py` before committing.
