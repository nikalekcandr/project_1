"""Habr Career (career.habr.com) — strong for data/BI/product analytics and fintech.

Uses the JSON endpoint behind the public vacancies page; falls back to parsing
the HTML cards if the JSON shape changes.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from bs4 import BeautifulSoup

from finradar.http import HttpError
from finradar.models import Vacancy
from finradar.sources.base import Source, dig, register
from finradar.textutil import clean_ws, parse_date

BASE = "https://career.habr.com"
_CURRENCY = {"rur": "RUB", "rub": "RUB", "usd": "USD", "eur": "EUR", "kzt": "KZT", "uah": "UAH"}
_QUAL = {"intern": "intern", "junior": "junior", "middle": "middle", "senior": "senior", "lead": "lead"}


@register("habr")
class HabrCareerSource(Source):
    complete_listing = False

    def __init__(self, name, cfg, http):
        super().__init__(name, cfg, http)
        self.max_pages = int(cfg.get("max_pages", 5))

    def fetch(self) -> Iterator[Vacancy]:
        seen: set[str] = set()
        for query in self.queries() or [""]:
            for v in self._query(query):
                if v.external_id not in seen:
                    seen.add(v.external_id)
                    yield v
                    if len(seen) >= self.max_items:
                        return

    def _query(self, query: str) -> Iterator[Vacancy]:
        for page in range(1, self.max_pages + 1):
            params = {"q": query, "type": "all", "sort": "date", "page": page}
            items: list[Vacancy] = []
            try:
                data = self.http.get_json(f"{BASE}/api/frontend/vacancies", params=params)
                items = [self._from_json(it) for it in data.get("list", [])]
                total_pages = int(dig(data, "meta", "totalPages", default=page))
            except (HttpError, ValueError) as exc:
                self.warn(f"JSON endpoint failed ({exc}), falling back to HTML")
                html = self.http.get_text(f"{BASE}/vacancies", params=params, robots=True)
                items = list(self.parse_html(html))
                total_pages = page + 1 if items else page
            yield from items
            if not items or page >= total_pages:
                break

    def _from_json(self, it: dict[str, Any]) -> Vacancy:
        sal = it.get("salary") or {}
        locations = ", ".join(loc.get("title", "") for loc in it.get("locations") or [] if loc.get("title"))
        skills = [s.get("title") for s in it.get("skills") or [] if s.get("title")]
        divisions = [d.get("title") for d in it.get("divisions") or [] if d.get("title")]
        qualification = (it.get("salaryQualification") or {}).get("title") or it.get("qualification")
        href = it.get("href") or f"/vacancies/{it.get('id')}"
        return self.vacancy(
            it.get("id"),
            href if href.startswith("http") else BASE + href,
            it.get("title", ""),
            company=dig(it, "company", "title"),
            location=locations or None,
            work_format="remote" if it.get("remoteWork") else None,
            employment=it.get("employment"),
            salary_min=sal.get("from"),
            salary_max=sal.get("to"),
            salary_currency=_CURRENCY.get((sal.get("currency") or "").lower(), (sal.get("currency") or "").upper() or None),
            salary_text=sal.get("formatted"),
            published_at=parse_date(dig(it, "publishedDate", "date")),
            tags=divisions + skills,
            skills=[],
            raw={"seniority_hint": _QUAL.get(str(qualification).lower()) if qualification else None},
        )

    def parse_html(self, html: str) -> Iterator[Vacancy]:
        soup = BeautifulSoup(html, "lxml")
        for card in soup.select(".vacancy-card"):
            link = card.select_one("a.vacancy-card__title-link") or card.select_one('a[href^="/vacancies/"]')
            if not link:
                continue
            m = re.search(r"/vacancies/(\d+)", link.get("href", ""))
            if not m:
                continue
            company = card.select_one(".vacancy-card__company-title")
            salary = card.select_one(".vacancy-card__salary")
            meta = card.select_one(".vacancy-card__meta")
            date = card.select_one(".vacancy-card__date time")
            skills = [clean_ws(a.get_text()) for a in card.select(".vacancy-card__skills a")]
            meta_text = clean_ws(meta.get_text(" ")) if meta else ""
            yield self.vacancy(
                m.group(1),
                BASE + f"/vacancies/{m.group(1)}",
                clean_ws(link.get_text(" ")),
                company=clean_ws(company.get_text(" ")) if company else None,
                salary_text=clean_ws(salary.get_text(" ")) if salary and re.search(r"\d", salary.get_text()) else None,
                location=meta_text or None,
                published_at=parse_date(date.get("datetime")) if date else None,
                tags=skills,
            )
