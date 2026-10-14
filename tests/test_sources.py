"""Connector tests against fixtures shaped like each source's real responses."""

from __future__ import annotations

import json
from email.message import EmailMessage

import pytest

from finradar.http import BlockedError
from finradar.sources import REGISTRY


def make(type_name, fake, **cfg):
    cfg.setdefault("name", type_name)
    cfg.setdefault("type", type_name)
    return REGISTRY[type_name](cfg["name"], cfg, fake)


# --------------------------------------------------------------------------- hh.ru

HH_API = {
    "items": [{
        "id": "101", "name": "Финансовый аналитик (FP&A)", "alternate_url": "https://hh.ru/vacancy/101",
        "employer": {"id": "1", "name": "Сбер"}, "area": {"name": "Москва"},
        "salary": {"from": 200000, "to": 280000, "currency": "RUR", "gross": False},
        "published_at": "2026-10-10T12:00:00+0300",
        "snippet": {"requirement": "Опыт в <highlighttext>FP&A</highlighttext> от 3 лет", "responsibility": "Бюджетирование"},
        "schedule": {"id": "fullDay"}, "work_format": [{"id": "HYBRID"}],
        "experience": {"id": "between3And6"}, "employment": {"id": "full"},
        "professional_roles": [{"id": "134", "name": "Финансовый аналитик, инвестиционный аналитик"}],
    }],
    "pages": 1,
}

HH_HTML = """
<html><body>
<div data-qa="vacancy-serp__vacancy vacancy-serp__vacancy_standard_plus">
  <a data-qa="serp-item__title" href="https://hh.ru/vacancy/555?query=x"><span data-qa="serp-item__title-text">Аналитик M&amp;A</span></a>
  <span data-qa="vacancy-serp__vacancy-compensation">от 250 000 до 350 000 ₽ за месяц, на руки</span>
  <a data-qa="vacancy-serp__vacancy-employer"><span data-qa="vacancy-serp__vacancy-employer-text">ВТБ Капитал</span></a>
  <span data-qa="vacancy-serp__vacancy-address">Москва</span>
  <span data-qa="vacancy-serp__vacancy-work-experience-between1And3">Опыт 1–3 года</span>
  <div data-qa="vacancy-serp__vacancy_snippet_requirement">Финансовое моделирование, DCF</div>
  <span>Можно удалённо</span>
</div>
<div data-qa="vacancy-serp__vacancy">
  <a data-qa="serp-item__title" href="/vacancy/556"><span data-qa="serp-item__title-text">Экономист</span></a>
  <span>120 000 – 150 000 ₽</span>
</div>
</body></html>
"""


def test_hh_api_mode(fake_http):
    fake = fake_http([(r"api\.hh\.ru/vacancies", HH_API)])
    src = make("hh", fake, access_token="t0ken", queries=["FP&A"], max_pages=2)
    [v] = list(src.fetch())
    assert src.mode == "api"
    assert (v.external_id, v.company, v.location) == ("101", "Сбер", "Москва")
    assert (v.salary_min, v.salary_max, v.salary_currency, v.salary_gross) == (200000, 280000, "RUB", False)
    assert v.work_format == "hybrid" and v.raw["seniority_hint"] == "between3And6"
    assert "FP&A" in v.description and "<" not in v.description


def test_hh_html_mode(fake_http):
    fake = fake_http([(r"hh\.ru/search/vacancy", HH_HTML)])
    src = make("hh", fake, queries=["аналитик"], max_pages=1)
    items = list(src.fetch())
    assert src.mode == "html"
    assert [v.external_id for v in items] == ["555", "556"]
    a, b = items
    assert a.title == "Аналитик M&A" and a.company == "ВТБ Капитал" and a.location == "Москва"
    assert a.salary_text.startswith("от 250 000") and a.work_format == "remote"
    assert a.raw["seniority_hint"] == "between1And3"
    assert b.salary_text == "120 000 – 150 000 ₽"


