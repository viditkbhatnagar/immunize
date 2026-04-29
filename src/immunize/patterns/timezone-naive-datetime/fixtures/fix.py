"""Fix for timezone-naive-datetime.

Same interface as repro, but obtains ``now`` as an offset-aware UTC
datetime so the comparison with an offset-aware ``expiry`` is well-defined.
"""

from __future__ import annotations

from datetime import datetime, timezone


def is_token_expired(expiry: datetime) -> bool:
    return datetime.now(timezone.utc) > expiry
