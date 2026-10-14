"""Configuration loading (YAML with ${ENV_VAR} / ${ENV_VAR:-default} interpolation)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_ENV = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")

DEFAULT_SETTINGS: dict[str, Any] = {
    "db": "data/finradar.db",
    "user_agent": "finradar/0.1 (+personal job-search aggregator)",
    "min_interval": 1.0,
    "timeout": 25,
    "respect_robots": True,
    "max_workers": 6,
    "min_relevance": 3.0,
    "fx": {"live": True, "rates": {}},
    "report_dir": "reports",
    "dedup_priority": {},
    "telegram": {},
    "llm": {"model": "claude-opus-5-5", "effort": "low", "max_per_run": 50, "min_score": 40},
}


def _interpolate(value: Any) -> Any:
    if isinstance(value, str):
        def repl(m: re.Match) -> str:
            return os.environ.get(m.group(1), m.group(2) if m.group(2) is not None else "")

        out = _ENV.sub(repl, value)
        return out if out != "" or not _ENV.search(value) else None
    if isinstance(value, list):
        return [_interpolate(v) for v in value]
    if isinstance(value, dict):
        return {k: _interpolate(v) for k, v in value.items()}
    return value


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal .env loader (KEY=VALUE lines); existing environment wins."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


@dataclass
class Config:
    settings: dict[str, Any]
    sources: list[dict[str, Any]]
    profile: dict[str, Any] = field(default_factory=dict)
    base_dir: Path = Path(".")

    @property
    def db_path(self) -> Path:
        p = Path(self.settings["db"])
        return p if p.is_absolute() else self.base_dir / p

    def enabled_sources(self, only: list[str] | None = None) -> list[dict[str, Any]]:
        out = []
        for s in self.sources:
            if only:
                if s["name"] in only or s["type"] in only:
                    out.append(s)
            elif s.get("enabled", True):
                out.append(s)
        return out


def _deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in (extra or {}).items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config(sources_path: str | Path, profile_path: str | Path | None = None) -> Config:
    sources_path = Path(sources_path)
    load_dotenv(sources_path.parent.parent / ".env")
    load_dotenv(".env")
    raw = yaml.safe_load(sources_path.read_text(encoding="utf-8")) or {}
    raw = _interpolate(raw)
    settings = _deep_merge(DEFAULT_SETTINGS, raw.get("settings") or {})
    sources = []
    names: set[str] = set()
    for item in raw.get("sources") or []:
        if not item.get("type"):
            raise ValueError(f"source without type: {item}")
        item.setdefault("name", item["type"])
        if item["name"] in names:
            raise ValueError(f"duplicate source name: {item['name']}")
        names.add(item["name"])
        sources.append(item)
    profile: dict[str, Any] = {}
    if profile_path and Path(profile_path).exists():
        profile = (_interpolate(yaml.safe_load(Path(profile_path).read_text(encoding="utf-8"))) or {}).get("profile", {})
    base_dir = sources_path.resolve().parent.parent if sources_path.parent.name == "config" else sources_path.resolve().parent
    return Config(settings=settings, sources=sources, profile=profile, base_dir=base_dir)
