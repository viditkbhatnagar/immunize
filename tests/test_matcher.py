"""Tests for immunize.matcher — the deterministic pattern engine."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from immunize.matcher import (
    _COMPILED_RULES,
    guess_error_class,
    guess_languages,
    load_patterns,
    match,
    score_pattern,
)
from immunize.models import CapturePayload, Pattern


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    _COMPILED_RULES.clear()


def _payload(
    *, stderr: str = "", stdout: str = "", source: str = "manual"
) -> CapturePayload:
    return CapturePayload(
        source=source,  # type: ignore[arg-type]
        stderr=stderr,
        stdout=stdout,
        exit_code=1,
        cwd="/tmp/sandbox",
        timestamp=datetime(2026, 4, 17, tzinfo=timezone.utc),
        project_fingerprint="sha256-test",
    )


def _pattern(
    *,
    id: str = "test-pattern",
    languages: list[str] | None = None,
    stderr_patterns: list[str] | None = None,
    stdout_patterns: list[str] | None = None,
    error_class_hint: str | None = None,
    min_confidence: float = 0.70,
    error_class: str = "other",
    description: str = "test pattern",
) -> Pattern:
    return Pattern.model_validate(
        {
            "id": id,
            "version": 1,
            "author": "@test",
            "origin": "bundled",
            "error_class": error_class,
            "languages": languages or ["python"],
            "description": description,
            "match": {
                "stderr_patterns": stderr_patterns or [],
                "stdout_patterns": stdout_patterns or [],
                "error_class_hint": error_class_hint,
                "min_confidence": min_confidence,
            },
            "verification": {"pytest_relative_path": "test_template.py"},
        }
    )


def _write_pattern(root: Path, *, id: str, **overrides: object) -> Path:
    slug_dir = root / id
    slug_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = slug_dir / "pattern.yaml"
    data: dict = {
        "id": id,
        "version": 1,
        "author": "@test",
        "origin": "bundled",
        "error_class": "other",
        "languages": ["python"],
        "description": "test pattern",
        "match": {"stderr_patterns": ["foo"], "min_confidence": 0.70},
        "verification": {"pytest_relative_path": "test_template.py"},
    }
    data.update(overrides)
    yaml_path.write_text(yaml.safe_dump(data))
    return yaml_path


# --- load_patterns ----------------------------------------------------------


def test_load_patterns_reads_two_valid(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled"
    _write_pattern(bundled, id="first-pattern")
    _write_pattern(bundled, id="second-pattern")

    loaded = load_patterns(bundled)
    ids = sorted(p.id for p in loaded)
    assert ids == ["first-pattern", "second-pattern"]
    for p in loaded:
        assert p.directory is not None
        assert p.directory.name == p.id


def test_load_patterns_missing_local_returns_bundled_only(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled"
    _write_pattern(bundled, id="only-bundled")

    loaded = load_patterns(bundled, local_dir=tmp_path / "does-not-exist")
    assert [p.id for p in loaded] == ["only-bundled"]


def test_load_patterns_skips_malformed_and_warns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bundled = tmp_path / "bundled"
    _write_pattern(bundled, id="good-pattern")

    bad_dir = bundled / "bad-pattern"
    bad_dir.mkdir()
    (bad_dir / "pattern.yaml").write_text("id: 'Not-Kebab'\nversion: 1\n")

    loaded = load_patterns(bundled)
    assert [p.id for p in loaded] == ["good-pattern"]

    captured = capsys.readouterr()
    assert "skipping malformed pattern" in captured.err
    assert "bad-pattern" in captured.err


def test_load_patterns_local_overrides_bundled_on_id_clash(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled"
    local = tmp_path / "local"
    _write_pattern(bundled, id="shared-id", description="bundled description")
    _write_pattern(local, id="shared-id", description="local description")

    loaded = load_patterns(bundled, local_dir=local)
    assert len(loaded) == 1
    assert loaded[0].description == "local description"


# --- score_pattern ----------------------------------------------------------


def test_score_pattern_single_stderr_match_adds_0_3() -> None:
    pattern = _pattern(stderr_patterns=[r"CORS"])
    result = score_pattern(_payload(stderr="CORS policy blocked"), pattern)
    assert result.score_breakdown["stderr"] == pytest.approx(0.3)
    assert result.matched_stderr_patterns == [r"CORS"]


def test_score_pattern_multiple_stderr_matches_cap_at_0_6() -> None:
    pattern = _pattern(stderr_patterns=[r"CORS", r"credentials", r"Access-Control"])
    stderr = "CORS policy: include credentials via Access-Control-Allow-Credentials"
    result = score_pattern(_payload(stderr=stderr), pattern)
    assert result.score_breakdown["stderr"] == pytest.approx(0.6)
    assert len(result.matched_stderr_patterns) == 3


def test_score_pattern_stdout_matches_add_0_2_capped_at_0_4() -> None:
    one_hit = _pattern(stdout_patterns=[r"WARN"])
    result = score_pattern(_payload(stdout="WARN: deprecation"), one_hit)
    assert result.score_breakdown["stdout"] == pytest.approx(0.2)

    three_hits = _pattern(
        id="stdout-triple", stdout_patterns=[r"WARN", r"deprec", r"log"]
    )
    result = score_pattern(_payload(stdout="WARN deprecation log line"), three_hits)
    assert result.score_breakdown["stdout"] == pytest.approx(0.4)


def test_score_pattern_error_class_hint_adds_0_15() -> None:
    pattern = _pattern(stderr_patterns=[r"CORS"], error_class_hint="cors")
    result = score_pattern(
        _payload(stderr="CORS policy: preflight failed"), pattern
    )
    assert result.score_breakdown["error_class_hint"] == pytest.approx(0.15)


def test_score_pattern_no_hint_bonus_when_error_class_hint_is_none() -> None:
    # Payload clearly resembles a CORS error, but hint is None → zero bonus.
    pattern = _pattern(stderr_patterns=[r"CORS"], error_class_hint=None)
    result = score_pattern(
        _payload(stderr="CORS policy: preflight failed"), pattern
    )
    assert result.score_breakdown["error_class_hint"] == 0.0


def test_score_pattern_language_bonus_adds_0_1() -> None:
    pattern = _pattern(stderr_patterns=[r"foo"], languages=["python"])
    stderr = 'Traceback (most recent call last):\n  File "app.py", line 1\nfoo'
    result = score_pattern(_payload(stderr=stderr), pattern)
    assert result.score_breakdown["language"] == pytest.approx(0.1)


def test_score_pattern_confidence_caps_at_1_0() -> None:
    pattern = _pattern(
        stderr_patterns=[r"a", r"b", r"c"],  # +0.6
        stdout_patterns=[r"x", r"y"],  # +0.4
        error_class_hint="cors",  # +0.15
        languages=["python"],  # +0.1
    )
    stderr = "a b c CORS\nTraceback (most recent call last):"
    stdout = "x y"
    result = score_pattern(_payload(stderr=stderr, stdout=stdout), pattern)
    assert result.confidence == 1.0


def test_score_pattern_score_breakdown_keys_populated() -> None:
    pattern = _pattern(
        stderr_patterns=[r"CORS"],
        stdout_patterns=[r"WARN"],
        error_class_hint="cors",
        languages=["python"],
    )
    result = score_pattern(
        _payload(
            stderr="CORS policy\nTraceback (most recent call last):",
            stdout="WARN",
        ),
        pattern,
    )
    assert set(result.score_breakdown.keys()) == {
        "stderr",
        "stdout",
        "error_class_hint",
        "language",
    }
    assert result.score_breakdown["stderr"] == pytest.approx(0.3)
    assert result.score_breakdown["stdout"] == pytest.approx(0.2)
    assert result.score_breakdown["error_class_hint"] == pytest.approx(0.15)
    assert result.score_breakdown["language"] == pytest.approx(0.1)
    assert result.confidence == pytest.approx(0.75)


# --- match ------------------------------------------------------------------


def test_match_filters_below_threshold() -> None:
    # high: 3 stderr hits → 0.6 (clears 0.5); low: 0 hits → 0.0 (below 0.5).
    high = _pattern(
        id="high", stderr_patterns=[r"a", r"b", r"c"], min_confidence=0.5
    )
    low = _pattern(id="low", stderr_patterns=[r"z"], min_confidence=0.5)
    results = match(_payload(stderr="a b c"), [high, low])
    assert [r.pattern.id for r in results] == ["high"]


def test_match_sorts_by_confidence_descending() -> None:
    low = _pattern(id="low-c", stderr_patterns=[r"a"], min_confidence=0.1)  # 0.3
    mid = _pattern(
        id="mid-c", stderr_patterns=[r"a", r"b"], min_confidence=0.1
    )  # 0.6
    top = _pattern(
        id="top-c",
        stderr_patterns=[r"a", r"b", r"c"],
        error_class_hint="cors",
        min_confidence=0.1,
    )  # 0.6 + 0.15 = 0.75
    results = match(_payload(stderr="a b c CORS"), [low, mid, top])
    assert [r.pattern.id for r in results] == ["top-c", "mid-c", "low-c"]


# --- guess_error_class ------------------------------------------------------


@pytest.mark.parametrize(
    ("cls", "stderr"),
    [
        ("cors", "Access-Control-Allow-Credentials missing"),
        ("import", "ImportError: no module named 'foo'"),
        ("auth", "401 Unauthorized"),
        ("rate_limit", "HTTP 429 Too Many Requests"),
        ("type_error", "TypeError: x.foo is not a function"),
        ("null_ref", "Cannot read prop of undefined"),
        ("config", "required env var FOO is not set"),
        ("network", "ECONNREFUSED 127.0.0.1:5432"),
    ],
)
def test_guess_error_class_detects_each_class(cls: str, stderr: str) -> None:
    assert guess_error_class(stderr) == cls


def test_guess_error_class_returns_other_on_no_match() -> None:
    assert guess_error_class("completely unrelated gibberish") == "other"


def test_guess_error_class_returns_other_on_tie() -> None:
    # "preflight" hits cors (1); "401" hits auth (1) → 1-1 tie → "other".
    assert guess_error_class("preflight failed for 401 request") == "other"


# --- guess_languages --------------------------------------------------------


@pytest.mark.parametrize(
    ("lang", "stderr"),
    [
        (
            "python",
            'Traceback (most recent call last):\n  File "a.py", line 1\nValueError',
        ),
        (
            "javascript",
            "Uncaught ReferenceError: foo is not defined\n    at Object.<anonymous>",
        ),
        (
            "typescript",
            "src/app.ts:10:3 - error TS2322: Type 'string' is not assignable to number.",
        ),
    ],
)
def test_guess_languages_detects_canonical_tracebacks(
    lang: str, stderr: str
) -> None:
    assert lang in guess_languages(stderr)