def test_hh_html_captcha_is_reported(fake_http):
    fake = fake_http([(r"hh\.ru/search/vacancy", "<html><body>Пройдите captcha</body></html>")])
    src = make("hh", fake, queries=["x"], max_pages=1)
    with pytest.raises(BlockedError):
        list(src.fetch())


# --------------------------------------------------------------------------- Habr Career / GetMatch

HABR_JSON = {
    "list": [{
        "id": 1000150001, "href": "/vacancies/1000150001", "title": "Продуктовый аналитик",
        "company": {"title": "Т-Банк"}, "remoteWork": True,
        "salary": {"from": 250000, "to": None, "currency": "rur", "formatted": "от 250 000 ₽"},
        "locations": [{"title": "Москва"}], "skills": [{"title": "SQL"}, {"title": "Python"}],
        "divisions": [{"title": "Аналитика"}], "publishedDate": {"date": "2026-10-12T10:00:00+03:00"},
        "salaryQualification": {"title": "Middle"},
    }],
    "meta": {"totalPages": 1},
}

HABR_HTML = """
<div class="vacancy-card">
  <div class="vacancy-card__date"><time datetime="2026-10-11T09:00:00+03:00">11 октября</time></div>
  <a class="vacancy-card__title-link" href="/vacancies/1000150002">BI-аналитик</a>
  <div class="vacancy-card__company-title"><a>Альфа-Банк</a></div>
  <div class="vacancy-card__meta">Москва • Можно удаленно</div>
  <div class="vacancy-card__salary"><div class="basic-salary">от 200 000 до 300 000 ₽</div></div>
  <div class="vacancy-card__skills"><a>Power BI</a><a>SQL</a></div>
</div>
"""


def test_habr_json(fake_http):
    fake = fake_http([(r"api/frontend/vacancies", HABR_JSON)])
    [v] = list(make("habr", fake, queries=["аналитик"]).fetch())
    assert v.url == "https://career.habr.com/vacancies/1000150001"
    assert (v.company, v.salary_min, v.salary_currency, v.work_format) == ("Т-Банк", 250000, "RUB", "remote")
    assert "SQL" in v.tags and v.raw["seniority_hint"] == "middle"


def test_habr_html_fallback(fake_http):
    fake = fake_http([(r"api/frontend/vacancies", 500), (r"career\.habr\.com/vacancies", HABR_HTML)])
    src = make("habr", fake, queries=["bi"], max_pages=1)
    [v] = list(src.fetch())
    assert (v.external_id, v.title, v.company) == ("1000150002", "BI-аналитик", "Альфа-Банк")
    assert v.salary_text == "от 200 000 до 300 000 ₽" and v.tags == ["Power BI", "SQL"]
    assert src.warnings


GETMATCH_JSON = {"offers": [{
    "id": 7001, "position": "Финансовый аналитик", "url": "/vacancies/7001-finansovyy-analitik",
    "company": {"name": "Ozon Fintech"}, "salary_display_from": 230000, "salary_display_to": 320000,
    "salary_currency": "₽", "salary_hidden": False, "remote_options": "hybrid",
    "display_locations": [{"city": "Москва"}], "stack": ["SQL", "Excel"], "seniority": "middle",
    "published_at": "2026-10-13T08:00:00Z", "offer_description": "<p>Модели unit-экономики</p>",
}]}

GETMATCH_HTML = """
<div class="list">
  <div class="b-vacancy-card"><a href="/vacancies/7002-analitik">Аналитик данных</a>
     <div class="b-vacancy-card-subtitle__company">Яндекс</div><div class="salary">300 000 – 400 000 ₽</div></div>
  <div class="b-vacancy-card"><a href="/vacancies/7003-bi">BI-разработчик</a><div class="company">Авито</div></div>
</div>
"""


