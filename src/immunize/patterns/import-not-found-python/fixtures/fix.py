"""Fix for import-not-found-python.

Same interface as repro, but the hallucinated ``_ghost_utils`` module
is replaced with stdlib ``re`` — no extra dependency needed.
"""

from __future__ import annotations

import re


def make_slug(title: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", title.lower())
    return cleaned.strip("-")
