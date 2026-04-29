"""Source-level verification for promise-unhandled-rejection.

Behavioral verification would need a real Node runtime plus a network
mock — too heavy for stdlib pytest. Instead, encode the pattern as a
source invariant: every fixture file that contains a Promise chain
(``.then(``) must terminate that chain in ``.catch(`` somewhere
downstream, otherwise a rejection will escape as unhandled.

Same approach as react-hook-missing-dep and node-cjs-esm-mismatch: we
trade exact runtime reproduction for a deterministic stdlib-only test.
The matcher fires on the canonical Node/browser stderr phrases (see
pattern.yaml); this test proves the source-level shape of the bug is
detectable.
"""

from __future__ import annotations

import re
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "repro.mjs"

# `.then(` and `.catch(` as method calls. Whitespace between the keyword
# and ``(`` is permitted, so ``.then (cb)`` matches the same as
# ``.then(cb)``.
_THEN_CALL_RE = re.compile(r"\.\s*then\s*\(")
_CATCH_CALL_RE = re.compile(r"\.\s*catch\s*\(")

# Strip JS/TS comments so prose like "terminate in .catch(...)" inside a
# // or /* */ block can't satisfy the assertion against the buggy file.
# The order matters — block first, then line — because `// inside /* ... */`
# would otherwise be eaten by the line pass first. Strings are not stripped;
# any code that hides a method call inside a literal is already in trouble.
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")


def _strip_comments(source: str) -> str:
    return _LINE_COMMENT_RE.sub("", _BLOCK_COMMENT_RE.sub("", source))


def test_promise_chain_terminates_in_catch() -> None:
    source = _strip_comments(FIXTURE.read_text())

    then_calls = _THEN_CALL_RE.findall(source)
    assert then_calls, "fixture has no .then() chain — test is invalid for this pattern"

    catch_calls = _CATCH_CALL_RE.findall(source)
    assert catch_calls, (
        f"fixture has {len(then_calls)} .then() call(s) but no .catch() — "
        "the rejection path is unhandled and will surface as "
        "UnhandledPromiseRejection at runtime."
    )
