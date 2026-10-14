"""Company career sites via the public JSON feeds of popular ATS platforms.

This is the cleanest way to get global finance employers (banks, funds, trading
firms, fintech): the data is first-party, structured, free and legal to read.

* Greenhouse      https://boards-api.greenhouse.io/v1/boards/<token>/jobs?content=true
* Lever           https://api.lever.co/v0/postings/<company>?mode=json
* Ashby           https://api.ashbyhq.com/posting-api/job-board/<org>?includeCompensation=true
* SmartRecruiters https://api.smartrecruiters.com/v1/companies/<id>/postings
* Workday         POST https://<host>/wday/cxs/<tenant>/<site>/jobs

ATS boards contain every role of a company (engineering, HR, ...); the pipeline's
relevance gate keeps only finance/economics/analytics postings.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from finradar.http import HttpError
from finradar.models import Vacancy
from finradar.sources.base import Source, as_list, dig, register
from finradar.textutil import html_to_text, parse_date

_LEVER_INTERVAL = {"per-year-salary": "year", "per-month-salary": "month", "per-hour-wage": "hour", "per-day-wage": "day"}
_ASHBY_INTERVAL = {"1 YEAR": "year", "1 MONTH": "month", "1 HOUR": "hour", "1 DAY": "day", "1 WEEK": None}


class _MultiCompany(Source):
    """Iterates over ``companies`` and tolerates individual failures."""

    def companies(self) -> list[Any]:
        return as_list(self.cfg.get("companies"))

    def fetch(self) -> Iterator[Vacancy]:
        count = 0
        for company in self.companies():
            try:
                for v in self.fetch_company(company):
                    yield v
                    count += 1
                    if count >= self.max_items:
                        return
            except HttpError as exc:
                self.warn(f"{company}: {exc}")
        # A board that failed means we can't safely close its postings.
        if self.warnings:
            self.partial = True

    def fetch_company(self, company: Any) -> Iterator[Vacancy]:  # pragma: no cover
        raise NotImplementedError

    def title_ok(self, title: str) -> bool:
        """Cheap pre-filter so we don't fetch details for obviously irrelevant roles."""
        include = self.cfg.get("title_include")
        if not include:
            return True
        low = title.lower()
        return any(k.lower() in low for k in include)


@register("greenhouse")
class GreenhouseSource(_MultiCompany):
    def fetch_company(self, token: str) -> Iterator[Vacancy]:
        data = self.http.get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", params={"content": "true"})
        for job in data.get("jobs", []):
            if not self.title_ok(job.get("title", "")):
                continue
            depts = [d.get("name") for d in job.get("departments", []) if d.get("name")]
            yield self.vacancy(
                f"{token}-{job['id']}",
                job.get("absolute_url", ""),
                job.get("title", ""),
                company=job.get("company_name") or self.cfg.get("names", {}).get(token) or token,
                description=html_to_text(job.get("content", "")),
                location=dig(job, "location", "name"),
                published_at=parse_date(job.get("first_published") or job.get("updated_at")),
                tags=depts,
            )


@register("lever")
class LeverSource(_MultiCompany):
    def fetch_company(self, company: str) -> Iterator[Vacancy]:
        host = "api.eu.lever.co" if self.cfg.get("eu") else "api.lever.co"
        data = self.http.get_json(f"https://{host}/v0/postings/{company}", params={"mode": "json"})
        for job in data if isinstance(data, list) else []:
            if not self.title_ok(job.get("text", "")):
                continue
            cats = job.get("categories") or {}
            sal = job.get("salaryRange") or {}
            workplace = job.get("workplaceType")
            yield self.vacancy(
                job["id"],
                job.get("hostedUrl", ""),
                job.get("text", ""),
                company=self.cfg.get("names", {}).get(company) or company,
                description=job.get("descriptionPlain") or html_to_text(job.get("description", "")),
                location=cats.get("location") or ", ".join(cats.get("allLocations") or []),
                work_format={"remote": "remote", "hybrid": "hybrid", "onsite": "office"}.get(workplace or ""),
                employment=cats.get("commitment"),
                salary_min=sal.get("min"),
                salary_max=sal.get("max"),
                salary_currency=sal.get("currency"),
                salary_period=_LEVER_INTERVAL.get(sal.get("interval", "")),
                published_at=parse_date(job.get("createdAt")),
                tags=[t for t in (cats.get("team"), cats.get("department")) if t],
            )


