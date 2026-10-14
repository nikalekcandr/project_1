"""hh.ru (and mirrors hh.kz, hh.uz, rabota.by).

Since April 2026 anonymous ``GET api.hh.ru/vacancies`` returns 403, so this
connector has two modes:

* ``api``  — official API with an application token (``HH_ACCESS_TOKEN``), available to
  registered applications (in practice: employer accounts / HR services);
* ``html`` — polite parsing of the public search page (``hh.ru/search/vacancy``),
  ~1 request every 2 s, stops immediately on captcha. Check hh.ru's terms before
  using it beyond personal use.

``mode: auto`` picks ``api`` when a token is configured, otherwise ``html``.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from typing import Any

from bs4 import BeautifulSoup

from finradar.http import BlockedError
from finradar.models import Vacancy
from finradar.sources.base import Source, as_list, dig, register
from finradar.textutil import clean_ws, html_to_text, parse_date

_CURRENCY = {"RUR": "RUB", "RUB": "RUB", "USD": "USD", "EUR": "EUR", "KZT": "KZT", "BYR": "BYN", "BYN": "BYN", "UZS": "UZS"}
_SCHEDULE_FORMAT = {"remote": "remote", "flyInFlyOut": "office", "fullDay": "office", "shift": "office"}
_WORK_FORMAT = {"REMOTE": "remote", "HYBRID": "hybrid", "ON_SITE": "office", "FIELD_WORK": "office"}
_EMPLOYMENT = {"full": "full", "part": "part", "project": "contract", "probation": "internship", "volunteer": "part"}
_VAC_ID = re.compile(r"/vacancy/(\d+)")


@register("hh")
class HHSource(Source):
    complete_listing = False  # we only see the first pages of each query

    def __init__(self, name, cfg, http):
        super().__init__(name, cfg, http)
        self.domain = cfg.get("domain", "hh.ru")
        self.token = cfg.get("access_token") or os.environ.get("HH_ACCESS_TOKEN")
        mode = cfg.get("mode", "auto")
        self.mode = ("api" if self.token else "html") if mode == "auto" else mode
        self.areas = [str(a) for a in as_list(cfg.get("areas"))]
        self.roles = [str(r) for r in as_list(cfg.get("professional_roles"))]
        self.period = min(int(cfg.get("period_days", 7)), 30)
        self.max_pages = int(cfg.get("max_pages", 5))
        self.min_interval = float(cfg.get("min_interval", 2.0))

    def fetch(self) -> Iterator[Vacancy]:
        seen: set[str] = set()
        queries = self.queries() or [""]
        for query in queries:
            gen = self._fetch_api(query) if self.mode == "api" else self._fetch_html(query)
            for v in gen:
                if v.external_id in seen:
                    continue
                seen.add(v.external_id)
                yield v
                if len(seen) >= self.max_items:
                    return

    # ------------------------------------------------------------------ API mode
    def _fetch_api(self, query: str) -> Iterator[Vacancy]:
        headers = {
            "HH-User-Agent": self.cfg.get("hh_user_agent", "finradar/0.1 (personal job search)"),
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        for page in range(self.max_pages):
            params: list[tuple[str, Any]] = [
                ("text", query), ("per_page", 100), ("page", page), ("period", self.period),
                ("order_by", "publication_time"),
            ]
            params += [("area", a) for a in self.areas] + [("professional_role", r) for r in self.roles]
            data = self.http.get_json(f"https://api.{self.domain}/vacancies", params=params, headers=headers)
            for item in data.get("items", []):
                yield self._from_api(item)
            if page + 1 >= int(data.get("pages", 0)):
                break

    def _from_api(self, it: dict[str, Any]) -> Vacancy:
        sal = it.get("salary") or it.get("salary_range") or {}
        work_formats = [_WORK_FORMAT.get(dig(w, "id")) for w in as_list(it.get("work_format"))]
        fmt = "hybrid" if "hybrid" in work_formats else next((w for w in work_formats if w), None)
        fmt = fmt or _SCHEDULE_FORMAT.get(dig(it, "schedule", "id"))
        snippet = " ".join(filter(None, [dig(it, "snippet", "responsibility"), dig(it, "snippet", "requirement")]))
        return self.vacancy(
            it["id"],
            it.get("alternate_url") or f"https://{self.domain}/vacancy/{it['id']}",
            it.get("name", ""),
            company=dig(it, "employer", "name"),
            description=html_to_text(snippet),
            location=dig(it, "area", "name"),
            work_format=fmt,
            employment=_EMPLOYMENT.get(dig(it, "employment", "id")),
            salary_min=sal.get("from"),
            salary_max=sal.get("to"),
            salary_currency=_CURRENCY.get(sal.get("currency") or "", sal.get("currency")),
            salary_gross=sal.get("gross"),
            published_at=parse_date(it.get("published_at")),
            tags=[r.get("name") for r in it.get("professional_roles", []) if r.get("name")],
            raw={"seniority_hint": dig(it, "experience", "id"), "employer_id": dig(it, "employer", "id")},
        )

    # ------------------------------------------------------------------ HTML mode
    def _fetch_html(self, query: str) -> Iterator[Vacancy]:
        url = f"https://{self.domain}/search/vacancy"
        for page in range(self.max_pages):
            params: list[tuple[str, Any]] = [
                ("text", query), ("page", page), ("items_on_page", 50), ("order_by", "publication_time"),
                ("search_period", self.period),
            ]
            params += [("area", a) for a in self.areas] + [("professional_role", r) for r in self.roles]
            html = self.http.get_text(url, params=params, browser_ua=True, min_interval=self.min_interval)
            items = list(self.parse_search_page(html))
            if not items:
                if "captcha" in html.lower():
                    raise BlockedError(f"captcha on {self.domain}", url=url)
                break
            yield from items
            if len(items) < 20:
                break

    def parse_search_page(self, html: str) -> Iterator[Vacancy]:
        soup = BeautifulSoup(html, "lxml")
        state_items = list(self._from_initial_state(soup))
        if state_items:
            yield from state_items
            return
        for card in soup.select('[data-qa~="vacancy-serp__vacancy"]'):
            link = card.select_one('a[data-qa="serp-item__title"]') or card.select_one('a[href*="/vacancy/"]')
            if not link:
                continue
            m = _VAC_ID.search(link.get("href", ""))
            if not m:
                continue
            vid = m.group(1)
            title_el = card.select_one('[data-qa="serp-item__title-text"]') or link
            company = card.select_one('[data-qa="vacancy-serp__vacancy-employer-text"]') or card.select_one(
                '[data-qa="vacancy-serp__vacancy-employer"]'
            )
            address = card.select_one('[data-qa="vacancy-serp__vacancy-address"]')
            salary_el = card.select_one('[data-qa^="vacancy-serp__vacancy-compensation"]')
            salary_text = clean_ws(salary_el.get_text(" ")) if salary_el else self._salary_from_card(card)
            exp_el = card.select_one('[data-qa^="vacancy-serp__vacancy-work-experience"]')
            hint = None
            if exp_el:
                hint = exp_el.get("data-qa", "").rsplit("-", 1)[-1]
            snippet = " ".join(
                clean_ws(el.get_text(" "))
                for el in card.select('[data-qa^="vacancy-serp__vacancy_snippet"]')
            )
            card_text = clean_ws(card.get_text(" "))
            yield self.vacancy(
                vid,
                f"https://{self.domain}/vacancy/{vid}",
                clean_ws(title_el.get_text(" ")),
                company=clean_ws(company.get_text(" ")) if company else None,
                location=clean_ws(address.get_text(" ")) if address else None,
                salary_text=salary_text or None,
                salary_currency="RUB" if self.domain == "hh.ru" else None,
                description=snippet,
                work_format="remote" if re.search(r"удал[её]нн?о", card_text, re.I) else None,
                raw={"seniority_hint": hint, "mode": "html"},
            )

    @staticmethod
    def _salary_from_card(card) -> str | None:
        for el in card.find_all(["span", "div"]):
            text = clean_ws(el.get_text(" "))
            if len(text) < 60 and re.search(r"\d.*(?:₽|\$|€|₸|руб|сум|br)", text, re.I):
                return text
        return None

    def _from_initial_state(self, soup: BeautifulSoup) -> Iterator[Vacancy]:
        tpl = soup.find("template", id="HH-Lux-InitialState")
        if not tpl:
            return
        try:
            state = json.loads(tpl.string or tpl.get_text())
        except (TypeError, ValueError):
            return
        for it in dig(state, "vacancySearchResult", "vacancies", default=[]):
            vid = it.get("vacancyId")
            if not vid:
                continue
            comp = it.get("compensation") or {}
            pub = dig(it, "publicationTime", "$") or it.get("publicationTime")
            snippet = " ".join(filter(None, [dig(it, "snippet", "resp"), dig(it, "snippet", "req")]))
            yield self.vacancy(
                vid,
                dig(it, "links", "desktop") or f"https://{self.domain}/vacancy/{vid}",
                it.get("name", ""),
                company=dig(it, "company", "visibleName") or dig(it, "company", "name"),
                location=dig(it, "area", "name"),
                description=html_to_text(snippet),
                salary_min=None if comp.get("noCompensation") else comp.get("from"),
                salary_max=None if comp.get("noCompensation") else comp.get("to"),
                salary_currency=_CURRENCY.get(comp.get("currencyCode") or "", comp.get("currencyCode")),
                salary_gross=comp.get("gross"),
                published_at=parse_date(pub),
                raw={"seniority_hint": dig(it, "workExperience"), "mode": "html-state"},
            )
