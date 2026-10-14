"""Free public job-board APIs (mostly remote / international roles).

* Remotive     https://remotive.com/api/remote-jobs
* RemoteOK     https://remoteok.com/api                     (attribution required: link back)
* Arbeitnow    https://www.arbeitnow.com/api/job-board-api  (Europe / Germany)
* Himalayas    https://himalayas.app/jobs/api
* Jobicy       https://jobicy.com/api/v2/remote-jobs
* The Muse     https://www.themuse.com/api/public/jobs      (US; finance & data categories)
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from finradar.models import Vacancy
from finradar.sources.base import Source, as_list, dig, register
from finradar.textutil import html_to_text, parse_date


class _Board(Source):
    complete_listing = False
    default_ttl_days = 30


@register("remotive")
class RemotiveSource(_Board):
    def fetch(self) -> Iterator[Vacancy]:
        seen: set[str] = set()
        requests_params: list[dict[str, Any]] = [{"category": c} for c in as_list(self.cfg.get("categories"))]
        requests_params += [{"search": q} for q in self.queries()]
        for params in requests_params or [{}]:
            data = self.http.get_json("https://remotive.com/api/remote-jobs", params={**params, "limit": 300})
            for job in data.get("jobs", []):
                jid = str(job.get("id"))
                if jid in seen:
                    continue
                seen.add(jid)
                yield self.vacancy(
                    jid, job.get("url", ""), job.get("title", ""),
                    company=job.get("company_name"),
                    description=html_to_text(job.get("description", "")),
                    location=job.get("candidate_required_location") or "Remote",
                    work_format="remote",
                    employment=job.get("job_type"),
                    salary_text=job.get("salary") or None,
                    published_at=parse_date(job.get("publication_date")),
                    tags=[job.get("category", "")] + list(job.get("tags") or []),
                )


@register("remoteok")
class RemoteOKSource(_Board):
    def fetch(self) -> Iterator[Vacancy]:
        seen: set[str] = set()
        for tag in as_list(self.cfg.get("tags")) or [None]:
            params = {"tag": tag} if tag else None
            data = self.http.get_json("https://remoteok.com/api", params=params)
            for job in data if isinstance(data, list) else []:
                if not isinstance(job, dict) or "id" not in job or "position" not in job:
                    continue  # first element is a legal notice
                jid = str(job["id"])
                if jid in seen:
                    continue
                seen.add(jid)
                smin, smax = job.get("salary_min") or None, job.get("salary_max") or None
                yield self.vacancy(
                    jid, job.get("url") or f"https://remoteok.com/remote-jobs/{jid}", job.get("position", ""),
                    company=job.get("company"),
                    description=html_to_text(job.get("description", "")),
                    location=job.get("location") or "Remote",
                    work_format="remote",
                    salary_min=smin, salary_max=smax, salary_currency="USD" if (smin or smax) else None,
                    salary_period="year" if (smin or smax) else None,
                    published_at=parse_date(job.get("epoch") or job.get("date")),
                    tags=list(job.get("tags") or []),
                )


@register("arbeitnow")
class ArbeitnowSource(_Board):
    def fetch(self) -> Iterator[Vacancy]:
        url: str | None = "https://www.arbeitnow.com/api/job-board-api"
        pages = 0
        while url and pages < int(self.cfg.get("max_pages", 5)):
            data = self.http.get_json(url)
            for job in data.get("data", []):
                yield self.vacancy(
                    job.get("slug"), job.get("url", ""), job.get("title", ""),
                    company=job.get("company_name"),
                    description=html_to_text(job.get("description", "")),
                    location=job.get("location"),
                    work_format="remote" if job.get("remote") else None,
                    employment=", ".join(job.get("job_types") or []) or None,
                    published_at=parse_date(job.get("created_at")),
                    tags=list(job.get("tags") or []),
                )
            url = dig(data, "links", "next")
            pages += 1


@register("himalayas")
class HimalayasSource(_Board):
    def fetch(self) -> Iterator[Vacancy]:
        seen: set[str] = set()
        queries = self.queries()
        for query in queries or [None]:
            offset = 0
            while offset < self.max_items:
                if query:
                    url, params = "https://himalayas.app/jobs/api/search", {"q": query, "page": offset // 20 + 1}
                else:
                    url, params = "https://himalayas.app/jobs/api", {"limit": 20, "offset": offset}
                data = self.http.get_json(url, params=params)
                jobs = data.get("jobs", [])
                for job in jobs:
                    jid = job.get("guid") or job.get("applicationLink") or job.get("title")
                    if jid in seen:
                        continue
                    seen.add(jid)
                    yield self.vacancy(
                        jid, job.get("applicationLink") or job.get("guid", ""), job.get("title", ""),
                        company=job.get("companyName"),
                        description=html_to_text(job.get("description") or job.get("excerpt") or ""),
                        location=", ".join(job.get("locationRestrictions") or []) or "Remote",
                        work_format="remote",
                        employment=job.get("employmentType"),
                        salary_min=job.get("minSalary"), salary_max=job.get("maxSalary"),
                        salary_currency=job.get("currency") or ("USD" if job.get("minSalary") else None),
                        salary_period="year" if job.get("minSalary") or job.get("maxSalary") else None,
                        published_at=parse_date(job.get("pubDate")),
                        deadline=parse_date(job.get("expiryDate")),
                        tags=list(job.get("categories") or []) + list(job.get("parentCategories") or []),
                        raw={"seniority_hint": ", ".join(job.get("seniority") or []) or None},
                    )
                offset += 20
                if len(jobs) < 20:
                    break


@register("jobicy")
class JobicySource(_Board):
    def fetch(self) -> Iterator[Vacancy]:
        seen: set[str] = set()
        variants: list[dict[str, Any]] = [{"industry": i} for i in as_list(self.cfg.get("industries"))]
        variants += [{"tag": t} for t in self.queries()]
        for params in variants or [{}]:
            data = self.http.get_json("https://jobicy.com/api/v2/remote-jobs", params={"count": 100, **params})
            for job in data.get("jobs", []):
                jid = str(job.get("id"))
                if jid in seen:
                    continue
                seen.add(jid)
                smin, smax = job.get("annualSalaryMin"), job.get("annualSalaryMax")
                yield self.vacancy(
                    jid, job.get("url", ""), html_to_text(job.get("jobTitle", "")),
                    company=job.get("companyName"),
                    description=html_to_text(job.get("jobDescription") or job.get("jobExcerpt") or ""),
                    location=job.get("jobGeo") or "Remote",
                    work_format="remote",
                    employment=", ".join(as_list(job.get("jobType"))) or None,
                    salary_min=smin, salary_max=smax, salary_currency=job.get("salaryCurrency"),
                    salary_period="year" if (smin or smax) else None,
                    published_at=parse_date(job.get("pubDate")),
                    tags=as_list(job.get("jobIndustry")),
                    raw={"seniority_hint": job.get("jobLevel")},
                )


@register("themuse")
class TheMuseSource(_Board):
    def fetch(self) -> Iterator[Vacancy]:
        categories = as_list(self.cfg.get("categories")) or ["Accounting and Finance", "Data and Analytics"]
        params: list[tuple[str, Any]] = [("category", c) for c in categories]
        params += [("location", loc) for loc in as_list(self.cfg.get("locations"))]
        params += [("level", lvl) for lvl in as_list(self.cfg.get("levels"))]
        api_key = self.cfg.get("api_key")
        for page in range(int(self.cfg.get("max_pages", 5))):
            page_params = [*params, ("page", page)] + ([("api_key", api_key)] if api_key else [])
            data = self.http.get_json("https://www.themuse.com/api/public/jobs", params=page_params)
            for job in data.get("results", []):
                locs = [loc.get("name") for loc in job.get("locations", []) if loc.get("name")]
                yield self.vacancy(
                    job.get("id"), dig(job, "refs", "landing_page", default=""), job.get("name", ""),
                    company=dig(job, "company", "name"),
                    description=html_to_text(job.get("contents", "")),
                    location="; ".join(locs) or None,
                    work_format="remote" if any("remote" in (loc or "").lower() for loc in locs) else None,
                    published_at=parse_date(job.get("publication_date")),
                    tags=[c.get("name") for c in job.get("categories", []) if c.get("name")],
                    raw={"seniority_hint": ", ".join(lv.get("short_name", "") for lv in job.get("levels", []))},
                )
            if page + 1 >= int(data.get("page_count", 0)):
                break