def test_getmatch_json(fake_http):
    fake = fake_http([(r"getmatch\.ru/api/offers", GETMATCH_JSON)])
    [v] = list(make("getmatch", fake, queries=["аналитик"], max_pages=1).fetch())
    assert v.url == "https://getmatch.ru/vacancies/7001-finansovyy-analitik"
    assert (v.company, v.salary_min, v.salary_max, v.salary_currency) == ("Ozon Fintech", 230000, 320000, "RUB")
    assert v.work_format == "hybrid" and v.location == "Москва" and v.tags == ["SQL", "Excel"]


def test_getmatch_html_fallback(fake_http):
    fake = fake_http([(r"getmatch\.ru/api/offers", 404), (r"getmatch\.ru/vacancies", GETMATCH_HTML)])
    items = list(make("getmatch", fake, max_pages=1).fetch())
    assert [(v.external_id, v.company) for v in items] == [("7002", "Яндекс"), ("7003", "Авито")]
    assert "300 000" in items[0].salary_text


# --------------------------------------------------------------------------- Telegram

def _tg_post(pid: int, html_text: str, dt: str = "2026-10-13T09:00:00+00:00") -> str:
    return f"""
<div class="tgme_widget_message_wrap"><div class="tgme_widget_message" data-post="Perforum_jobs/{pid}">
  <div class="tgme_widget_message_text js-message_text">{html_text}</div>
  <div class="tgme_widget_message_footer"><a class="tgme_widget_message_date" href="https://t.me/Perforum_jobs/{pid}">
  <time datetime="{dt}">09:00</time></a></div></div></div>"""


TG_PAGE = "<html><body>" + "".join([
    _tg_post(901, "#вакансия #middle<br/>Вакансия: Аналитик M&amp;A<br/>Компания: Газпромбанк<br/>"
                  "Локация: Москва<br/>Формат: гибрид<br/>ЗП: 250-350к ₽ на руки<br/>Обязанности: модели, DCF, due diligence<br/>"
                  "<a href=\"https://perforum.io/jobs/ma-analyst\">Откликнуться</a>"),
    _tg_post(902, "Подборка вакансий недели:<br/>"
                  "1. <a href=\"https://perforum.io/jobs/a\">FP&amp;A Manager — X5</a><br/>"
                  "2. <a href=\"https://perforum.io/jobs/b\">Credit Analyst — Райффайзенбанк</a><br/>"
                  "3. <a href=\"https://perforum.io/jobs/c\">Economist — ЦМАКП</a><br/>#вакансии"),
    _tg_post(903, "#резюме Ищу работу финансовым аналитиком, опыт 3 года, Москва"),
    _tg_post(904, "Анонс вебинара про карьеру"),
]) + "</body></html>"


def test_telegram_single_digest_and_noise(fake_http):
    fake = fake_http([(r"t\.me/s/Perforum_jobs", TG_PAGE)])
    src = make("telegram", fake, channels=["@Perforum_jobs"], pages=1, max_age_days=10_000)
    items = list(src.fetch())
    single = items[0]
    assert single.external_id == "Perforum_jobs/901" and single.url == "https://t.me/Perforum_jobs/901"
    assert (single.title, single.company) == ("Аналитик M&A", "Газпромбанк")
    assert single.salary_text.startswith("250-350к") and "Москва" in single.location
    assert single.raw["apply_url"] == "https://perforum.io/jobs/ma-analyst"
    digest = items[1:]
    assert [v.title for v in digest] == ["FP&A Manager — X5", "Credit Analyst — Райффайзенбанк", "Economist — ЦМАКП"]
    assert digest[0].url == "https://perforum.io/jobs/a" and digest[0].external_id == "Perforum_jobs/902-1"
    assert len(items) == 4  # resume post and webinar post are skipped


def test_telegram_title_at_company():
    from finradar.sources.telegram import TelegramSource

    title, company = TelegramSource._title_company("🔥 Senior Credit Analyst в Альфа-Банк\nОпыт от 3 лет")
    assert (title, company) == ("Senior Credit Analyst", "Альфа-Банк")


# --------------------------------------------------------------------------- ATS

