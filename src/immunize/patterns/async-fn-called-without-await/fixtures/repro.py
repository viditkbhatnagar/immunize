"""Repro for async-fn-called-without-await.

AI forgot the ``await``. ``fetch_value()`` returns a coroutine
object, not an int; multiplying the coroutine by 2 raises TypeError
at runtime, and the abandoned coroutine emits a RuntimeWarning on
garbage collection.
"""

from __future__ import annotations


async def fetch_value() -> int:
    return 21


async def compute_total() -> int:
    value = fetch_value()  # missing await
    return value * 2  # type: ignore[operator]
