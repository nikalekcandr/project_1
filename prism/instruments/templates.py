"""Шаблоны термшитов: структура = конфигурация.

Шаблон — YAML-файл с блоком ``meta`` (описание и параметры) и блоком
``trade`` (текст сделки с подстановками Jinja2). Новая структура из
термшита добавляется новым шаблоном или прямо YAML-файлом сделки — без
изменения кода движка.
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined

from .schema import Trade, load_trade

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "data" / "templates"

_env = Environment(undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)


def _add_months(d: date, k: int) -> date:
    from ..core.dates import add_months
    return add_months(d, k)


_env.globals.update(add_months=_add_months, date=date, timedelta=timedelta)
_env.filters["d"] = lambda x: (x if isinstance(x, str) else x.isoformat())


@lru_cache(maxsize=None)
def _load(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def list_templates() -> list[dict[str, Any]]:
    out = []
    for p in sorted(TEMPLATE_DIR.glob("*.yaml")):
        meta = _load(str(p))["meta"]
        out.append({"id": p.stem, **meta})
    return out


def template_meta(tid: str) -> dict:
    return _load(str(TEMPLATE_DIR / f"{tid}.yaml"))["meta"]


def _coerce(spec: dict, v: Any) -> Any:
    t = spec.get("type", "str")
    if v is None:
        return None
    if t == "float":
        return float(v)
    if t == "int":
        return int(v)
    if t == "date":
        return v if isinstance(v, date) else date.fromisoformat(str(v))
    if t == "bool":
        return v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "да")
    return str(v)


def render(tid: str, params: dict[str, Any] | None = None) -> dict:
    raw = _load(str(TEMPLATE_DIR / f"{tid}.yaml"))
    meta = raw["meta"]
    vals: dict[str, Any] = {}
    for name, spec in meta.get("params", {}).items():
        vals[name] = _coerce(spec, (params or {}).get(name, spec.get("default")))
    unknown = set(params or {}) - set(meta.get("params", {}))
    if unknown:
        raise ValueError(f"неизвестные параметры шаблона {tid}: {sorted(unknown)}")
    text = _env.from_string(raw["trade"]).render(**vals)
    data = yaml.safe_load(text)
    data.setdefault("product_type", tid)
    return data


def build(tid: str, params: dict[str, Any] | None = None) -> Trade:
    return load_trade(render(tid, params))