def test_greenhouse(fake_http):
    payload = {"jobs": [{"id": 42, "title": "Quantitative Researcher", "absolute_url": "https://boards.greenhouse.io/imc/jobs/42",
                         "location": {"name": "Amsterdam"}, "updated_at": "2026-10-01T00:00:00Z",
                         "content": "&lt;p&gt;Build &lt;b&gt;models&lt;/b&gt;&lt;/p&gt;", "departments": [{"name": "Research"}]}]}
    fake = fake_http([(r"boards-api\.greenhouse\.io/v1/boards/imc/jobs", payload), (r"boards/nope", 404)])
    src = make("greenhouse", fake, companies=["imc", "nope"], names={"imc": "IMC Trading"})
    [v] = list(src.fetch())
    assert (v.external_id, v.company, v.location, v.description) == ("imc-42", "IMC Trading", "Amsterdam", "Build models")
    assert src.partial and src.warnings  # the failed board blocks closing


def test_lever_and_ashby(fake_http):
    lever = [{"id": "abc", "text": "Treasury Analyst", "hostedUrl": "https://jobs.lever.co/x/abc", "createdAt": 1760000000000,
              "categories": {"location": "London", "commitment": "Full-time", "team": "Finance"}, "descriptionPlain": "Liquidity",
              "workplaceType": "hybrid", "salaryRange": {"min": 60000, "max": 75000, "currency": "GBP", "interval": "per-year-salary"}}]
    ashby = {"jobs": [{"id": "j1", "title": "Strategic Finance Manager", "jobUrl": "https://jobs.ashbyhq.com/ramp/j1",
                       "location": "New York", "isRemote": False, "workplaceType": "Hybrid", "publishedAt": "2026-10-02T00:00:00Z",
                       "descriptionPlain": "FP&A", "isListed": True,
                       "compensation": {"compensationTierSummary": "$150K – $190K",
                                        "summaryComponents": [{"compensationType": "Salary", "interval": "1 YEAR",
                                                               "currencyCode": "USD", "minValue": 150000, "maxValue": 190000}]}}]}
    fake = fake_http([(r"api\.lever\.co/v0/postings/x", lever), (r"posting-api/job-board/ramp", ashby)])
    [lv] = list(make("lever", fake, companies=["x"]).fetch())
    assert (lv.salary_min, lv.salary_currency, lv.salary_period, lv.work_format) == (60000, "GBP", "year", "hybrid")
    [av] = list(make("ashby", fake, companies=["ramp"], names={"ramp": "Ramp"}).fetch())
    assert (av.company, av.salary_max, av.salary_period, av.work_format) == ("Ramp", 190000, "year", "hybrid")


def test_smartrecruiters_and_workday(fake_http):
    sr = {"totalFound": 1, "content": [{"id": "744", "name": "Financial Analyst", "company": {"name": "Visa", "identifier": "Visa"},
                                         "releasedDate": "2026-10-05T10:00:00.000Z",
                                         "location": {"city": "Dubai", "country": "ae", "remote": False, "fullLocation": "Dubai, UAE"},
                                         "experienceLevel": {"label": "Mid-Senior Level"}}]}
    wd = {"total": 1, "jobPostings": [{"title": "Analyst, Portfolio Management", "externalPath": "/job/NY/Analyst_R123",
                                       "locationsText": "New York, NY", "postedOn": "Posted 3 Days Ago", "bulletFields": ["R123"]}]}
    fake = fake_http([(r"smartrecruiters\.com/v1/companies/Visa/postings", sr), (r"POST https://blackrock\.wd1", wd)])
    [s] = list(make("smartrecruiters", fake, companies=["Visa"]).fetch())
    assert s.url == "https://jobs.smartrecruiters.com/Visa/744" and s.location == "Dubai, UAE"
    src = make("workday", fake, search=["analyst"], companies=[{"name": "BlackRock", "host": "blackrock.wd1.myworkdayjobs.com",
                                                                 "tenant": "blackrock", "site": "BlackRock_Professional"}])
    [w] = list(src.fetch())
    assert w.url == "https://blackrock.wd1.myworkdayjobs.com/en-US/BlackRock_Professional/job/NY/Analyst_R123"
    assert w.company == "BlackRock" and w.published_at is not None