@register("ashby")
class AshbySource(_MultiCompany):
    def fetch_company(self, org: str) -> Iterator[Vacancy]:
        data = self.http.get_json(
            f"https://api.ashbyhq.com/posting-api/job-board/{org}", params={"includeCompensation": "true"}
        )
        for job in data.get("jobs", []):
            if job.get("isListed") is False or not self.title_ok(job.get("title", "")):
                continue
            comp = next(
                (c for c in dig(job, "compensation", "summaryComponents", default=[]) if c.get("compensationType") == "Salary"),
                {},
            )
            yield self.vacancy(
                job.get("id"),
                job.get("jobUrl", ""),
                job.get("title", ""),
                company=self.cfg.get("names", {}).get(org) or org,
                description=job.get("descriptionPlain") or html_to_text(job.get("descriptionHtml", "")),
                location=job.get("location"),
                work_format="remote" if job.get("isRemote") else {"Hybrid": "hybrid", "OnSite": "office", "Remote": "remote"}.get(
                    job.get("workplaceType") or ""
                ),
                employment=job.get("employmentType"),
                salary_min=comp.get("minValue"),
                salary_max=comp.get("maxValue"),
                salary_currency=comp.get("currencyCode"),
                salary_period=_ASHBY_INTERVAL.get(comp.get("interval", "")),
                salary_text=dig(job, "compensation", "compensationTierSummary"),
                published_at=parse_date(job.get("publishedAt")),
                tags=[t for t in (job.get("department"), job.get("team")) if t],
            )


@register("smartrecruiters")
class SmartRecruitersSource(_MultiCompany):
    def fetch_company(self, company: str) -> Iterator[Vacancy]:
        offset, page_size = 0, 100
        while True:
            params: dict[str, Any] = {"limit": page_size, "offset": offset}
            if self.cfg.get("q"):
                params["q"] = self.cfg["q"]
            data = self.http.get_json(f"https://api.smartrecruiters.com/v1/companies/{company}/postings", params=params)
            content = data.get("content", [])
            for job in content:
                if not self.title_ok(job.get("name", "")):
                    continue
                loc = job.get("location") or {}
                yield self.vacancy(
                    job.get("id"),
                    f"https://jobs.smartrecruiters.com/{dig(job, 'company', 'identifier') or company}/{job.get('id')}",
                    job.get("name", ""),
                    company=dig(job, "company", "name") or company,
                    location=loc.get("fullLocation") or ", ".join(filter(None, [loc.get("city"), loc.get("country")])),
                    work_format="remote" if loc.get("remote") else ("hybrid" if loc.get("hybrid") else None),
                    employment=dig(job, "typeOfEmployment", "label"),
                    published_at=parse_date(job.get("releasedDate")),
                    tags=[t for t in (dig(job, "department", "label"), dig(job, "function", "label"), dig(job, "industry", "label")) if t],
                    raw={"seniority_hint": dig(job, "experienceLevel", "label")},
                )
            offset += page_size
            if offset >= int(data.get("totalFound", 0)) or not content or offset >= self.max_items:
                break


@register("workday")
class WorkdaySource(_MultiCompany):
    """``companies`` items: {host: blackrock.wd1.myworkdayjobs.com, tenant: blackrock, site: BlackRock_Professional, name: BlackRock}."""

    def fetch_company(self, c: dict[str, Any]) -> Iterator[Vacancy]:
        host, tenant, site = c["host"], c["tenant"], c["site"]
        endpoint = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
        searches = as_list(c.get("search") or self.cfg.get("search") or [""])
        seen: set[str] = set()
        for text in searches:
            offset = 0
            while offset < int(c.get("max_items", 200)):
                body = {"appliedFacets": c.get("facets", {}), "limit": 20, "offset": offset, "searchText": text}
                data = self.http.post_json(endpoint, body)
                postings = data.get("jobPostings", [])
                for job in postings:
                    path = job.get("externalPath", "")
                    if not path or path in seen or not self.title_ok(job.get("title", "")):
                        continue
                    seen.add(path)
                    yield self.vacancy(
                        f"{tenant}{path}",
                        f"https://{host}/en-US/{site}{path}",
                        job.get("title", ""),
                        company=c.get("name") or tenant,
                        location=job.get("locationsText"),
                        published_at=parse_date(job.get("postedOn")),
                        tags=[b for b in job.get("bulletFields", []) if isinstance(b, str)][:3],
                    )
                offset += 20
                if not postings or offset >= int(data.get("total", 0)):
                    break
