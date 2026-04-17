"""Fix for async-fn-called-without-await.

Same interface as repro. The single added ``await`` resolves
``fetch_value()`` to its int return value before the arithmetic.
"""

from __future__ import annotations


async def fetch_value() -> int:
    return 21


async def compute_total() -> int:
    value = await fetch_value()
    return value * 2