# --------------------------------------------------------------------------- public boards

def test_public_boards(fake_http):
    fake = fake_http([
        (r"remotive\.com/api", {"jobs": [{"id": 1, "url": "https://remotive.com/1", "title": "Financial Analyst", "company_name": "Acme",
                                          "category": "Finance", "tags": ["excel"], "publication_date": "2026-10-10T00:00:00",
                                          "candidate_required_location": "Europe", "salary": "$70k - $90k", "description": "<p>FP&A</p>"}]}),
        (r"remoteok\.com/api", [{"legal": "notice"}, {"id": "2", "position": "Crypto Analyst", "company": "Chain", "epoch": 1760000000,
                                                      "salary_min": 80000, "salary_max": 120000, "tags": ["crypto"], "url": "https://remoteok.com/2"}]),
        (r"jobicy\.com/api", {"jobs": [{"id": 3, "url": "https://jobicy.com/3", "jobTitle": "Accountant", "companyName": "Ledger",
                                        "jobIndustry": ["Accounting &amp; Finance"], "jobGeo": "USA", "pubDate": "2026-10-09 10:00:00",
                                        "annualSalaryMin": 60000, "annualSalaryMax": 70000, "salaryCurrency": "USD"}]}),
        (r"themuse\.com/api", {"page": 0, "page_count": 1, "results": [{"id": 4, "name": "Economist", "contents": "<p>Macro</p>",
                                                                        "publication_date": "2026-10-08T00:00:00Z", "locations": [{"name": "Flexible / Remote"}],
                                                                        "levels": [{"short_name": "mid"}], "categories": [{"name": "Data and Analytics"}],
                                                                        "company": {"name": "Fed"}, "refs": {"landing_page": "https://themuse.com/4"}}]}),
        (r"himalayas\.app/jobs/api/search", {"jobs": [{"guid": "h5", "title": "FP&A Analyst", "companyName": "Hima", "applicationLink": "https://h/5",
                                                       "minSalary": 90000, "maxSalary": 110000, "currency": "USD", "pubDate": 1760000000,
                                                       "locationRestrictions": ["Canada"], "seniority": ["Mid-level"]}]}),
    ])
    r = list(make("remotive", fake, queries=["finance"]).fetch())
    assert r[0].salary_text == "$70k - $90k" and r[0].work_format == "remote"
    ok = list(make("remoteok", fake).fetch())
    assert len(ok) == 1 and ok[0].salary_currency == "USD"
    jb = list(make("jobicy", fake, industries=["accounting-finance"]).fetch())
    assert jb[0].tags == ["Accounting &amp; Finance"] and jb[0].salary_period == "year"
    mu = list(make("themuse", fake).fetch())
    assert mu[0].work_format == "remote" and mu[0].raw["seniority_hint"] == "mid"
    hi = list(make("himalayas", fake, queries=["fp&a"]).fetch())
    assert hi[0].salary_max == 110000 and hi[0].location == "Canada"


# --------------------------------------------------------------------------- keyed APIs

