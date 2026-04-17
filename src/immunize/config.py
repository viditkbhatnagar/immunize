from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

from immunize.models import Settings


DEFAULTS: dict[str, Any] = {
    "model": "claude-sonnet-4-6",
    "generate_semgrep": False,
    "verify_timeout_seconds": 30,
    "verify_retry_count": 1,
}


def load_settings(
    *,
    cli_overrides: dict[str, Any] | None = None,
    cwd: Path | None = None,
) -> Settings:
    project_dir = (cwd or Path.cwd()).resolve()
    state_db_path = project_dir / ".immunize" / "state.db"

    merged: dict[str, Any] = dict(DEFAULTS)
    merged.update(_read_toml(_user_config_path()))
    merged.update(_read_toml(project_dir / ".immunize" / "config.toml"))
    merged.update(_read_env())
    if cli_overrides:
        merged.update(cli_overrides)

    merged["project_dir"] = project_dir
    merged["state_db_path"] = state_db_path
    return Settings(**merged)


def _user_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "immunize" / "config.toml"


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        doc = tomllib.load(f)
    return _flatten(doc)


def _flatten(doc: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "model" in doc:
        out["model"] = doc["model"]
    generate = doc.get("generate") or {}
    if "semgrep" in generate:
        out["generate_semgrep"] = generate["semgrep"]
    verify = doc.get("verify") or {}
    if "timeout_seconds" in verify:
        out["verify_timeout_seconds"] = verify["timeout_seconds"]
    if "retry_count" in verify:
        out["verify_retry_count"] = verify["retry_count"]
    return out


def _read_env() -> dict[str, Any]:
    out: dict[str, Any] = {}
    if (v := os.environ.get("IMMUNIZE_MODEL")) is not None:
        out["model"] = v
    if (v := os.environ.get("IMMUNIZE_GENERATE_SEMGREP")) is not None:
        out["generate_semgrep"] = _parse_bool(v)
    if (v := os.environ.get("IMMUNIZE_VERIFY_TIMEOUT_SECONDS")) is not None:
        out["verify_timeout_seconds"] = int(v)
    if (v := os.environ.get("IMMUNIZE_VERIFY_RETRY_COUNT")) is not None:
        out["verify_retry_count"] = int(v)
    return out


def _parse_bool(s: str) -> bool:
    return s.strip().lower() in ("1", "true", "yes", "on")
