"""Unified data model shared by every source, the storage layer and analytics."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from typing import Any

# Opportunity kinds: a regular job is only one of them.
KINDS = (
    "vacancy",
    "internship",
    "graduate_program",
    "fellowship",
    "academic",
    "grant",
    "competition",
    "event",
)

SENIORITIES = ("intern", "junior", "middle", "senior", "lead", "head", "c_level")

WORK_FORMATS = ("remote", "hybrid", "office")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


@dataclass
class Vacancy:
    """One posting as collected from one source.

    Sources fill in what they know; :mod:`finradar.enrich` derives the rest
    (domains, seniority, skills, normalized salary, ...).
    """

    source: str
    external_id: str
    url: str
    title: str
    company: str | None = None
    description: str = ""
    location: str | None = None
    city: str | None = None
    country: str | None = None
    work_format: str | None = None  # remote / hybrid / office
    employment: str | None = None  # full / part / contract / internship / temporary
    seniority: str | None = None
    kind: str = "vacancy"

    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None  # ISO 4217
    salary_period: str | None = None  # month / year / day / hour
    salary_gross: bool | None = None
    salary_text: str | None = None

    published_at: datetime | None = None
    deadline: datetime | None = None

    tags: list[str] = field(default_factory=list)  # raw tags/categories from the source
    skills: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    primary_domain: str | None = None
    language: str | None = None  # ru / en

    # Derived by enrichment
    salary_month_rub: float | None = None
    salary_year_usd: float | None = None
    relevance: float = 0.0  # how strongly it belongs to finance/econ/analytics

    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def uid(self) -> str:
        return f"{self.source}:{self.external_id}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("published_at", "deadline"):
            if d[k] is not None:
                d[k] = d[k].isoformat()
        d["uid"] = self.uid
        return d

    @classmethod
    def field_names(cls) -> list[str]:
        return [f.name for f in fields(cls)]


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str, sort_keys=True)
