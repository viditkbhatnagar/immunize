---
name: immunize-timezone-naive-datetime
description: Use when writing Python code that calls datetime.now() or datetime.utcnow() and compares the result against a datetime that came from outside the process (HTTP API, database, JWT claim, etc.).
---

# timezone-naive-datetime

Always construct datetimes as offset-aware in UTC. Mixing naive and aware
datetimes in a comparison or subtraction raises:

    TypeError: can't compare offset-naive and offset-aware datetimes

Datetimes that arrive from outside the process — JSON `expires_at`
fields, JWT `exp` claims, database `TIMESTAMPTZ` columns, RFC 3339
strings parsed with `fromisoformat` — are aware. Datetimes you create
inside the process must match.

## Example

Wrong — `datetime.now()` returns a naive datetime; the comparison crashes:

```python
from datetime import datetime

def is_token_expired(expiry: datetime) -> bool:
    return datetime.now() > expiry
```

Right — pass `timezone.utc` so the local datetime is aware:

```python
from datetime import datetime, timezone

def is_token_expired(expiry: datetime) -> bool:
    return datetime.now(timezone.utc) > expiry
```

## Don't reach for `datetime.utcnow()`

`datetime.utcnow()` returns a *naive* datetime whose value happens to be
in UTC — it carries no `tzinfo`. Comparing it with an aware datetime
raises the same TypeError, and the function is deprecated as of Python
3.12. Use `datetime.now(timezone.utc)` instead.

## Parsing aware datetimes

When reading external timestamps:

- ISO 8601 with `Z` or `+00:00`: `datetime.fromisoformat(s.replace("Z", "+00:00"))`
- POSIX timestamps: `datetime.fromtimestamp(ts, tz=timezone.utc)`
- Database driver: prefer `TIMESTAMPTZ` over `TIMESTAMP` and let the
  driver return aware values.

## Immunity note

The verification asserts that the fixture's expiry check accepts an
aware `datetime` without crashing. The repro raises `TypeError`; the fix
returns the boolean the consumer expects. The interface is unchanged.
