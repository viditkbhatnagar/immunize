"""Fix for python-none-attribute-access.

Same interface as repro, but guards the None return from ``dict.get``
before attribute access.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class User:
    name: str


def lookup_display_name(registry: dict[str, User], user_id: str) -> str:
    user = registry.get(user_id)
    if user is None:
        return "unknown"
    return user.name
