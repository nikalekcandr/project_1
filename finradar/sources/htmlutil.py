"""Generic helpers to pull structured postings out of arbitrary HTML."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from finradar.textutil import clean_ws, html_to_text, parse_date

_SALARY_TEXT = re.compile(r"\d[\d\s .,]*\s*(?:k|к|тыс\.?|млн)?\s*(?:₽|руб|\$|€|£|₸|usd|eur|rub|gbp|aed)|(?:₽|\$|€|£|usd|eur|rub|gbp|aed)\s*\d", re.I)


def iter_jsonld(soup: BeautifulSoup) -> Iterator[dict[str, Any]]:
    for script in soup.find_all("script", type=lambda t: t and "ld+json" in t):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw.strip().rstrip(";"))
        except ValueError:
            # Some sites put several objects or HTML entities inside
            try:
                data = json.loads(re.sub(r"[\x00-\x1f]", " ", raw))
            except ValueError:
                continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            obj = stack.pop(0)
            if isinstance(obj, list):
                stack.extend(obj)
            elif isinstance(obj, dict):
                if "@graph" in obj:
                    stack.extend(obj["@graph"] if isinstance(obj["@graph"], list) else [obj["@graph"]])
                yield obj


def _type_is(obj: dict, name: str) -> bool:
    t = obj.get("@type")
    return name in t if isinstance(t, list) else t == name


def find_job_postings(soup: BeautifulSoup) -> list[dict[str, Any]]:
    return [o for o in iter_jsonld(soup) if _type_is(o, "JobPosting")]


def _first(value: Any) -> Any:
    return value[0] if isinstance(value, list) and value else value


def jobposting_fields(jp: dict[str, Any]) -> dict[str, Any]:
    """Map a schema.org JobPosting to Vacancy keyword arguments."""
    org = _first(jp.get("hiringOrganization")) or {}
    company = org.get("name") if isinstance(org, dict) else str(org)
    locs = jp.get("jobLocation")
    loc_parts: list[str] = []
    country = None
    for loc in locs if isinstance(locs, list) else [locs]:
        if not isinstance(loc, dict):
            continue
        addr = loc.get("address") or {}
        if isinstance(addr, str):
            loc_parts.append(addr)
            continue
        city = addr.get("addressLocality")
        region = addr.get("addressRegion")
        ctry = addr.get("addressCountry")
        if isinstance(ctry, dict):
            ctry = ctry.get("name")
        country = country or ctry
        loc_parts.append(", ".join(str(p) for p in (city, region, ctry) if p))
    remote = jp.get("jobLocationType") == "TELECOMMUTE" or bool(jp.get("applicantLocationRequirements") and not locs)
    base = jp.get("baseSalary") or jp.get("estimatedSalary") or {}
    base = _first(base) or {}
    value = base.get("value") if isinstance(base, dict) else None
    sal_min = sal_max = None
    unit = None
    if isinstance(value, dict):
        sal_min = value.get("minValue") or value.get("value")
        sal_max = value.get("maxValue") or value.get("value")
        unit = value.get("unitText")
    elif isinstance(value, (int, float, str)):
        sal_min = sal_max = value
    period = {"YEAR": "year", "MONTH": "month", "WEEK": None, "DAY": "day", "HOUR": "hour"}.get(str(unit or "").upper())
    employment = _first(jp.get("employmentType"))
    ident = jp.get("identifier")
    if isinstance(ident, dict):
        ident = ident.get("value")

    def num(x):
        try:
            return float(str(x).replace(" ", "").replace(",", "."))
        except (TypeError, ValueError):
            return None

    return {
        "title": clean_ws(jp.get("title") or jp.get("name") or ""),
        "company": company,
        "description": html_to_text(jp.get("description") or ""),
        "location": "; ".join(p for p in loc_parts if p) or None,
        "country_raw": country,
        "work_format": "remote" if remote else None,
        "employment": {"FULL_TIME": "full", "PART_TIME": "part", "CONTRACTOR": "contract", "TEMPORARY": "temporary",
                       "INTERN": "internship"}.get(str(employment or "").upper()),
        "salary_min": num(sal_min),
        "salary_max": num(sal_max),
        "salary_currency": (base.get("currency") if isinstance(base, dict) else None) or None,
        "salary_period": period,
        "published_at": parse_date(jp.get("datePosted")),
        "deadline": parse_date(jp.get("validThrough")),
        "identifier": ident,
        "url": jp.get("url"),
    }


def card_for(anchor: Tag, link_re: re.Pattern, max_up: int = 6) -> Tag:
    """Climb from a link to the largest ancestor that still contains only this posting."""
    own = link_re.search(anchor.get("href", ""))
    own_id = own.group(0) if own else None
    card = anchor
    for _ in range(max_up):
        parent = card.parent
        if parent is None or parent.name in ("body", "html", "[document]"):
            break
        ids = {m.group(0) for a in parent.find_all("a", href=True) if (m := link_re.search(a["href"]))}
        if len(ids - {own_id}) > 0:
            break
        card = parent
    return card


def guess_card_fields(card: Tag) -> dict[str, Any]:
    """Heuristics for list cards without semantic markup."""
    out: dict[str, Any] = {}
    for el in card.find_all(True):
        cls = " ".join(el.get("class", [])).lower() + " " + (el.get("data-qa") or "").lower()
        text = clean_ws(el.get_text(" "))
        if not text or len(text) > 200:
            continue
        if "company" not in out and re.search(r"company|employer|компани|работодател", cls):
            out["company"] = text
        elif "salary_text" not in out and re.search(r"salary|compensation|зарплат|price", cls):
            out["salary_text"] = text
        elif "location" not in out and re.search(r"location|city|address|город|локац|geo", cls):
            out["location"] = text
        elif "date" not in out and (el.name == "time" or re.search(r"date|time|published", cls)):
            out["date"] = el.get("datetime") or text
    if "salary_text" not in out:
        m = _SALARY_TEXT.search(clean_ws(card.get_text(" ")))
        if m:
            start = max(0, m.start() - 25)
            out["salary_text"] = clean_ws(card.get_text(" "))[start : m.end() + 25]
    return out


def absolute(base: str, href: str) -> str:
    return urljoin(base, href)


def meta_content(soup: BeautifulSoup, *names: str) -> str | None:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return clean_ws(tag["content"])
    return None
