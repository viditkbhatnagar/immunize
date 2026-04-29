"""Source-level verification for node-cjs-esm-mismatch.

A behavioral runner here would need a real Node.js install on every CI
machine — too heavy. Instead, we encode the pattern as a source-level
invariant: in an ES Module file (.mjs by extension, or in a package that
declares ``"type": "module"``), the CommonJS ``require()`` call is
illegal and crashes at load time. The test reads the fixture and asserts
no top-level ``require(...)`` calls remain.

Same approach as react-hook-missing-dep: we trade exact runtime
reproduction for a stdlib-only test that's deterministic across CI
environments. The matcher anchors on the canonical Node stderr phrases
(see pattern.yaml); this test just proves the bug shape is detectable
in source.
"""

from __future__ import annotations

import re
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "repro.mjs"

# Word-bounded `require(` — rejects substrings like `prerequire(` and
# string literals don't matter because Node parses `require` as an
# identifier here. The optional whitespace lets `require (foo)` and
# `require\t(foo)` both match.
_REQUIRE_CALL_RE = re.compile(r"\brequire\s*\(")

# `import x from "y"` or `import { ... } from "y"` or `import "y"`.
# Anchored at start-of-line (with optional leading whitespace) so it
# doesn't fire on the substring `import` inside an unrelated identifier.
_IMPORT_STATEMENT_RE = re.compile(r"^\s*import\s+", re.MULTILINE)


def test_esm_module_uses_import_not_require() -> None:
    source = FIXTURE.read_text()

    # Sanity: this is supposed to be an ESM file, so it must contain at
    # least one `import` statement. If the fixture has degenerated into
    # something that isn't ESM at all, the test below would pass
    # vacuously and miss the bug.
    assert _IMPORT_STATEMENT_RE.search(
        source
    ), "fixture has no `import` statement — test is invalid for an ESM file"

    require_calls = _REQUIRE_CALL_RE.findall(source)
    assert not require_calls, (
        f"ESM module ({FIXTURE.name}) contains {len(require_calls)} require() "
        "call(s); replace with `import` statements to load this file under Node's "
        "ESM loader."
    )
