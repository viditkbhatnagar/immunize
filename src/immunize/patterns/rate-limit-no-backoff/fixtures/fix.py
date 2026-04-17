"""Fix for rate-limit-no-backoff.

Same interface as repro. Adds a bounded retry loop with exponential
backoff on 429: the caller eventually sees the 200 payload once the
transient limit clears, or a final HTTPError after max attempts.
"""

from __future__ import annotations

import time
from typing import Any

_MAX_ATTEMPTS = 4


def fetch_user(client: Any, user_id: str) -> dict[str, Any]:
    resp = None
    for attempt in range(_MAX_ATTEMPTS):
        resp = client.get(f"/users/{user_id}")
        if resp.status_code != 429:
            break
        time.sleep(2**attempt)
    assert resp is not None
    resp.raise_for_status()
    return resp.json()
