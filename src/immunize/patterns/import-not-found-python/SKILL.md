---
name: immunize-import-not-found-python
description: Use when writing Python imports to verify the module and symbol exist at the claimed path before committing the line.
---

# import-not-found-python

Before writing `from X import Y`, verify the module exists at that
exact path and the symbol is exported. When AI drafts Python code
from memory, it often invents plausible-sounding module names or
guesses wrong sub-paths, and the first call explodes:

    ModuleNotFoundError: No module named '_ghost_utils'
    ImportError: cannot import name 'slugify' from 'myapp.utils'

## Example

Wrong — module does not exist; lazy-imported inside a helper:

```python
def make_slug(title: str) -> str:
    from _ghost_utils import slugify
    return slugify(title)
```

Right — use a real import. Stdlib often suffices:

```python
import re

def make_slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
```

## How to verify before committing

- Check the module if it is third-party: `pip show <module>`.
- Check the symbol is exported: read the module's `__init__.py` or
  `__all__`, or grep the source for `def <symbol>`.
- Prefer explicit package paths (`from myapp.utils.text import slugify`)
  over guessable short names (`from utils import slugify`) — shorter
  paths collide across projects and invite hallucination.
- If the symbol is genuinely internal, re-export it deliberately
  through `__init__.py` rather than reaching into implementation
  modules.

## Don't paper over with try/except

```python
try:
    from _ghost_utils import slugify
except ImportError:
    slugify = lambda s: s  # silent fallback — hides the typo forever
```

A silent fallback turns a crash at startup into a broken behavior at
runtime. If the dependency is genuinely optional, raise a clear
`ConfigError` naming what to install; never fall back to a stub that
looks like success.
