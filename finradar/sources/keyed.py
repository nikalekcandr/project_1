"""Official job-search APIs.

Russian market
* SuperJob     https://api.superjob.ru/2.0/vacancies/  (free key: X-Api-App-Id)
* Trudvsem     http://opendata.trudvsem.ru/api/v1/vacancies (open data «Работа России», no key)

International (free keys)
* Adzuna       https://api.adzuna.com/v1/api/jobs/<country>/search/<page>  (UK, US, DE, NL, SG, ...)
* USAJOBS      https://data.usajobs.gov/api/search   (economists, financial analysts in US federal agencies)
* Reed         https://www.reed.co.uk/api/1.0/search  (UK)
* Jooble       https://jooble.org/api/<key>          (global aggregator)
* ReliefWeb    https://api.reliefweb.int/v2/jobs      (UN / NGO / development economics; pre-approved appname)

Keys are read from config or environment variables, never hard-coded.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

from finradar.models import Vacancy
from finradar.sources.base import Source, SourceConfigError, as_list, dig, register
from finradar.textutil import html_to_text, parse_date


def _secret(cfg: dict[str, Any], key: str, env: str) -> str | None:
    return cfg.get(key) or os.environ.get(env)


class _Keyed(Source):
    complete_listing = False

    def require(self, value: str | None, what: str) -> str:
        if not value:
            raise SourceConfigError(f"{self.name}: {what} is not configured")
        return value


@register("superjob")
class SuperJobSource(_Keyed):
    def fetch(self) -> Iterator[Vacancy]:
        key = self.require(_secret(self.cfg, "app_key", "SUPERJOB_API_KEY"), "SUPERJOB_API_KEY")
        seen: set[str] = set()
        for query in self.queries() or [""]:
            for page in range(int(self.cfg.get("max_pages", 5))):
                params: dict[str, Any] = {"keyword": query, "count": 100, "page": page, "order_field": "date"}
                if self.cfg.get("town"):
                    params["town"] = self.cfg["town"]
                if self.cfg.get("catalogues"):
                    params["catalogues"] = self.cfg["catalogues"]
                data = self.http.get_json(
                    "https://api.superjob.ru/2.0/vacancies/", params=params, headers={"X-Api-App-Id": key}
                )
                for it in data.get("objects", []):
                    vid = str(it.get("id"))
                    if vid in seen:
                        continue
                    seen.add(vid)
                    yield self.vacancy(
                        vid, it.get("link", ""), it.get("profession", ""),
                        company=it.get("firm_name"),
                        description="\n".join(filter(None, [it.get("candidat"), it.get("work"), it.get("compensation")])),
                        location=dig(it, "town", "title"),
                        work_format="remote" if dig(it, "place_of_work", "id") == 2 else None,
                        employment=dig(it, "type_of_work", "title"),
                        salary_min=it.get("payment_from") or None,
                        salary_max=it.get("payment_to") or None,
                        salary_currency={"rub": "RUB", "uah": "UAH", "uzs": "UZS"}.get(it.get("currency", "")),
                        published_at=parse_date(it.get("date_published")),
                        tags=[c.get("title") for c in it.get("catalogues", []) if c.get("title")],
                        raw={"seniority_hint": dig(it, "experience", "title")},
                    )
                if not data.get("more"):
                    break


@register("trudvsem")
class TrudvsemSource(_Keyed):
    def fetch(self) -> Iterator[Vacancy]:
        seen: set[str] = set()
        region = self.cfg.get("region_code")  # e.g. 7700000000000 for Moscow
        base = "http://opendata.trudvsem.ru/api/v1/vacancies" + (f"/region/{region}" if region else "")
        for query in self.queries() or [""]:
            for page in range(int(self.cfg.get("max_pages", 3))):
                params = {"text": query, "offset": page, "limit": 100}
                data = self.http.get_json(base, params=params)
                rows = dig(data, "results", "vacancies", default=[])
                for row in rows:
                    it = row.get("vacancy", row)
                    vid = str(it.get("id"))
                    if vid in seen:
                        continue
                    seen.add(vid)
                    addr = dig(it, "addresses", "address", 0, "location")
                    yield self.vacancy(
                        vid, it.get("vac_url", ""), it.get("job-name", ""),
                        company=dig(it, "company", "name"),
                        description=html_to_text(" ".join(filter(None, [it.get("duty"), dig(it, "requirement", "qualification")]))),
                        location=addr or dig(it, "region", "name"),
                        employment=it.get("employment"),
                        salary_min=it.get("salary_min") or None,
                        salary_max=it.get("salary_max") or None,
                        salary_currency="RUB",
                        published_at=parse_date(it.get("creation-date")),
                        tags=[t for t in [dig(it, "category", "specialisation")] if t],
                        raw={"seniority_hint": dig(it, "requirement", "experience")},
                    )
                if len(rows) < 100:
                    break


@register("adzuna")
class AdzunaSource(_Keyed):
    def fetch(self) -> Iterator[Vacancy]:
        app_id = self.require(_secret(self.cfg, "app_id", "ADZUNA_APP_ID"), "ADZUNA_APP_ID")
        app_key = self.require(_secret(self.cfg, "app_key", "ADZUNA_APP_KEY"), "ADZUNA_APP_KEY")
        seen: set[str] = set()
        currency_by_country = {"gb": "GBP", "us": "USD", "de": "EUR", "nl": "EUR", "fr": "EUR", "sg": "SGD",
                               "ca": "CAD", "au": "AUD", "ch": "CHF", "pl": "PLN", "in": "INR", "at": "EUR"}
        for country in as_list(self.cfg.get("countries")) or ["gb"]:
            for query in self.queries() or [""]:
                for page in range(1, int(self.cfg.get("max_pages", 3)) + 1):
                    params: dict[str, Any] = {
                        "app_id": app_id, "app_key": app_key, "results_per_page": 50,
                        "what": query, "max_days_old": self.max_age_days, "sort_by": "date",
                    }
                    if self.cfg.get("category"):
                        params["category"] = self.cfg["category"]
                    data = self.http.get_json(f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}", params=params)
                    results = data.get("results", [])
                    for it in results:
                        vid = f"{country}-{it.get('id')}"
                        if vid in seen:
                            continue
                        seen.add(vid)
                        predicted = str(it.get("salary_is_predicted")) == "1"
                        yield self.vacancy(
                            vid, it.get("redirect_url", ""), html_to_text(it.get("title", "")),
                            company=dig(it, "company", "display_name"),
                            description=html_to_text(it.get("description", "")),
                            location=dig(it, "location", "display_name"),
                            employment=it.get("contract_time"),
                            salary_min=None if predicted else it.get("salary_min"),
                            salary_max=None if predicted else it.get("salary_max"),
                            salary_currency=currency_by_country.get(country),
                            salary_period="year",
                            published_at=parse_date(it.get("created")),
                            tags=[t for t in [dig(it, "category", "label")] if t],
                        )
                    if len(results) < 50:
                        break


@register("usajobs")
class USAJobsSource(_Keyed):
    def fetch(self) -> Iterator[Vacancy]:
        key = self.require(_secret(self.cfg, "api_key", "USAJOBS_API_KEY"), "USAJOBS_API_KEY")
        email = self.require(_secret(self.cfg, "email", "USAJOBS_EMAIL"), "USAJOBS_EMAIL")
        headers = {"Host": "data.usajobs.gov", "User-Agent": email, "Authorization-Key": key}
        seen: set[str] = set()
        searches: list[dict[str, Any]] = [{"Keyword": q} for q in self.queries()]
        searches += [{"JobCategoryCode": code} for code in as_list(self.cfg.get("job_series"))]
        for params in searches:
            data = self.http.get_json(
                "https://data.usajobs.gov/api/search", params={**params, "ResultsPerPage": 250, "DatePosted": self.max_age_days},
                headers=headers,
            )
            for item in dig(data, "SearchResult", "SearchResultItems", default=[]):
                d = item.get("MatchedObjectDescriptor", {})
                vid = d.get("PositionID") or item.get("MatchedObjectId")
                if vid in seen:
                    continue
                seen.add(vid)
                rem = (d.get("PositionRemuneration") or [{}])[0]
                yield self.vacancy(
                    vid, d.get("PositionURI", ""), d.get("PositionTitle", ""),
                    company=" / ".join(filter(None, [d.get("OrganizationName"), d.get("DepartmentName")])),
                    description=dig(d, "UserArea", "Details", "JobSummary", default=""),
                    location=d.get("PositionLocationDisplay"),
                    salary_min=float(rem["MinimumRange"]) if rem.get("MinimumRange") else None,
                    salary_max=float(rem["MaximumRange"]) if rem.get("MaximumRange") else None,
                    salary_currency="USD",
                    salary_period={"PA": "year", "PH": "hour", "PM": "month", "PD": "day"}.get(rem.get("RateIntervalCode")),
                    published_at=parse_date(d.get("PublicationStartDate")),
                    deadline=parse_date(d.get("ApplicationCloseDate")),
                    tags=[c.get("Name") for c in d.get("JobCategory", []) if c.get("Name")],
                    country="США",
                )


@register("reed")
class ReedSource(_Keyed):
    def fetch(self) -> Iterator[Vacancy]:
        key = self.require(_secret(self.cfg, "api_key", "REED_API_KEY"), "REED_API_KEY")
        seen: set[str] = set()
        for query in self.queries() or [""]:
            skip = 0
            while skip < self.max_items:
                params = {"keywords": query, "resultsToTake": 100, "resultsToSkip": skip}
                if self.cfg.get("location"):
                    params["locationName"] = self.cfg["location"]
                data = self.http.get_json("https://www.reed.co.uk/api/1.0/search", params=params, auth=(key, ""))
                results = data.get("results", [])
                for it in results:
                    vid = str(it.get("jobId"))
                    if vid in seen:
                        continue
                    seen.add(vid)
                    yield self.vacancy(
                        vid, it.get("jobUrl", ""), it.get("jobTitle", ""),
                        company=it.get("employerName"),
                        description=html_to_text(it.get("jobDescription", "")),
                        location=it.get("locationName"),
                        salary_min=it.get("minimumSalary"), salary_max=it.get("maximumSalary"),
                        salary_currency=it.get("currency") or "GBP",
                        published_at=parse_date(it.get("date")),
                        deadline=parse_date(it.get("expirationDate")),
                        country="Великобритания",
                    )
                skip += 100
                if len(results) < 100:
                    break


@register("jooble")
class JoobleSource(_Keyed):
    def fetch(self) -> Iterator[Vacancy]:
        key = self.require(_secret(self.cfg, "api_key", "JOOBLE_API_KEY"), "JOOBLE_API_KEY")
        host = self.cfg.get("host", "jooble.org")
        seen: set[str] = set()
        for location in as_list(self.cfg.get("locations")) or [""]:
            for query in self.queries() or [""]:
                for page in range(1, int(self.cfg.get("max_pages", 2)) + 1):
                    data = self.http.post_json(f"https://{host}/api/{key}", {"keywords": query, "location": location, "page": page})
                    jobs = data.get("jobs", [])
                    for it in jobs:
                        vid = str(it.get("id"))
                        if vid in seen:
                            continue
                        seen.add(vid)
                        yield self.vacancy(
                            vid, it.get("link", ""), html_to_text(it.get("title", "")),
                            company=it.get("company") or None,
                            description=html_to_text(it.get("snippet", "")),
                            location=it.get("location"),
                            employment=it.get("type") or None,
                            salary_text=it.get("salary") or None,
                            published_at=parse_date(it.get("updated")),
                            tags=[t for t in [it.get("source")] if t],
                        )
                    if len(jobs) < 20:
                        break


@register("reliefweb")
class ReliefWebSource(_Keyed):
    def fetch(self) -> Iterator[Vacancy]:
        appname = self.require(_secret(self.cfg, "appname", "RELIEFWEB_APPNAME"), "RELIEFWEB_APPNAME (pre-approved)")
        query = " OR ".join(f'"{q}"' for q in self.queries()) or "economist"
        body = {
            "query": {"value": query, "fields": ["title", "body"]},
            "fields": {"include": ["title", "body", "url", "date.created", "date.closing", "source.name",
                                   "country.name", "city.name", "career_categories.name", "experience.name"]},
            "sort": ["date.created:desc"],
            "limit": min(self.max_items, 500),
        }
        data = self.http.post_json(f"https://api.reliefweb.int/v2/jobs?appname={appname}", body)
        for item in data.get("data", []):
            f = item.get("fields", {})
            yield self.vacancy(
                item.get("id"), f.get("url") or item.get("href", ""), f.get("title", ""),
                company=", ".join(s.get("name") for s in f.get("source", []) if s.get("name")) or None,
                description=html_to_text(f.get("body", "")),
                location=", ".join(c.get("name") for c in (f.get("city") or []) + (f.get("country") or []) if c.get("name")) or None,
                published_at=parse_date(dig(f, "date", "created")),
                deadline=parse_date(dig(f, "date", "closing")),
                tags=[c.get("name") for c in f.get("career_categories", []) if c.get("name")],
                raw={"seniority_hint": ", ".join(e.get("name", "") for e in f.get("experience", []))},
            )
