"""Derive normalized fields for a freshly collected :class:`Vacancy`."""

from __future__ import annotations

from finradar import taxonomy
from finradar.models import Vacancy
from finradar.salary import Salary, find_salary_in_text, infer_period, normalize, parse_salary
from finradar.textutil import clean_ws, detect_language, truncate

MAX_DESCRIPTION = 20_000


def enrich(v: Vacancy, rates_rub: dict[str, float]) -> Vacancy:
    v.title = clean_ws(v.title).replace("\n", " ")[:300]
    v.company = clean_ws(v.company).replace("\n", " ")[:200] or None if v.company else None
    v.description = truncate(clean_ws(v.description), MAX_DESCRIPTION)
    v.language = v.language or detect_language(f"{v.title}\n{v.description}")

    _enrich_salary(v, rates_rub)

    cls = taxonomy.classify_domains(v.title, v.description, v.tags)
    v.domains, v.primary_domain, v.relevance = cls.domains, cls.primary_domain, cls.relevance

    if v.kind == "vacancy":
        v.kind = taxonomy.classify_kind(v.title, v.description, v.employment, v.tags)
    if v.kind == "internship" and not v.seniority:
        v.seniority = "intern"
    if not v.seniority:
        v.seniority = taxonomy.classify_seniority(
            v.title, v.description, hint=v.raw.get("seniority_hint"), domains=v.domains
        )
    if not v.work_format:
        v.work_format = taxonomy.classify_work_format(v.title, v.location, v.description[:2000])

    extracted = taxonomy.extract_skills(v.title, v.description, extra=v.tags)
    v.skills = list(dict.fromkeys([*v.skills, *extracted]))

    if not (v.city and v.country):
        city, country = taxonomy.resolve_location(v.location, v.title, v.description[:400])
        v.city = v.city or city
        v.country = v.country or country
    if v.work_format == "remote" and not v.city and not v.location:
        v.location = "Remote"
    return v


def _enrich_salary(v: Vacancy, rates_rub: dict[str, float]) -> None:
    sal: Salary | None = None
    if v.salary_min or v.salary_max:
        sal = Salary(v.salary_min, v.salary_max, v.salary_currency, v.salary_period, v.salary_gross)
        if sal.currency is None and v.salary_text:
            parsed = parse_salary(v.salary_text)
            sal.currency = parsed.currency if parsed else None
        if sal.period is None:
            sal.period = infer_period(sal)
    elif v.salary_text:
        sal = parse_salary(v.salary_text, default_currency=v.salary_currency)
    elif v.description:
        sal, line = find_salary_in_text(v.description, default_currency=v.salary_currency)
        if sal and line:
            v.salary_text = line[:200]
    if not sal:
        return
    v.salary_min, v.salary_max = sal.min, sal.max
    v.salary_currency, v.salary_period = sal.currency, sal.period
    if v.salary_gross is None:
        v.salary_gross = sal.gross
        sal.gross = v.salary_gross
    v.salary_month_rub, v.salary_year_usd = normalize(sal, rates_rub)
