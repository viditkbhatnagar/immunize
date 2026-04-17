# Launch Library — 20 Patterns for v0.1

> The curated list of patterns to author for the v0.1 release. Ordered by strategic priority: high-impact patterns first, ones that demo well on Hacker News, ones with clean verification stories. Work top to bottom; if you run out of time at pattern 15, that's still a shippable v0.1.

## How I chose these

Three criteria:

1. **Frequency** — errors the AI actually produces often. Drawn from public issues, HN threads about AI coding frustrations, and common LLM failure modes.
2. **Verifiability** — errors where we can write a clean pytest that fails without the fix and passes with it. Some errors (browser CORS, IDE integration issues) verify weakly.
3. **Demo value** — the 90-second HN demo should lead with 2-3 of these. Pick patterns that are visually obvious when they occur.

Patterns that fall outside these criteria aren't bad — they just don't belong in v0.1.

## Tier 1 — Must ship (patterns 1–10)

These are the patterns that justify v0.1 existing. Every one of them catches errors that I've personally seen Claude Code / Cursor produce in real work or public bug reports.

### 1. `react-hook-missing-dep`
**What**: `useEffect` or `useCallback` referencing state without listing it in the dependency array.
**Language**: JavaScript, TypeScript
**Stderr hint**: `React Hook useEffect has a missing dependency`
**Why high priority**: Single most common React bug Claude introduces. Lint already catches it, but the SKILL.md teaches the AI to write the dependency correctly the first time.
**Verification approach**: Test imports a component, mounts it, asserts a counter isn't incrementing infinitely.

### 2. `fetch-missing-credentials`
**What**: Cross-origin authenticated fetch without `credentials: 'include'` (JS) or `withCredentials: true` (axios).
**Language**: JavaScript, TypeScript
**Stderr hint**: `credentials flag is 'include'`, `Access-Control-Allow-Credentials`
**Why high priority**: Classic Claude Code mistake when generating frontend auth code. Flagship demo pattern.
**Verification approach**: Mock fetch wrapper; test asserts `credentials: 'include'` is in the request init.

### 3. `python-none-attribute-access`
**What**: Accessing `.foo` on a value that can be `None`. AI often forgets Optional-type handling.
**Language**: Python
**Stderr hint**: `AttributeError: 'NoneType' object has no attribute`
**Why high priority**: The single most common Python runtime error from AI-generated code.
**Verification approach**: Test a function that takes `dict | None`; asserts it doesn't crash when given None.

### 4. `import-not-found-python`
**What**: Imports from a module that doesn't exist, or wrong import path (`from utils import foo` when `utils.py` doesn't exist).
**Language**: Python
**Stderr hint**: `ModuleNotFoundError`, `ImportError`
**Why high priority**: Common when AI hallucinates module names.
**Verification approach**: Test uses `importlib` to attempt the wrong import, expects ModuleNotFoundError; then the fix uses the correct import path.

### 5. `missing-env-var`
**What**: Code references `os.environ['FOO']` without checking if it's set; crashes with KeyError on missing env vars.
**Language**: Python, JavaScript, TypeScript
**Stderr hint**: `KeyError`, `process.env.FOO is undefined`
**Why high priority**: Classic config error. Fix is always "read with default or raise a specific error message."
**Verification approach**: Unset env var, run code, assert it raises a clean `ConfigError` (not a raw KeyError).

### 6. `rate-limit-no-backoff`
**What**: Code that calls an API in a loop without exponential backoff; first 429 crashes the script.
**Language**: Python, JavaScript, TypeScript
**Stderr hint**: `429`, `Too Many Requests`, `rate limit`
**Why high priority**: Common in AI-generated scraper / API client code.
**Verification approach**: Mock HTTP client; return 429 on first call, 200 on second. Test asserts code retries with backoff.

### 7. `typescript-any-escape`
**What**: Function signature uses `any` as the return or param type, defeating TypeScript.
**Language**: TypeScript
**Stderr hint**: N/A (this is a lint/code-review pattern, not a runtime error)
**Why high priority**: Claude drops `any` liberally to "make it compile." Catching this is high-leverage.
**Verification approach**: Use `ts.transpileModule` to parse the file; assert no `any` annotations remain in function signatures.

### 8. `async-fn-called-without-await`
**What**: Calling an async function without `await` and using its return value as if it were the resolved value.
**Language**: JavaScript, TypeScript, Python
**Stderr hint**: `Promise {<pending>}`, `coroutine was never awaited`
**Why high priority**: Subtle bug that Claude produces often. Runtime-verifiable.
**Verification approach**: Test a function that depends on an async result; assert the result is the resolved value, not a pending promise.

### 9. `null-default-param-python`
**What**: Mutable default argument (`def f(x=[])`), causing cross-call state leaks.
**Language**: Python
**Stderr hint**: N/A (silent bug; pattern match is on source code via Semgrep rule)
**Why high priority**: Classic Python gotcha. Ships as a Semgrep rule primarily, with SKILL.md warning.
**Verification approach**: Call `f()` twice, assert state doesn't leak.

