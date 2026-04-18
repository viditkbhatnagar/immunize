# Matcher calibration — v0.2.0

## Context

v0.1.x anchors were designed against hand-synthesized examples, not real-world
stderr. External review found that several patterns either didn't match their
own class of real errors (import, env, async had 0% recall) or required very
specific phrasings that real code doesn't produce (react, fetch under-matched).

This pass re-grounds every anchor set against 5 real copy-pasted stderr
samples per pattern (35 total), collected from GitHub issues, Stack Overflow,
MDN, and canonical SDK error messages. Every regex change was measured against
those samples before being committed.

**Aggregate recall**: 12/40 → 38/40. The two "unmatched" samples are
cross-pattern false-positive rejects (e.g. a CORS-preflight-rejected failure
that shouldn't match `fetch-missing-credentials` because it's not a credentials
issue). The pattern_lint FAIL→PASS→FAIL fixture contract is unchanged — only
stderr regex and threshold moved.

## Two thresholds, one authoritative source

The matcher gates a candidate pattern at two thresholds stacked:

1. **Per-pattern** `pattern.match.min_confidence` (enforced in
   [`matcher.match()`](../src/immunize/matcher.py#L91) at the pattern level).
   This is what the author tunes against real-world stderr — the source of
   truth for precision/recall tradeoffs.
2. **Global floor** `settings.min_match_confidence` (enforced in
   [`cli._apply_payload`](../src/immunize/cli.py) after `matcher.match()`).
   Pre-v0.2.0 default: `0.70`. v0.2.0 default: **`0.30`**.

The pre-v0.2.0 default of 0.70 silently shadowed every per-pattern threshold
below it. Single-anchor samples (most of the real-world tracebacks surveyed
here — one specific phrase + language signal + hint adds up to ~0.55) would
score *above* their pattern's own min_confidence but *below* the 0.70 floor,
so the pattern was dead code in practice.

Setting the floor default to **0.30** reverses the relationship: per-pattern
thresholds become authoritative. Contributors write authentic thresholds in
each `pattern.yaml`; the floor exists only for operators who want a stricter
global minimum (raise via `IMMUNIZE_MIN_MATCH_CONFIDENCE=0.60` in CI, for
example).

The recall tables below reflect matches under the new effective threshold
`max(pattern.min_confidence, 0.30)` — i.e. per-pattern thresholds are now
what actually fires.

## Per-pattern detail

---

### react-hook-missing-dep

**Old**
```
stderr_patterns:
  - "React Hook useEffect has a missing dependency"
  - "React Hook useCallback has a missing dependency"
min_confidence: 0.70
```

**New**
```
stderr_patterns:
  - "React Hook (?:React\\.)?(?:useEffect|useCallback|useMemo) has (?:a missing|an unnecessary) dependency"
  - "react-hooks/exhaustive-deps"
min_confidence: 0.30
```

**Samples (recall 3/5 → 5/5)**

| # | Source | Matched before | Matched after |
|---|---|---|---|
| 1 | [github.com/facebook/react/issues/20475](https://github.com/facebook/react/issues/20475) (CLI with `React.useEffect` qualifier) | ✗ | ✓ |
| 2 | [github.com/facebook/react/issues/15204](https://github.com/facebook/react/issues/15204) | ✓ | ✓ |
| 3 | [github.com/facebook/react/issues/16265](https://github.com/facebook/react/issues/16265) (inline `eslint(...)` format) | ✓ | ✓ |
| 4 | [github.com/facebook/react/issues/19061](https://github.com/facebook/react/issues/19061) (`useCallback has an unnecessary dependency`) | ✗ | ✓ |
| 5 | [github.com/facebook/react/issues/15865](https://github.com/facebook/react/issues/15865) | ✓ | ✓ |

**Rationale**: the rule ID `react-hooks/exhaustive-deps` is extremely specific
— every single surveyed sample contained it. Lowered threshold to 0.30 so a
single-anchor match on the rule ID clears. The widened phrase anchor covers
`useMemo`, the `React.`-qualified form, and the "unnecessary" variant (same
rule, inverse wording, same remedy).

---

### fetch-missing-credentials

**Old**
```
stderr_patterns:
  - "Access-Control-Allow-Credentials"
  - "credentials"
min_confidence: 0.75
```

**New**
```
stderr_patterns:
  - "Access-Control-Allow-Credentials"
  - "credentials mode is 'include'"
  - "Credential is not supported"
min_confidence: 0.45
```

**Samples (recall on the 3 in-scope samples: 1/3 → 3/3; 2 out-of-scope correctly rejected)**

| # | Source | In scope? | Matched before | Matched after |
|---|---|---|---|---|
| 1 | [github.com/Kong/insomnia/issues/7647](https://github.com/Kong/insomnia/issues/7647) (wildcard + credentials-include) | yes | ✗ | ✓ |
| 2 | [github.com/openai/openai-chatkit-starter-app/issues/7](https://github.com/openai/openai-chatkit-starter-app/issues/7) (plain missing ACA-Origin) | no — different bug | ✗ | ✗ (correct reject) |
| 3 | [github.com/hasura/graphql-engine/issues/3854](https://github.com/hasura/graphql-engine/issues/3854) (preflight mismatch) | no — different bug | ✗ | ✗ (correct reject) |
| 4 | [MDN CORSMissingAllowCredentials](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS/Errors/CORSMissingAllowCredentials) (Firefox) | yes | ✓ | ✓ |
| 5 | [MDN CORSNotSupportingCredentials](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS/Errors/CORSNotSupportingCredentials) (Firefox) | yes | ✗ | ✓ |

**Rationale**: the bare word `credentials` as an anchor caused false positives
on password prompts and basic-auth messages (grep-level broad). Replaced with
three tight phrases that collectively cover Chrome's "credentials mode is
'include'" wording, Firefox's "Credential is not supported" wording, and any
output explicitly naming the header. Threshold 0.45 = one specific anchor
(0.3) + the `cors` hint (0.15). The two out-of-scope CORS failures (sample 2
missing-origin, sample 3 preflight-mismatch) correctly stay below threshold
because they contain none of the three new anchors.

---

### python-none-attribute-access

**Old**
```
stderr_patterns:
  - "AttributeError"
  - "'NoneType' object has no attribute"
min_confidence: 0.70
```

**New**
```
stderr_patterns:
  - "AttributeError: 'NoneType' object has no attribute"
  - "TypeError: 'NoneType' object is not subscriptable"
min_confidence: 0.30
```

**Samples (recall 4/7 → 7/7)**

| # | Source | Variant | Matched before | Matched after |
|---|---|---|---|---|
| 1 | [github.com/encode/httpx/discussions/1951](https://github.com/encode/httpx/discussions/1951) | AttributeError | ✓ | ✓ |
| 2 | [github.com/pytorch/pytorch/issues/74016](https://github.com/pytorch/pytorch/issues/74016) | AttributeError, `Exception ignored in` | ✓ | ✓ |
| 3 | [github.com/langfuse/langfuse/issues/4834](https://github.com/langfuse/langfuse/issues/4834) | AttributeError | ✓ | ✓ |
| 4 | [github.com/matplotlib/matplotlib/issues/21569](https://github.com/matplotlib/matplotlib/issues/21569) | AttributeError | ✓ | ✓ |
| 5 | [github.com/cython/cython/issues/5595](https://github.com/cython/cython/issues/5595) | TypeError subscriptable | ✗ | ✓ |
| 6 | [github.com/kubernetes-client/python/issues/1673](https://github.com/kubernetes-client/python/issues/1673) | TypeError subscriptable | ✗ | ✓ |
| 7 | [github.com/huggingface/transformers/issues/21995](https://github.com/huggingface/transformers/issues/21995) | TypeError subscriptable, Jupyter-style | ✗ | ✓ |

**Rationale**: the subscript variant (`TypeError: 'NoneType' object is not
subscriptable`) shares the same failure mode — unchecked None — and the
skill's "guard against None" remedy applies identically. Merged the two loose
anchors (`AttributeError` alone + the partial phrase) into one tight phrase
plus the subscript variant; both are canonical CPython strings with zero
false-positive surface.

---

### import-not-found-python

**Old**
```
stderr_patterns:
  - "ModuleNotFoundError: No module named"
  - "ImportError: cannot import name"
min_confidence: 0.70
```

**New**
```
stderr_patterns:
  - "ModuleNotFoundError: No module named"
  - "ImportError: cannot import name"
min_confidence: 0.50
```

**Samples (recall 0/6 → 6/6)**

| # | Source | Variant | Matched before | Matched after |
|---|---|---|---|---|
| 1 | [github.com/pypa/pip/issues/12692](https://github.com/pypa/pip/issues/12692) | ModuleNotFoundError | ✗ | ✓ |
| 2 | [github.com/pypa/pip/issues/6642](https://github.com/pypa/pip/issues/6642) | ModuleNotFoundError | ✗ | ✓ |
| 3 | [github.com/psf/black/issues/2964](https://github.com/psf/black/issues/2964) | ImportError: cannot import name | ✗ | ✓ |
| 4 | [github.com/plotly/dash/issues/1992](https://github.com/plotly/dash/issues/1992) | ImportError from werkzeug | ✗ | ✓ |
| 5 | [github.com/explosion/spaCy/issues/12669](https://github.com/explosion/spaCy/issues/12669) | ImportError, IPython-style chain | ✗ | ✓ |
| 6 | [github.com/pytest-dev/pytest/issues/12066](https://github.com/pytest-dev/pytest/issues/12066) | ImportError, deep chain | ✗ | ✓ |

**Rationale**: anchors were already unambiguously specific — the pattern was
dead code only because threshold was too high. Single-anchor match (0.3) +
`import` hint (0.15) + python lang (0.1) = 0.55; old threshold 0.70 needed
both anchors *and* hint *and* lang simultaneously, which never happened in
practice. Dropped threshold to 0.50, regexes unchanged.

---

### missing-env-var

**Old**
```
stderr_patterns:
  - "KeyError:"
  - "os.environ"
error_class_hint: config
min_confidence: 0.75
```

**New**
```
stderr_patterns:
  - "KeyError: '[A-Z][A-Z0-9_]*'"
  - "os\\.environ\\["
error_class_hint: null
min_confidence: 0.40
```

**Samples (recall 0/5 → 5/5)**

| # | Source | Matched before | Matched after |
|---|---|---|---|
| 1 | [github.com/apache/airflow/issues/16457](https://github.com/apache/airflow/issues/16457) (`KeyError: 'ENVIRONMENT'`) | ✗ | ✓ |
| 2 | [github.com/pytorch/pytorch/issues/82492](https://github.com/pytorch/pytorch/issues/82492) (`KeyError: 'BUILD_ENVIRONMENT'`) | ✗ | ✓ |
| 3 | Same issue, second traceback (`KeyError: 'TEST_CONFIG'`) | ✗ | ✓ |
| 4 | [github.com/microsoft/promptflow/issues/3499](https://github.com/microsoft/promptflow/issues/3499) (`KeyError: 'AZURE_SEARCH_SERVICE_ENDPOINT'`) | ✗ | ✓ |
| 5 | [github.com/pydanny/cookiecutter-django/issues/1888](https://github.com/pydanny/cookiecutter-django/issues/1888) (`KeyError: 'DATABASE_URL'` via django-environ — no literal `os.environ[` in frame) | ✗ | ✓ |

**Rationale**: the old `config` hint keyed off phrases like "env var" or
"environment variable" that real tracebacks don't contain, so the hint's 0.15
bonus never fired. Dropped the hint entirely and tightened anchors to
UPPER_SNAKE key convention (`KeyError: '[A-Z][A-Z0-9_]*'`) plus the actual
accessor syntax (`os\.environ\[`). The upper-snake key convention rejects
regular dict KeyErrors with camelCase/lowercase keys. Sample 5 still clears
via anchor 1 alone (0.3) plus python lang (0.1) = 0.4.

---

### rate-limit-no-backoff

**Old**
```
stderr_patterns:
  - "429"
  - "Too Many Requests"
  - "rate limit"
min_confidence: 0.70
```

**New**
```
stderr_patterns:
  - "429 Too Many Requests"
  - "RateLimitError"
  - "HTTPError.*\\b429\\b"
  - "rate_limit_error"
min_confidence: 0.50
```

**Samples (recall 4/7 → 7/7)**

| # | Source | Matching anchors | Score | Matched before | Matched after |
|---|---|---|---|---|---|
| 1 | [github.com/run-llama/llama_index/issues/11593](https://github.com/run-llama/llama_index/issues/11593) (`openai.RateLimitError`, quota) | RateLimitError | 0.55 | ✗ | ✓ |
| 2 | [github.com/assafelovic/gpt-researcher/issues/614](https://github.com/assafelovic/gpt-researcher/issues/614) (`openai.RateLimitError`) | RateLimitError | 0.55 | ✗ | ✓ |
| 3 | [github.com/pixeltable/pixeltable/issues/704](https://github.com/pixeltable/pixeltable/issues/704) (TPM limit) | RateLimitError | 0.55 | ✗ | ✓ |
| 4 | [github.com/anthropics/anthropic-sdk-python/issues/496](https://github.com/anthropics/anthropic-sdk-python/issues/496) (`anthropic.RateLimitError`, message-only) | RateLimitError + rate_limit_error | 0.75 | ✓ | ✓ |
| 5 | [github.com/facebookresearch/cc_net/issues/14](https://github.com/facebookresearch/cc_net/issues/14) (`requests.HTTPError: 429`) | HTTPError.*\b429\b | 0.55 | ✓ | ✓ |
| 6 | [github.com/TheR1D/shell_gpt/issues/301](https://github.com/TheR1D/shell_gpt/issues/301) (Rich traceback) | HTTPError.*\b429\b | 0.55 | ✓ | ✓ |
| 7 | [github.com/JuanBindez/pytubefix/issues/287](https://github.com/JuanBindez/pytubefix/issues/287) (`urllib.error.HTTPError: HTTP Error 429`) | HTTPError.*\b429\b | 0.55 | ✓ | ✓ |

**Rationale**: the old design let bare `"Too Many Requests"` or `"rate limit"`
clear threshold whenever they appeared anywhere in stderr plus the
`rate_limit` hint plus python lang — matching any Python traceback that
happened to quote those phrases in an unrelated log line. Tightened so every
anchor now *requires* an HTTP-client context:

- `"429 Too Many Requests"` — the exact HTTP status line (requests/httpx).
- `"RateLimitError"` — SDK exception class (openai, anthropic, stripe).
- `"HTTPError.*\b429\b"` — HTTPError class + word-bounded 429 on the same
  line (covers `requests.HTTPError` and `urllib.error.HTTPError`). Word
  boundaries prevent `1429` / `4290` substring matches.
- `"rate_limit_error"` — snake-cased JSON error-type from SDK structured
  responses; needed to reach 7/7 recall on message-only Anthropic pastes
  that lack a python traceback (so no language-score bonus).

Bare `"Too Many Requests"` and `"rate limit"` are kept as `rate_limit`
*hint* keywords (+0.15 when detected) but not as standalone anchors.
Threshold 0.50 means a stderr that only contains those phrases — without
any of the four anchors — maxes at hint (0.15) + python lang (0.10) = 0.25
and is correctly rejected.

**False-positive audit:**

| Adversarial stderr | Score | Cleared? |
|---|---|---|
| Py stderr with `"Too Many Requests"` only (no 429, no HTTPError, no RateLimitError) | 0.25 | ✗ rejected |
| Py stderr with `"429"` as a line number | 0.25 | ✗ rejected |
| Py stderr mentioning `"rate limit"` in docs/comments | 0.25 | ✗ rejected |
| Non-python stderr with `"HTTPError: 429"` (rare edge) | 0.45 | ✗ rejected |

---

### async-fn-called-without-await

**Old**
```
stderr_patterns:
  - "coroutine was never awaited"
  - "RuntimeWarning"
min_confidence: 0.75
```

**New**
```
stderr_patterns:
  - "coroutine '[^']+' was never awaited"
min_confidence: 0.30
```

**Samples (recall 0/5 → 5/5)**

| # | Source | Matched before | Matched after |
|---|---|---|---|
| 1 | [github.com/Rapptz/discord.py/issues/4190](https://github.com/Rapptz/discord.py/issues/4190) (`coroutine 'Client.start' was never awaited`) | ✗ | ✓ |
| 2 | [github.com/tornadoweb/tornado/issues/1845](https://github.com/tornadoweb/tornado/issues/1845) (`coroutine 'run' was never awaited`) | ✗ | ✓ |
| 3 | [github.com/openai/openai-python/issues/1265](https://github.com/openai/openai-python/issues/1265) (`coroutine 'AsyncAPIClient.post' was never awaited`) | ✗ | ✓ |
| 4 | [github.com/jelmer/xandikos/issues/192](https://github.com/jelmer/xandikos/issues/192) (`coroutine 'main' was never awaited`) | ✗ | ✓ |
| 5 | [github.com/zauberzeug/nicegui/issues/1809](https://github.com/zauberzeug/nicegui/issues/1809) (`coroutine 'AsyncServer.enter_room' was never awaited`) | ✗ | ✓ |

**Rationale**: the old anchor `"coroutine was never awaited"` had **zero**
recall because real warnings always embed a coroutine name between
"coroutine" and "was never awaited" — all 5 surveyed samples look like
`coroutine 'X' was never awaited`. Replaced with a single tight regex
capturing the canonical form. Dropped the `RuntimeWarning` anchor because it
was too broad (fires on every Python RuntimeWarning regardless of topic).
Threshold 0.30 allows the single specific anchor (0.3) to clear on its own.

## Diagnostic dump gating

Commit 2 added `.immunize/hook_payloads/<ts>-<sid>.json` dumps on every hook
firing to support this calibration work. Now that Commit 4 empirically pinned
the schema, that diagnostic is gated behind `IMMUNIZE_DEBUG_HOOK=1` so normal
users don't accumulate dumps. Contributors still use the dump to diagnose
novel schema changes by opting in:

```
IMMUNIZE_DEBUG_HOOK=1 immunize capture --source claude-code-hook < payload.json
```
