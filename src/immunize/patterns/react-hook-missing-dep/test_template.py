"""Source-level verification for react-hook-missing-dep.

Source-pattern check, not a behavioral test. A true runtime assertion
would require a JS parser (too heavy for a stdlib-only test) or a fake
React runtime (too fragile). Instead, we prove the missing-dep shape is
detectable in source: every useState identifier referenced inside a
useEffect or useCallback body must appear in that hook's deps array.
"""

from __future__ import annotations

import re
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "repro.jsx"

_USE_STATE_RE = re.compile(r"const\s*\[\s*(\w+)\s*,\s*\w+\s*\]\s*=\s*useState\b")
_HOOK_CALL_RE = re.compile(
    r"(useEffect|useCallback)\s*\(\s*\(\s*\)\s*=>\s*\{(.*?)\}\s*,\s*\[([^\]]*)\]\s*\)",
    re.DOTALL,
)


def test_every_reactive_ref_is_in_deps() -> None:
    source = FIXTURE.read_text()
    reactives = set(_USE_STATE_RE.findall(source))
    assert reactives, "fixture has no useState declarations — test is invalid"

    hooks = _HOOK_CALL_RE.findall(source)
    assert hooks, "fixture has no useEffect/useCallback calls — test is invalid"

    for hook_name, body, deps_str in hooks:
        deps = {d.strip() for d in deps_str.split(",") if d.strip()}
        for name in reactives:
            if re.search(rf"\b{re.escape(name)}\b", body):
                assert name in deps, (
                    f"{hook_name} references reactive '{name}' but it is "
                    f"missing from deps array {sorted(deps)}"
                )