### 10. `fastapi-sync-route-in-async-app`
**What**: Defining `def route()` instead of `async def route()` in a FastAPI app, blocking the event loop.
**Language**: Python
**Stderr hint**: N/A (performance bug; detected via source pattern)
**Why high priority**: Specific to AI-generated FastAPI code; Claude mixes sync/async patterns carelessly.
**Verification approach**: Inspect source AST; assert FastAPI routes that do any IO are `async def`.

## Tier 2 — Nice to ship (patterns 11–17)

These extend coverage. If you have time before launch, write them. If you don't, they're v0.2.

### 11. `cors-wildcard-with-credentials`
**What**: Server sends `Access-Control-Allow-Origin: *` together with `Access-Control-Allow-Credentials: true` — invalid combination per spec.
**Language**: Python (Flask, FastAPI), JavaScript (Express)
**Stderr hint**: Browser console `Access-Control-Allow-Origin` with credentials issue
**Verification approach**: Response header assertion.

### 12. `sql-injection-string-format`
**What**: Using `f"SELECT * FROM users WHERE id = {user_id}"` instead of parameterized queries.
**Language**: Python
**Stderr hint**: N/A (security pattern — source-level detection)
**Verification approach**: Semgrep rule + SKILL.md.

### 13. `react-state-stale-closure`
**What**: Event handler captures stale state because of dependency array mismatch.
**Language**: JavaScript, TypeScript
**Stderr hint**: N/A (correctness bug)
**Verification approach**: Mount a component, trigger events; assert state is fresh.

### 14. `python-iterator-consumed-twice`
**What**: Iterating over a generator twice, expecting the same items; second iteration is empty.
**Language**: Python
**Stderr hint**: N/A (silent bug)
**Verification approach**: Assert second iteration matches first (it won't, until the fix materializes to a list).

### 15. `node-cjs-esm-mismatch`
**What**: Using `require()` in an ESM module, or `import` in a CJS module.
**Language**: JavaScript, TypeScript
**Stderr hint**: `require is not defined in ES module scope`, `Cannot use import statement outside a module`
**Verification approach**: Test module loads cleanly with correct syntax.

### 16. `missing-try-except-api-call`
**What**: API call with no error handling; first failed request crashes the script.
**Language**: Python, JavaScript
**Stderr hint**: Various
**Verification approach**: Mock API to raise an exception; assert the code catches and logs gracefully.

### 17. `hardcoded-secret-in-source`
**What**: API key, token, or password literal committed to source.
**Language**: All
**Stderr hint**: N/A (detected by source pattern)
**Verification approach**: Semgrep rule.

## Tier 3 — Stretch (patterns 18–20)

Ship if energy permits. Otherwise v0.2.

### 18. `timezone-naive-datetime`
**What**: Using `datetime.now()` without timezone; comparing with aware datetimes.
**Language**: Python

### 19. `off-by-one-slice`
**What**: List slicing where `xs[:-1]` was meant but `xs[-1:]` was written.
**Language**: Python, JavaScript

### 20. `promise-unhandled-rejection`
**What**: Promise chain without `.catch()` or try/catch in async function; crashes Node with unhandled rejection.
**Language**: JavaScript, TypeScript

## Suggested authoring order

For your 7–10 hour content sprint, author in this order. Each should take ~20–30 minutes.

**Day 1 (3 hours)**: Patterns 1, 2, 3, 5, 6. These are the flagship demos — most likely to produce clean verification stories.

**Day 2 (3 hours)**: Patterns 4, 8, 9, 10, 11. Fills out the "common Claude failure" coverage.

**Day 3 (2-3 hours)**: Patterns 7, 12, 13, 14, 15. Broader language coverage.

**Optional Day 4 (2 hours)**: Patterns 16, 17, 18, 19, 20. If energy holds and launch isn't until day 14.

## Demo picks for Hacker News launch

Lead with **pattern 2 (fetch-missing-credentials)** — it's the most visually obvious error and the fix is clear.

Show **pattern 3 (python-none-attribute-access)** as the second demo — different language, different error shape, proves the library isn't JavaScript-only.

Mention in voiceover that there are **X total bundled patterns** (X = whatever you shipped, be honest). "And when you hit an error not in the library, Claude Code drafts a local pattern for you at no extra cost."

## Metrics for post-launch

Once v0.1 is live, track:

- Which bundled patterns get applied most (top 3 validate you chose right)
- Which patterns get applied rarely (maybe cut in v0.2 to reduce library size)
- How many users hit the "no match" case and how many drafted local patterns successfully (signal for whether local-learning UX works)
- How many community PRs arrive proposing new patterns (signal for whether the contributor story is compelling)

Use these to prioritize v0.2.

## What to tell Claude Code about this doc

This list is strictly reference material for when you (Vidit) author patterns. Claude Code doesn't use this during Phase 1B step execution — it's only relevant once the mechanism is shipped (step 10 of PLAN_1B.md) and you start populating the library.

When Claude Code reaches step 10, it should NOT try to auto-generate all 20 patterns in a single run. The authoring workflow is deliberately hands-on — you review every draft, every time. Claude Code's job in step 10 is to help you with individual patterns as you drive, not to batch-author without review.
