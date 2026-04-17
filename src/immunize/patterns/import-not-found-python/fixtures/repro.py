"""Repro for import-not-found-python.

AI hallucinated a helper module and wrote a lazy import. The module
loads fine — the ModuleNotFoundError fires the first time
``make_slug`` is called, exactly as it would in production.
"""

from __future__ import annotations


def make_slug(title: str) -> str:
    from _ghost_utils import slugify  # module does not exist

    return slugify(title)
