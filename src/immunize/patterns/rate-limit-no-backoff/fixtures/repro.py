"""Repro for rate-limit-no-backoff.

AI generated a happy-path API client. The first 429 propagates as
an HTTPError; the script dies mid-loop with no retry, no pause, and
no context beyond the raised exception.
"""

from __future__ import annotations

from typing import Any


def fetch_user(client: Any, user_id: str) -> dict[str, Any]:
    resp = client.get(f"/users/{user_id}")
    resp.raise_for_status()
    return resp.json()
