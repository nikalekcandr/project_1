"""End-to-end: config -> fetch (fake network) -> dedup -> scoring -> closing -> analytics/report/digest/CLI."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from finradar import analytics, cli, digest, pipeline
from finradar.config import load_config
from finradar.storage import Store

from .conftest import FakeHttp

CBR = """<?xml version="1.0" encoding="windows-1251"?><ValCurs Date="14.10.2026">
<Valute><NumCode>840</NumCode><CharCode>USD</CharCode><Nominal>1</Nominal><Value>80,0000</Value></Valute>
<Valute><NumCode>978</NumCode><CharCode>EUR</CharCode><Nominal>1</Nominal><Value>90,0000</Value></Valute>
<Valute><NumCode>398</NumCode><CharCode>KZT</CharCode><Nominal>100</Nominal><Value>16,0000</Value></Valute>
</ValCurs>""".encode("cp1251")


def hh_payload(salary_to: int) -> dict:
    return {"pages": 1, "items": [
        {"id": "101", "name": "Финансовый аналитик (FP&A)", "alternate_url": "https://hh.ru/vacancy/101",
         "employer": {"name": "ПАО Сбербанк"}, "area": {"name": "Москва"},
         "salary": {"from": 220000, "to": salary_to, "currency": "RUR", "gross": False},
         "published_at": datetime.now(timezone.utc).isoformat(),
         "snippet": {"requirement": "Финансовое моделирование, Excel, SQL, Power BI. Опыт от 3 лет.",
                     "responsibility": "Бюджетирование и управленческая отчетность"},
         "experience": {"id": "between3And6"}},
        {"id": "102", "name": "Водитель-экспедитор", "alternate_url": "https://hh.ru/vacancy/102",
         "employer": {"name": "Логистика"}, "area": {"name": "Москва"}, "published_at": datetime.now(timezone.utc).isoformat()},
    ]}


def tg_page() -> str:
    now = datetime.now(timezone.utc).isoformat()
    text = ("#вакансия<br/>Вакансия: Финансовый аналитик (FP&amp;A)<br/>Компания: Сбербанк<br/>Город: Москва<br/>"
            "ЗП: 220-300к ₽ на руки<br/>Обязанности: бюджетирование и управленческая отчетность, финансовое моделирование. "
            "Требования: Excel, SQL, Power BI, опыт от 3 лет.")
    return f"""<div class="tgme_widget_message" data-post="finjobs/77"><div class="tgme_widget_message_text">{text}</div>
      <a class="tgme_widget_message_date" href="https://t.me/finjobs/77"><time datetime="{now}"></time></a></div>"""


def gh_payload(with_quant: bool) -> dict:
    jobs = [{"id": 2, "title": "Senior Software Engineer", "absolute_url": "https://gh/2", "location": {"name": "Chicago"},
             "content": "Go, Kubernetes", "updated_at": datetime.now(timezone.utc).isoformat()},
            {"id": 3, "title": "Investment Banking Summer Analyst Internship", "absolute_url": "https://gh/3",
             "location": {"name": "London"}, "content": "M&A execution support",
             "updated_at": datetime.now(timezone.utc).isoformat()}]
    if with_quant:
        jobs.append({"id": 1, "title": "Quantitative Researcher", "absolute_url": "https://gh/1", "location": {"name": "Chicago"},
                     "content": "&lt;p&gt;Statistical arbitrage research. Compensation $200,000 - $250,000 per year.&lt;/p&gt;",
                     "updated_at": datetime.now(timezone.utc).isoformat()})
    return {"jobs": jobs}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "sources.yaml").write_text(yaml.safe_dump({
        "settings": {"db": "data/test.db", "max_workers": 2, "report_dir": "reports"},
        "sources": [
            {"name": "hh", "type": "hh", "access_token": "tok", "queries": ["аналитик"], "max_pages": 1},
            {"name": "tg", "type": "telegram", "channels": ["finjobs"], "pages": 1},
            {"name": "gh", "type": "greenhouse", "companies": ["jumptrading"], "names": {"jumptrading": "Jump Trading"}},
            {"name": "broken", "type": "reed", "enabled": True},
            {"name": "off", "type": "remotive", "enabled": False},
        ],
    }, allow_unicode=True), encoding="utf-8")
    (cfg_dir / "profile.yaml").write_text(yaml.safe_dump({"profile": {
        "domains": {"corp_finance": 1.0, "quant": 0.5, "ib_ma": 0.8},
        "keywords": {"FP&A": 3, "Power BI": 1},
        "seniority": ["middle", "senior"],
        "min_salary": {"rub_month": 200000, "usd_year": 100000},
        "locations": ["Москва"],
    }}, allow_unicode=True), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("REED_API_KEY", raising=False)

    state = {"salary_to": 300000, "with_quant": True}
    fake = FakeHttp([
        (r"cbr\.ru", CBR),
        (r"api\.hh\.ru/vacancies", lambda *a: hh_payload(state["salary_to"])),
        (r"t\.me/s/finjobs", lambda *a: tg_page()),
        (r"boards-api\.greenhouse\.io/v1/boards/jumptrading", lambda *a: gh_payload(state["with_quant"])),
    ])
    monkeypatch.setattr(pipeline, "build_http", lambda cfg: fake)
    return tmp_path, state


def test_end_to_end(workspace, capsys):
    root, state = workspace
    cfg = load_config(root / "config/sources.yaml", root / "config/profile.yaml")
    assert cfg.db_path == root / "data/test.db"

    with Store(cfg.db_path) as store:
        results = {r.name: r for r in pipeline.run(cfg, store)}
        assert results["hh"].status == "ok" and results["hh"].fetched == 2 and results["hh"].kept == 1  # driver filtered out
        assert results["tg"].kept == 1
        assert results["gh"].kept == 2  # software engineer filtered out
        assert results["broken"].status == "skipped" and "REED_API_KEY" in results["broken"].error
        assert "off" not in results

        # FX came from the (fake) CBR feed and salaries were normalized
        hh = store.get("hh:101")
        assert hh["salary_month_rub"] == 260000 and hh["salary_currency"] == "RUB"
        quant = store.get("gh:jumptrading-1")
        assert quant["salary_year_usd"] == 225000 and quant["primary_domain"] == "quant"
        intern = store.get("gh:jumptrading-3")
        assert intern["kind"] == "internship" and intern["seniority"] == "intern"

        # hh and Telegram copies of the same role collapse into one cluster; hh wins as canonical
        tg = store.get("tg:finjobs/77")
        assert tg["cluster_id"] == hh["cluster_id"]
        assert hh["is_canonical"] == 1 and tg["is_canonical"] == 0

        ov = analytics.overview(store)
        assert (ov["active"], ov["active_rows"], ov["duplicates"]) == (3, 4, 1)

        # personal scoring: the FP&A role in Moscow outranks the quant role and the internship
        assert hh["score"] > quant["score"] > 0
        assert any("FP&A" in r for r in json.loads(hh["score_reasons"]))

        # Second run: salary raised on hh, quant role removed from the Greenhouse board
        state["salary_to"] = 340000
        state["with_quant"] = False
        results = {r.name: r for r in pipeline.run(cfg, store)}
        assert results["hh"].updated == 1 and results["gh"].closed == 1
        assert store.get("gh:jumptrading-1")["is_active"] == 0
        changes = store.conn.execute("SELECT field, old, new FROM changes WHERE uid='hh:101'").fetchall()
        assert [(c["field"], c["old"], c["new"]) for c in changes] == [("salary_max", "300000.0", "340000.0")]
        assert analytics.salary_changes(store)["raised"] == 1

        rep = analytics.full_report(store)
        assert rep["overview"]["active"] == 2
        assert {s["source"] for s in rep["sources"]} >= {"hh", "tg", "gh"}

        items = digest.select(store, days=1, min_score=0)
        assert items[0]["uid"] == "hh:101"
        md = digest.to_markdown(items)
        assert "Финансовый аналитик (FP&A)" in md
        msgs = digest.to_telegram_html(items)
        assert msgs and all(len(m) < 4096 for m in msgs)
        digest.mark_sent(store, items)
        assert digest.select(store, days=1, min_score=0) == []

    # CLI commands work against the same workspace
    args = ["-c", "config/sources.yaml", "-p", "config/profile.yaml"]
    assert cli.main([*args, "stats"]) == 0
    assert cli.main([*args, "report", "-o", "reports/test.html"]) == 0
    html = Path("reports/test.html").read_text(encoding="utf-8")
    assert "Финансовый аналитик (FP&amp;A)" in html or "Финансовый аналитик (FP\\u0026A)" in html or "Финансовый аналитик (FP&A)" in html
    assert "<script>" in html and "</html>" in html
    assert cli.main([*args, "export", "-f", "csv", "-o", "reports/v.csv"]) == 0
    assert "hh:101" in Path("reports/v.csv").read_text(encoding="utf-8-sig")
    assert cli.main([*args, "search", "бюджетирование"]) == 0
    assert "hh:101" in capsys.readouterr().out
    assert cli.main([*args, "top", "--days", "3"]) == 0
    assert cli.main([*args, "show", "hh:101"]) == 0
    out = capsys.readouterr().out
    assert "tg:finjobs/77" in out and "salary_max: 300000.0 → 340000.0" in out
    assert cli.main([*args, "sources"]) == 0
    assert cli.main([*args, "rescore"]) == 0


def test_dry_run_and_doctor(workspace, capsys):
    root, _ = workspace
    args = ["-c", "config/sources.yaml", "-p", "config/profile.yaml"]
    assert cli.main([*args, "fetch", "--dry-run", "-s", "hh"]) == 0
    with Store(root / "data/test.db") as store:
        assert store.count() == 0
    assert cli.main([*args, "doctor"]) == 0
    out = capsys.readouterr().out
    assert "Финансовый аналитик" in out and "REED_API_KEY" in out


def test_init_creates_configs(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init"]) == 0
    assert Path("config/sources.yaml").exists() and Path("config/profile.yaml").exists() and Path(".env").exists()
    cfg = load_config("config/sources.yaml", "config/profile.yaml")
    assert len(cfg.enabled_sources()) >= 15
    assert cfg.profile["domains"]["corp_finance"] == 1.0
    # every configured type exists
    from finradar.sources import REGISTRY

    assert all(s["type"] in REGISTRY for s in cfg.sources)


def test_expire_stream_sources(tmp_path):
    from finradar.models import Vacancy

    with Store(tmp_path / "x.db") as store:
        old = Vacancy("tg", "1", "https://t.me/x/1", "Аналитик", published_at=datetime.now(timezone.utc) - timedelta(days=40))
        new = Vacancy("tg", "2", "https://t.me/x/2", "Экономист", published_at=datetime.now(timezone.utc))
        store.upsert([old, new])
        assert store.expire("tg", ttl_days=30) == 1
        assert store.get("tg:1")["is_active"] == 0 and store.get("tg:2")["is_active"] == 1
        assert [r["uid"] for r in store.search("экономист")] == ["tg:2"]
