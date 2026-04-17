"""Repro for python-none-attribute-access.

Defines a small user registry with a lookup function that crashes when
the requested key is missing — the AI forgot to handle the None return
from ``dict.get``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class User:
    name: str


def lookup_display_name(registry: dict[str, User], user_id: str) -> str:
    user = registry.get(user_id)
    return user.name
