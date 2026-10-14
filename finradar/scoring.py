"""Personal relevance score (0-100) with human-readable reasons.

Driven entirely by ``config/profile.yaml`` so you can tune what "a good match" means.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from finradar.models import SENIORITIES, dumps
from finradar.storage import Store, parse_ts
from finradar.taxonomy import DOMAIN_SHORT
from finradar.textutil import norm_company

_DEFAULT_KIND_WEIGHT = {
    "vacancy": 1.0, "internship": 0.6, "graduate_program": 0.7, "fellowship": 0.7,
    "academic": 0.6, "grant": 0.5, "competition": 0.4, "event": 0.3,
}


@dataclass
class Profile:
    domains: dict[str, float] = field(default_factory=dict)
    kinds: dict[str, float] = field(default_factory=lambda: dict(_DEFAULT_KIND_WEIGHT))
    seniority: list[str] = field(default_factory=list)
    keywords: dict[str, float] = field(default_factory=dict)
    negative_keywords: dict[str, float] = field(default_factory=dict)
    min_salary_rub_month: float | None = None
    min_salary_usd_year: float | None = None
    locations: list[str] = field(default_factory=list)
    work_format: dict[str, float] = field(default_factory=dict)
    languages: list[str] = field(default_factory=list)
    favorite_companies: list[str] = field(default_factory=list)
    exclude_companies: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        def compile_kw(d: dict[str, float]) -> list[tuple[re.Pattern, float]]:
            return [(re.compile(k[3:] if k.startswith("re:") else re.escape(k), re.I), w) for k, w in d.items()]

        self._kw = compile_kw(self.keywords)
        self._neg = compile_kw(self.negative_keywords)
        self._fav = {norm_company(c) for c in self.favorite_companies}
        self._excl = {norm_company(c) for c in self.exclude_companies}
        self._loc = [loc.lower() for loc in self.locations]

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> Profile:
        d = dict(d or {})
        salary = d.pop("min_salary", {}) or {}
        return cls(
            domains={k: float(v) for k, v in (d.get("domains") or {}).items()},
            kinds={**_DEFAULT_KIND_WEIGHT, **{k: float(v) for k, v in (d.get("kinds") or {}).items()}},
            seniority=list(d.get("seniority") or []),
            keywords={k: float(v) for k, v in (d.get("keywords") or {}).items()},
            negative_keywords={k: float(v) for k, v in (d.get("negative_keywords") or {}).items()},
            min_salary_rub_month=salary.get("rub_month"),
            min_salary_usd_year=salary.get("usd_year"),
            locations=list(d.get("locations") or []),
            work_format={k: float(v) for k, v in (d.get("work_format") or {}).items()},
            languages=list(d.get("languages") or []),
            favorite_companies=list(d.get("favorite_companies") or []),
            exclude_companies=list(d.get("exclude_companies") or []),
        )


def _label(rx: re.Pattern) -> str:
    """Readable name for a keyword; for regex keywords, the longest plain alternative."""
    pattern = re.sub(r"\(\?<?[=!][^)]*\)", "", rx.pattern)  # drop lookarounds
    parts = [re.sub(r"\\[bBsSwWdD]|[\\^$()?*+\[\]{}.]", "", p).strip() for p in pattern.split("|")]
    parts = [p for p in parts if p]
    return max(parts, key=len) if parts else rx.pattern


def score_row(row: dict[str, Any], profile: Profile, now: datetime | None = None) -> tuple[float, list[str]]:
    now = now or datetime.now(timezone.utc)
    reasons: list[str] = []
    title = row.get("title") or ""
    desc = (row.get("description") or "")[:6000]
    company_key = row.get("company_key") or norm_company(row.get("company"))

    if company_key and company_key in profile._excl:
        return 0.0, ["компания в списке исключений"]

    score = 0.0
    domains = row.get("domains") or []
    if profile.domains and domains:
        weights = [profile.domains.get(d, 0.0) * (1.0 if i == 0 else 0.6) for i, d in enumerate(domains)]
        best = max(weights)
        if best > 0:
            score += 35 * best
            reasons.append(DOMAIN_SHORT.get(domains[weights.index(best)], domains[weights.index(best)]))
    elif not profile.domains and domains:
        score += 20

    kw_points = 0.0
    for rx, w in profile._kw:
        if rx.search(title):
            kw_points += 2 * w
            reasons.append(f"+{_label(rx)} в названии")
        elif rx.search(desc):
            kw_points += w
    score += min(kw_points, 25)

    for rx, w in profile._neg:
        if rx.search(title) or rx.search(desc[:1500]):
            score -= abs(w)
            reasons.append(f"−{_label(rx)}")

    seniority = row.get("seniority")
    if profile.seniority:
        if seniority in profile.seniority:
            score += 10
            reasons.append(f"уровень {seniority}")
        elif seniority is None:
            score += 5
        elif seniority in SENIORITIES:
            idx = SENIORITIES.index(seniority)
            near = any(abs(idx - SENIORITIES.index(s)) == 1 for s in profile.seniority if s in SENIORITIES)
            score += 4 if near else -6

    rub, usd = row.get("salary_month_rub"), row.get("salary_year_usd")
    floor_rub, floor_usd = profile.min_salary_rub_month, profile.min_salary_usd_year
    if rub is None and usd is None:
        score += 6
    else:
        ok = (floor_rub and rub and rub >= floor_rub) or (floor_usd and usd and usd >= floor_usd)
        low = (floor_rub and rub and rub < floor_rub * 0.8) and not (floor_usd and usd and usd >= floor_usd)
        if ok or (not floor_rub and not floor_usd):
            score += 15
            reasons.append("зарплата ≥ цели" if ok else "зарплата указана")
        elif low:
            score -= 10
            reasons.append("зарплата ниже цели")
        else:
            score += 3

    fmt = row.get("work_format")
    loc_text = " ".join(filter(None, [row.get("city"), row.get("country"), row.get("location")])).lower()
    loc_points = 0.0
    if fmt and profile.work_format:
        loc_points = 10 * profile.work_format.get(fmt, 0.0)
        if fmt == "remote" and profile.work_format.get("remote", 0) >= 0.8:
            reasons.append("удалёнка")
    if profile._loc and loc_text and any(loc in loc_text for loc in profile._loc):
        loc_points = max(loc_points, 10)
        reasons.append(f"локация: {row.get('city') or row.get('country') or row.get('location')}")
    elif not fmt and not loc_text:
        loc_points = 3
    score += loc_points

    if profile.languages and row.get("language") and row["language"] not in profile.languages:
        score -= 10

    published = parse_ts(row.get("published_at")) or parse_ts(row.get("first_seen"))
    if published:
        age_days = (now - published).total_seconds() / 86400
        score += 5 if age_days <= 2 else 3 if age_days <= 7 else 1 if age_days <= 30 else 0

    if company_key and company_key in profile._fav:
        score += 8
        reasons.append("компания из избранного")

    score *= profile.kinds.get(row.get("kind") or "vacancy", 1.0)

    llm = row.get("llm")
    if isinstance(llm, dict) and "fit_score" in llm:
        fit = max(0, min(100, int(llm.get("fit_score") or 0)))
        score = 0.6 * score + 0.4 * fit
        if llm.get("fit_reasons"):
            reasons.insert(0, f"LLM {fit}: {llm['fit_reasons'][0]}")
        if llm.get("is_relevant") is False:
            score *= 0.2
            reasons.insert(0, "LLM: вне профиля")
    return round(max(0.0, min(100.0, score)), 1), reasons[:6]


def rescore(store: Store, profile: Profile, only_active: bool = True) -> int:
    from finradar.storage import row_to_dict

    where = "is_active=1" if only_active else "1=1"
    updates = []
    now = datetime.now(timezone.utc)
    for row in store.iter_rows(where):
        d = row_to_dict(row)
        d["company_key"] = row["company_key"]
        s, reasons = score_row(d, profile, now)
        updates.append((s, dumps(reasons), row["uid"]))
    if updates:
        store.bulk_update("UPDATE vacancies SET score=?, score_reasons=? WHERE uid=?", updates)
    return len(updates)