def test_keyed_apis(fake_http, monkeypatch):
    monkeypatch.setenv("SUPERJOB_API_KEY", "k")
    monkeypatch.setenv("ADZUNA_APP_ID", "i")
    monkeypatch.setenv("ADZUNA_APP_KEY", "k")
    fake = fake_http([
        (r"api\.superjob\.ru", {"objects": [{"id": 9, "profession": "Экономист", "firm_name": "Росатом", "town": {"title": "Москва"},
                                              "payment_from": 120000, "payment_to": 0, "currency": "rub", "date_published": 1760000000,
                                              "link": "https://superjob.ru/9", "experience": {"title": "От 1 года"}}], "more": False}),
        (r"opendata\.trudvsem\.ru", {"results": {"vacancies": [{"vacancy": {"id": "t1", "job-name": "Ведущий экономист", "vac_url": "https://trudvsem.ru/t1",
                                                                            "company": {"name": "ФНС"}, "salary_min": 90000, "salary_max": 110000,
                                                                            "creation-date": "2026-10-01", "region": {"name": "Москва"}}}]}}),
        (r"api\.adzuna\.com/v1/api/jobs/gb/search/1", {"results": [{"id": "77", "title": "<strong>FP&amp;A</strong> Analyst", "redirect_url": "https://adzuna/77",
                                                                    "company": {"display_name": "Barclays"}, "location": {"display_name": "London"},
                                                                    "salary_min": 55000, "salary_max": 65000, "salary_is_predicted": "0",
                                                                    "created": "2026-10-12T00:00:00Z", "description": "Budgeting"}]}),
    ])
    [sj] = list(make("superjob", fake, queries=["экономист"], max_pages=1).fetch())
    assert (sj.company, sj.salary_min, sj.salary_max, sj.salary_currency) == ("Росатом", 120000, None, "RUB")
    [tv] = list(make("trudvsem", fake, queries=["экономист"], max_pages=1).fetch())
    assert tv.company == "ФНС" and tv.salary_currency == "RUB"
    [az] = list(make("adzuna", fake, countries=["gb"], queries=["fp&a"], max_pages=1).fetch())
    assert (az.title, az.salary_currency, az.salary_period) == ("FP&A Analyst", "GBP", "year")


def test_keyed_api_without_key_fails_cleanly(fake_http, monkeypatch):
    monkeypatch.delenv("REED_API_KEY", raising=False)
    from finradar.sources import SourceConfigError

    with pytest.raises(SourceConfigError, match="REED_API_KEY"):
        list(make("reed", fake_http()).fetch())


# --------------------------------------------------------------------------- generic connectors

RSS = b"""<?xml version="1.0"?><rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>
<item><title>Acme Capital: Investment Analyst</title><link>https://acme.com/jobs/1</link><guid>acme-1</guid>
<pubDate>Mon, 12 Oct 2026 10:00:00 GMT</pubDate><description>&lt;p&gt;LBO models&lt;/p&gt;</description><category>Finance</category></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Economist</title><link href="https://econ.org/j/2"/><id>tag:econ,2</id><updated>2026-10-11T00:00:00Z</updated>
<summary>Research on labour markets</summary><author><name>Think Tank</name></author></entry></feed>"""


def test_rss_and_atom(fake_http):
    fake = fake_http([(r"acme\.com/feed", RSS), (r"econ\.org/feed", ATOM)])
    items = list(make("rss", fake, feeds=["https://acme.com/feed", "https://econ.org/feed"], max_age_days=10_000,
                      title_regex=r"^(?P<company>[^:]+):\s*(?P<title>.+)$").fetch())
    assert [(v.title, v.company) for v in items] == [("Investment Analyst", "Acme Capital"), ("Economist", "Think Tank")]
    assert items[0].description == "LBO models" and items[1].url == "https://econ.org/j/2"


LISTING = """<html><body><ul>
<li class="job-item"><a href="/jobs/ma-associate">M&amp;A Associate</a><span class="company">Альфа Капитал</span>
<span class="salary">от 350 000 ₽</span></li>
<li class="job-item"><a href="/jobs/economist-cb">Экономист</a></li>
<li><a href="/about">О нас</a></li></ul></body></html>"""

DETAIL_JSONLD = """<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@type":"JobPosting","title":"M&A Associate","datePosted":"2026-10-12",
 "hiringOrganization":{"@type":"Organization","name":"Альфа Капитал"},
 "jobLocation":{"@type":"Place","address":{"addressLocality":"Москва","addressCountry":"RU"}},
 "baseSalary":{"@type":"MonetaryAmount","currency":"RUB","value":{"@type":"QuantitativeValue","minValue":350000,"maxValue":450000,"unitText":"MONTH"}},
 "employmentType":"FULL_TIME","description":"<p>Сделки M&amp;A, финансовое моделирование</p>"}
</script></head><body><h1>M&A Associate</h1></body></html>"""

