"""Source plug-in contract and registry."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar

from finradar.http import HttpClient
from finradar.models import Vacancy

log = logging.getLogger(__name__)

REGISTRY: dict[str, type[Source]] = {}


def register(type_name: str):
    def deco(cls: type[Source]) -> type[Source]:
        cls.type_name = type_name
        REGISTRY[type_name] = cls
        return cls

    return deco


class SourceConfigError(Exception):
    pass


class Source:
    """A configured instance of a connector.

    ``complete_listing`` tells the pipeline whether a posting missing from a
    successful run can be considered closed (true for API/listing sources, false
    for streams like Telegram, RSS and e-mail alerts, which use ``ttl_days``).
    """

    type_name: ClassVar[str] = ""
    complete_listing: ClassVar[bool] = True
    default_ttl_days: ClassVar[int] = 45
    needs: ClassVar[tuple[str, ...]] = ()  # required config keys

    def __init__(self, name: str, cfg: dict[str, Any], http: HttpClient):
        self.name = name
        self.cfg = cfg
        self.http = http
        self.max_items = int(cfg.get("max_items", 1000))
        self.max_age_days = int(cfg.get("max_age_days", 30))
        self.ttl_days = int(cfg.get("ttl_days", self.default_ttl_days))
        self.warnings: list[str] = []
        self.partial = False  # set when part of the listing failed: don't close missing postings
        missing = [k for k in self.needs if not cfg.get(k)]
        if missing:
            raise SourceConfigError(f"{name}: missing config keys {missing}")

    # Subclasses implement this.
    def fetch(self) -> Iterator[Vacancy]:  # pragma: no cover - interface
        raise NotImplementedError

    # ------------------------------------------------------------------ helpers
    def vacancy(self, external_id: Any, url: str, title: str, **kw: Any) -> Vacancy:
        return Vacancy(source=self.name, external_id=str(external_id), url=url, title=title or "", **kw)

    def too_old(self, published: datetime | None) -> bool:
        if not published:
            return False
        return published < datetime.now(timezone.utc) - timedelta(days=self.max_age_days)

    def warn(self, message: str) -> None:
        log.warning("[%s] %s", self.name, message)
        self.warnings.append(message)

    def queries(self, key: str = "queries") -> list[str]:
        q = self.cfg.get(key) or []
        return [q] if isinstance(q, str) else list(q)


def as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def dig(obj: Any, *path: Any, default: Any = None) -> Any:
    """Safe nested get: dig(d, "a", 0, "b")."""
    cur = obj
    for key in path:
        if cur is None:
            return default
        if isinstance(key, int):
            if not isinstance(cur, list) or len(cur) <= key:
                return default
            cur = cur[key]
        else:
            if not isinstance(cur, dict):
                return default
            cur = cur.get(key)
    return default if cur is None else cur
