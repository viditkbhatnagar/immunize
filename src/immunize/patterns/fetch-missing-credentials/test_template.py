"""Source-level verification for fetch-missing-credentials.

Asserts every fetch() call to a cross-origin URL in the fixture includes
`credentials: 'include'` in its options init. "Cross-origin" here is any
URL with an absolute http(s):// scheme — same-origin requests don't need
the flag.

Source-pattern check, not a behavioral test. Simulating the browser's
CORS credentials machinery in pytest would require a fake fetch + a fake
Access-Control policy engine; neither is worth the complexity for
stdlib-only verification. The skill + cursor rule carry the runtime
intuition; this test proves the shape is source-detectable.
"""

from __future__ import annotations

import re
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "repro.jsx"

# First arg: single or double quoted URL (captured).
# Second group: the remainder of the arg list up to the first ) — DOTALL
# so multi-line option objects are captured.
_FETCH_CALL_RE = re.compile(
    r"fetch\s*\(\s*['\"]([^'\"]+)['\"]([^)]*)\)",
    re.DOTALL,
)
_CREDENTIALS_INCLUDE_RE = re.compile(r"credentials\s*:\s*['\"]include['\"]")


def test_cross_origin_fetch_includes_credentials() -> None:
    source = FIXTURE.read_text()
    calls = _FETCH_CALL_RE.findall(source)
    assert calls, "fixture has no fetch() calls — test is invalid"

    cross_origin = [(url, rest) for url, rest in calls if url.startswith(("http://", "https://"))]
    assert cross_origin, "fixture has no cross-origin fetch calls — test is invalid"

    for url, rest in cross_origin:
        assert _CREDENTIALS_INCLUDE_RE.search(rest), (
            f"fetch('{url}') is cross-origin but does not include "
            f"credentials: 'include' in its init; init tail: {rest!r}"
        )
