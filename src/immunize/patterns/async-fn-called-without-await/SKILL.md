---
name: immunize-async-fn-called-without-await
description: Use when calling an async def function from Python to ensure every call is awaited before its return value is used as the resolved result.
---

# async-fn-called-without-await

Every `async def` call returns a coroutine object, not the value the
body produces. Using that coroutine as if it were the resolved value
raises a TypeError at runtime, and Python also emits a warning when
the unused coroutine is garbage-collected:

    TypeError: unsupported operand type(s) for *: 'coroutine' and 'int'
    RuntimeWarning: coroutine 'fetch_value' was never awaited

Both signals point at the same bug: a missing `await`.

## Example

Wrong — `value` is a coroutine, not an int:

```python
async def fetch_value() -> int:
    return 21

async def compute_total() -> int:
    value = fetch_value()          # missing await
    return value * 2
```

Right — `await` resolves the coroutine to its return value:

```python
async def fetch_value() -> int:
    return 21

async def compute_total() -> int:
    value = await fetch_value()
    return value * 2
```

## At the sync boundary, use asyncio.run

```python
result = asyncio.run(compute_total())
```

Inside sync code, `asyncio.run()` drives a single coroutine to
completion and returns its value. Inside async code, always
`await`; never call `asyncio.run()` from an already-running loop.

## Running many in parallel

Launch with `asyncio.gather` — a plain list comprehension produces a
list of un-awaited coroutines:

```python
users = await asyncio.gather(*(fetch_user(i) for i in ids))
```

## Catch this earlier

Set `PYTHONASYNCIODEBUG=1` in development. It surfaces un-awaited
coroutines as warnings the moment they are garbage-collected,
instead of waiting for a downstream TypeError. Static type checkers
(mypy, pyright) also flag this when return annotations are present —
assigning a coroutine to an `int`-annotated variable is a type
error they catch before the code ever runs.
