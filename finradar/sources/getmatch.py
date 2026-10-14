"""GetMatch (getmatch.ru) — IT/analytics/fintech roles, almost always with a salary range.

GetMatch's documented Public API is employer-side only (posting vacancies,
candidates), so for job search we read the public listing: first the JSON feed the
site itself uses, then the HTML listing as a fallback. Both are configurable
because the site may change them.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from bs4 import BeautifulSoup

from finradar.http import HttpError
from finradar.models import Vacancy
from finradar.sources.base import Source, dig, register
from finradar.sources.htmlutil import card_for, guess_card_fields
from finradar.textutil import clean_ws, html_to_text, parse_date

BASE = "https://getmatch.ru"
_LINK = re.compile(r"/vacancies/(\d+)")
_CURRENCY = {"₽": "RUB", "rub": "RUB", "rur": "RUB", "$": "USD", "usd": "USD", "€": "EUR", "eur": "EUR", "₸": "KZT", "kzt": "KZT"}
_REMOTE = {"full": "remote", "remote": "remote", "hybrid": "hybrid", "office": "office", "partial": "hybrid"}


def _pick(d: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if d.get(k) not in (None, "", []):
            return d[k]
    return None


@register("getmatch")
class GetMatchSource(Source):
    complete_listing = False

    def __init__(self, name, cfg, http):
        super().__init__(name, cfg, http)
        self.api_url = cfg.get("api_url", f"{BASE}/api/offers")
        self.page_size = int(cfg.get("page_size", 50))
        self.max_pages = int(cfg.get("max_pages", 6))
        self.specializations = cfg.get("specializations") or []

    def fetch(self) -> Iterator[Vacancy]:
        seen: set[str] = set()
        try:
            gen = self._fetch_api()
            first = next(gen, None)
            if first is None:
                raise HttpError("empty JSON feed")
            items: Iterator[Vacancy] = _chain(first, gen)
        except (HttpError, ValueError, KeyError) as exc:
            self.warn(f"JSON feed unavailable ({exc}); using HTML listing")
            items = self._fetch_html()
        for v in items:
            if v.external_id not in seen:
                seen.add(v.external_id)
                yield v
                if len(seen) >= self.max_items:
                    return

    # ------------------------------------------------------------------ JSON
    def _fetch_api(self) -> Iterator[Vacancy]:
        queries = self.queries() or [""]
        for query in queries:
            for page in range(self.max_pages):
                params = {"sa": "", "pa": "all", "s": "landing_ca_header", "offset": page * self.page_size,
                          "limit": self.page_size, **(self.cfg.get("api_params") or {})}
                if query:
                    params["q"] = query
                if self.specializations:
                    params["sp"] = ",".join(self.specializations)
                data = self.http.get_json(self.api_url, params=params)
                offers = data.get("offers") if isinstance(data, dict) else data
                if offers is None and isinstance(data, dict):
                    offers = data.get("items") or data.get("data") or []
                if not offers:
                    break
                for it in offers:
                    yield self._from_json(it)
                if len(offers) < self.page_size:
                    break

    def _from_json(self, it: dict[str, Any]) -> Vacancy:
        vid = _pick(it, "id", "offer_id")
        url = _pick(it, "url", "public_url") or f"/vacancies/{vid}"
        if url.startswith("/"):
            url = BASE + url
        cur_raw = str(_pick(it, "salary_currency", "currency") or "").lower()
        locations = _pick(it, "display_locations", "locations", "location_requirements") or []
        if isinstance(locations, list):
            location = ", ".join(
                (loc.get("city") or loc.get("description") or loc.get("name") or "") if isinstance(loc, dict) else str(loc)
                for loc in locations
            ).strip(", ")
        else:
            location = str(locations)
        stack = _pick(it, "stack", "skills") or []
        seniority = _pick(it, "seniority", "seniorities")
        if isinstance(seniority, list):
            seniority = seniority[0] if seniority else None
        return self.vacancy(
            vid,
            url,
            _pick(it, "position", "title", "name") or "",
            company=dig(it, "company", "name") or _pick(it, "company_name"),
            description=html_to_text(_pick(it, "offer_description", "description", "short_description") or ""),
            location=location or None,
            work_format=_REMOTE.get(str(_pick(it, "remote_options", "work_format") or "").lower()),
            salary_min=None if it.get("salary_hidden") else _pick(it, "salary_display_from", "salary_from"),
            salary_max=None if it.get("salary_hidden") else _pick(it, "salary_display_to", "salary_to"),
            salary_currency=_CURRENCY.get(cur_raw, cur_raw.upper() or None),
            salary_gross=None if it.get("salary_is_total") is None else not bool(it.get("salary_is_total")),
            published_at=parse_date(_pick(it, "published_at", "created_at", "updated_at")),
            tags=[s if isinstance(s, str) else s.get("name", "") for s in stack],
            raw={"seniority_hint": str(seniority).lower() if seniority else None},
        )

    # ------------------------------------------------------------------ HTML
    def _fetch_html(self) -> Iterator[Vacancy]:
        for query in self.queries() or [""]:
            for page in range(1, self.max_pages + 1):
                params: dict[str, Any] = {"p": page}
                if query:
                    params["q"] = query
                if self.specializations:
                    params["sp"] = ",".join(self.specializations)
                html = self.http.get_text(f"{BASE}/vacancies", params=params, robots=True)
                items = list(self.parse_html(html))
                if not items:
                    break
                yield from items

    def parse_html(self, html: str) -> Iterator[Vacancy]:
        soup = BeautifulSoup(html, "lxml")
        done: set[str] = set()
        for a in soup.find_all("a", href=_LINK):
            vid = _LINK.search(a["href"]).group(1)
            if vid in done:
                continue
            title = clean_ws(a.get_text(" "))
            if not title or len(title) < 3:
                continue
            done.add(vid)
            card = card_for(a, _LINK)
            f = guess_card_fields(card)
            yield self.vacancy(
                vid,
                f"{BASE}/vacancies/{vid}",
                title,
                company=f.get("company"),
                salary_text=f.get("salary_text"),
                location=f.get("location"),
                description=clean_ws(card.get_text(" "))[:1500],
            )


def _chain(first, rest):
    yield first
    yield from rest
