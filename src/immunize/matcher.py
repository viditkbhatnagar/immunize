"""Pattern matching engine — deterministic, offline, no LLM.

Replaces the Phase 1 diagnose/generate pipeline. Given a CapturePayload
and a list of loaded Patterns, produces ranked MatchResult objects based
on regex matches against stderr/stdout plus lightweight heuristics for
error class and language.

NO imports from ``anthropic``. NO network calls. Pure stdlib + pyyaml +
pydantic + rich.

Regex caching: ``pattern.yaml`` files specify ``stderr_patterns`` and
``stdout_patterns`` as regex strings. They are compiled once per process,
keyed by ``pattern.id``, and stored in the module-level ``_COMPILED_RULES``
dict. After ``load_patterns`` deduplicates on id (local overrides bundled),
ids are unique, so there are no cache collisions. Tests clear this dict
between cases via an autouse fixture to stay hermetic.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import ValidationError
from rich.console import Console

from immunize.models import CapturePayload, MatchResult, Pattern

# Public: consumed by authoring tools (as valid hint-class names) and
# exercised directly in tests. The string form remains authoritative; the
# compiled regex form below is a runtime accelerator that additionally
# enforces word boundaries so keywords can't substring-collide across
# classes (v0.2.0 fix: "ENOTFOUND" was substring-matching inside
# "ModuleNotFoundError" and tying import vs network to 'other').
ERROR_CLASS_HINTS: dict[str, list[str]] = {
    "cors": ["CORS", "Access-Control-Allow", "preflight"],
    "import": ["ModuleNotFoundError", "ImportError", "Cannot find module"],
    "auth": ["401", "403", "Unauthorized", "Forbidden", "authentication"],
    "rate_limit": ["429", "rate limit", "Too Many Requests"],
    "type_error": ["TypeError", "is not a function", "is not iterable"],
    "null_ref": ["NoneType", "Cannot read prop", "undefined is not"],
    "config": ["env var", "environment variable", "not set", "tsconfig"],
    "network": ["ECONNREFUSED", "ENOTFOUND", "ETIMEDOUT", "getaddrinfo"],
}

# Word-bounded regex form. \b on both sides rejects substring collisions
# (ENOTFOUND inside ModuleNotFoundError; CORS inside CORSICAN; 429 inside
# 4290). Hyphens and spaces inside keywords like "Access-Control-Allow" are
# already non-word characters, so internal \b assertions aren't needed —
# only outer boundaries. re.IGNORECASE matches the prior .lower()-based
# semantics; re.escape is defensive in case a keyword ever gains a regex
# metachar.
_HINT_REGEXES: dict[str, list[re.Pattern[str]]] = {
    cls: [re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE) for kw in keywords]
    for cls, keywords in ERROR_CLASS_HINTS.items()
}

# Tiny epsilon for confidence-threshold comparisons. IEEE 754 binary floats
# can't represent 0.3 or 0.15 exactly; e.g. 0.3 + 0.15 evaluates to
# 0.44999999999999996 in CPython, which trips a strict `>= 0.45` check.
# Adding 1e-9 before the comparison restores author intent while staying
# well below any calibration delta that matters.
_CONFIDENCE_EPSILON = 1e-9

# Language detection: each language maps to a list of pre-compiled regexes.
# Any-signature match adds the language to guess_languages' result. Multiple
# languages can be returned (e.g., a Next.js traceback hits both JS and TS).
_LANGUAGE_SIGNATURES: dict[str, list[re.Pattern[str]]] = {
    "python": [
        re.compile(r"Traceback \(most recent call last\)"),
        re.compile(r'File "[^"]+\.py"'),
        re.compile(r"\bModuleNotFoundError\b"),
    ],
    "javascript": [
        re.compile(r"\bReferenceError\b"),
        re.compile(r"at Object\.<anonymous>"),
        re.compile(r"TypeError: \S+ is not a function"),
    ],
    "typescript": [re.compile(r"\bTS\d{3,5}:")],
    "go": [re.compile(r"(?m)^panic:"), re.compile(r"\bgoroutine \d+")],
    "rust": [re.compile(r"thread '[^']*' panicked")],
}

# Compiled-rules cache. Key = pattern.id. Populated lazily by _compile_rules.
_COMPILED_RULES: dict[str, tuple[list[re.Pattern[str]], list[re.Pattern[str]]]] = {}


def load_patterns(bundled_dir: Path, local_dir: Path | None = None) -> list[Pattern]:
    """Load all bundled and local patterns from disk.

    Bundled patterns come from ``bundled_dir/<slug>/pattern.yaml``. Local
    patterns, if ``local_dir`` is provided and exists, come from
    ``local_dir/<slug>/pattern.yaml``. When a local pattern's ``id``
    matches a bundled pattern's ``id``, the local one wins — local is
    explicit user authorship.

    Malformed pattern.yaml files are logged to stderr via Rich and
    skipped; one bad pattern never aborts the load.
    """
    # soft_wrap=True disables Rich's column-width truncation so pattern
    # paths and identifiers always render in full — CI runners have
    # narrow default terminal widths and were truncating path names,
    # making the warning messages ambiguous.
    console_err = Console(stderr=True, soft_wrap=True)
    bundled = _load_from_dir(bundled_dir, console_err)
    local = _load_from_dir(local_dir, console_err) if local_dir is not None else []

    by_id: dict[str, Pattern] = {p.id: p for p in bundled}
    for p in local:
        by_id[p.id] = p  # local overrides bundled on id clash
    return list(by_id.values())


def match(payload: CapturePayload, patterns: list[Pattern]) -> list[MatchResult]:
    """Score each pattern against the payload and return those that clear
    their own ``match.min_confidence`` threshold, sorted descending.
    """
    scored = [score_pattern(payload, p) for p in patterns]
    above = [
        r for r in scored if r.confidence + _CONFIDENCE_EPSILON >= r.pattern.match.min_confidence
    ]
    above.sort(key=lambda r: r.confidence, reverse=True)
    return above


def score_pattern(payload: CapturePayload, pattern: Pattern) -> MatchResult:
    """Deterministic confidence scoring for one pattern against the payload.

    Always returns a MatchResult, even at confidence 0.0 — threshold
    filtering happens in ``match()``. Breakdown keys are fixed:
    ``stderr``, ``stdout``, ``error_class_hint``, ``language``.
    """
    stderr_res, stdout_res = _compile_rules(pattern)

    matched_stderr = [
        raw
        for regex, raw in zip(stderr_res, pattern.match.stderr_patterns, strict=True)
        if regex.search(payload.stderr)
    ]
    stderr_score = min(0.6, 0.3 * len(matched_stderr))

    matched_stdout = [
        raw
        for regex, raw in zip(stdout_res, pattern.match.stdout_patterns, strict=True)
        if regex.search(payload.stdout)
    ]
    stdout_score = min(0.4, 0.2 * len(matched_stdout))

    hint_score = 0.0
    if (
        pattern.match.error_class_hint is not None
        and guess_error_class(payload.stderr) == pattern.match.error_class_hint
    ):
        hint_score = 0.15

    language_score = 0.0
    detected = guess_languages(payload.stderr)
    if detected and any(lang in pattern.languages for lang in detected):
        language_score = 0.1

    breakdown: dict[str, float] = {
        "stderr": stderr_score,
        "stdout": stdout_score,
        "error_class_hint": hint_score,
        "language": language_score,
    }
    confidence = min(1.0, sum(breakdown.values()))

    return MatchResult(
        pattern=pattern,
        confidence=confidence,
        matched_stderr_patterns=matched_stderr,
        matched_stdout_patterns=matched_stdout,
        score_breakdown=breakdown,
    )


def guess_error_class(stderr: str) -> str:
    """Keyword-based error-class guess with word-boundary safety.

    Returns the class whose keywords produce the most hits in ``stderr``.
    Uses pre-compiled word-bounded regex (_HINT_REGEXES) rather than plain
    substring matching so keywords like "ENOTFOUND" don't accidentally
    match inside unrelated longer identifiers like "ModuleNotFoundError".
    Returns ``"other"`` when nothing matches or when multiple classes tie
    for first place (avoids false confidence on ambiguous stderr).
    """
    scores: dict[str, int] = {}
    for cls, regexes in _HINT_REGEXES.items():
        count = sum(1 for rx in regexes if rx.search(stderr))
        if count > 0:
            scores[cls] = count
    if not scores:
        return "other"
    max_count = max(scores.values())
    winners = [cls for cls, n in scores.items() if n == max_count]
    if len(winners) > 1:
        return "other"
    return winners[0]


def guess_languages(stderr: str) -> list[str]:
    """Detect languages whose canonical traceback shapes appear in stderr.

    Multi-language output is intentional (e.g., a Next.js traceback hits
    both JavaScript and TypeScript). Order follows ``_LANGUAGE_SIGNATURES``
    insertion order.
    """
    return [
        lang
        for lang, sigs in _LANGUAGE_SIGNATURES.items()
        if any(sig.search(stderr) for sig in sigs)
    ]


def _load_from_dir(directory: Path | None, console_err: Console) -> list[Pattern]:
    if directory is None or not directory.is_dir():
        return []
    patterns: list[Pattern] = []
    for child in sorted(directory.iterdir()):
        if not child.is_dir():
            continue
        yaml_path = child / "pattern.yaml"
        if not yaml_path.is_file():
            continue
        try:
            data = yaml.safe_load(yaml_path.read_text())
            pattern = Pattern.model_validate(data)
        except (yaml.YAMLError, ValidationError, OSError) as e:
            console_err.print(
                f"[yellow]immunize: skipping malformed pattern at {yaml_path}: {e}[/yellow]"
            )
            continue
        patterns.append(pattern.model_copy(update={"directory": child.resolve()}))
    return patterns


def _compile_rules(
    pattern: Pattern,
) -> tuple[list[re.Pattern[str]], list[re.Pattern[str]]]:
    cached = _COMPILED_RULES.get(pattern.id)
    if cached is not None:
        return cached
    stderr_res = [re.compile(p) for p in pattern.match.stderr_patterns]
    stdout_res = [re.compile(p) for p in pattern.match.stdout_patterns]
    compiled = (stderr_res, stdout_res)
    _COMPILED_RULES[pattern.id] = compiled
    return compiled
