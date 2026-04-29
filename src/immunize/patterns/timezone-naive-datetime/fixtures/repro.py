"""Repro for timezone-naive-datetime.

A token-expiry check that takes an offset-aware datetime from an upstream
API and compares it against ``datetime.now()`` — which is offset-naive.
The comparison raises ``TypeError`` the first time the function meets a
real (aware) input.
"""

from __future__ import annotations

from datetime import datetime


def is_token_expired(expiry: datetime) -> bool:
    return datetime.now() > expiry