DETAIL_PLAIN = """<html><head><meta property="og:title" content="Экономист в аналитический центр"></head>
<body><main><h1>Экономист</h1><p>Макроэкономические прогнозы, эконометрика.</p></main></body></html>"""


def test_jsonld_crawler(fake_http):
    fake = fake_http([
        (r"site\.ru/jobs\?page=1", LISTING), (r"site\.ru/jobs\?page=2", LISTING),
        (r"site\.ru/jobs/ma-associate", DETAIL_JSONLD), (r"site\.ru/jobs/economist-cb", DETAIL_PLAIN),
    ])
    src = make("jsonld_crawler", fake, start_urls=["https://site.ru/jobs"], link_pattern=r"/jobs/[^/?#]+/?$",
               pagination={"param": "page", "start": 1, "max_pages": 3}, max_age_days=10_000)
    items = list(src.fetch())
    a, b = items
    assert (a.title, a.company, a.salary_min, a.salary_max, a.salary_period) == ("M&A Associate", "Альфа Капитал", 350000, 450000, "month")
    assert a.location.startswith("Москва") and a.employment == "full" and "финансовое моделирование" in a.description
    assert b.title == "Экономист" and "эконометрика" in b.description
    # page 2 returned the same links -> pagination stopped, page 3 never requested
    assert not any("page=3" in str(c[2]) for c in fake.calls)


def test_html_list(fake_http):
    fake = fake_http([(r"board\.io/v\?p=1", LISTING), (r"board\.io/v\?p=2", "<html></html>")])
    src = make("html_list", fake, url_template="https://board.io/v?p={page}", pages=2, item="li.job-item",
               fields={"title": "a", "link": "a@href", "company": ".company", "salary": ".salary"})
    items = list(src.fetch())
    assert [(v.title, v.company, v.salary_text) for v in items] == [
        ("M&A Associate", "Альфа Капитал", "от 350 000 ₽"), ("Экономист", None, None)]
    assert items[0].url == "https://board.io/jobs/ma-associate"


def test_email_alert_parsing(fake_http):
    msg = EmailMessage()
    msg["Subject"] = "New jobs for “financial analyst”"
    msg["Date"] = "Tue, 13 Oct 2026 08:00:00 +0000"
    msg.set_content("plain")
    msg.add_alternative("""<table>
      <tr><td><a href="https://www.linkedin.com/comm/jobs/view/4001234567/?trackingId=x">Financial Analyst</a><br>Goldman Sachs<br>London, England</td></tr>
      <tr><td><a href="https://www.linkedin.com/comm/jobs/view/4007654321/">FP&amp;A Associate</a><br>Revolut<br>Remote</td></tr>
      <tr><td><a href="https://www.linkedin.com/comm/jobs/view/4007654321/">View job</a></td></tr>
    </table>""", subtype="html")
    src = make("email_alerts", fake_http())
    items = list(src.parse_message(msg.as_bytes()))
    assert [(v.title, v.company, v.location) for v in items] == [
        ("Financial Analyst", "Goldman Sachs", "London, England"), ("FP&A Associate", "Revolut", "Remote")]
    assert items[0].url == "https://www.linkedin.com/jobs/view/4001234567"
    assert items[0].published_at is not None


def test_registry_complete():
    expected = {"hh", "habr", "getmatch", "telegram", "greenhouse", "lever", "ashby", "smartrecruiters", "workday",
                "remotive", "remoteok", "arbeitnow", "himalayas", "jobicy", "themuse", "superjob", "trudvsem", "adzuna",
                "usajobs", "reed", "jooble", "reliefweb", "rss", "jsonld_crawler", "html_list", "email_alerts"}
    assert expected <= set(REGISTRY)
    json.dumps(sorted(REGISTRY))
