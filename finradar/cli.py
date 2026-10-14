"""Command-line interface: ``finradar <command>``."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from finradar import analytics, digest, pipeline
from finradar.config import Config, load_config
from finradar.report import format_salary, render
from finradar.scoring import Profile, rescore
from finradar.storage import Store, row_to_dict
from finradar.taxonomy import DOMAIN_LABELS

ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- output helpers

def table(rows: list[list], headers: list[str], max_width: int = 48) -> str:
    cells = [[str(h) for h in headers]] + [["" if c is None else str(c) for c in r] for r in rows]
    cells = [[c if len(c) <= max_width else c[: max_width - 1] + "…" for c in r] for r in cells]
    widths = [max(len(r[i]) for r in cells) for i in range(len(headers))]
    line = lambda r: "  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip()  # noqa: E731
    out = [line(cells[0]), "  ".join("─" * w for w in widths)]
    out += [line(r) for r in cells[1:]]
    return "\n".join(out)


def _rub(v) -> str:
    return "—" if v is None else f"{v / 1000:,.0f}k ₽".replace(",", " ")


def _usd(v) -> str:
    return "—" if v is None else f"${v / 1000:,.0f}k"


# --------------------------------------------------------------------------- commands

def cmd_init(args, _cfg: Config | None) -> int:
    cfg_dir = Path(args.config).parent
    cfg_dir.mkdir(parents=True, exist_ok=True)
    pairs = [
        (ROOT / "config" / "sources.example.yaml", Path(args.config)),
        (ROOT / "config" / "profile.example.yaml", Path(args.profile)),
        (ROOT / "config" / "resume.example.txt", cfg_dir / "resume.txt"),
        (ROOT / ".env.example", Path(".env")),
    ]
    for src, dst in pairs:
        if dst.exists():
            print(f"= {dst} уже существует — не трогаю")
        elif src.exists():
            shutil.copyfile(src, dst)
            print(f"+ {dst}")
    print("\nДальше: отредактируйте config/profile.yaml и config/resume.txt, затем `finradar doctor` и `finradar fetch`.")
    return 0


def cmd_sources(args, cfg: Config) -> int:
    with Store(cfg.db_path) as store:
        runs = store.last_runs()
        rows = []
        for s in cfg.sources:
            r = runs.get(s["name"])
            rows.append([
                s["name"], s["type"], "on" if s.get("enabled", True) else "off",
                r["status"] if r else "—", (r["finished_at"] or "")[:16].replace("T", " ") if r else "",
                r["kept"] if r else "", (r["error"] or "")[:60] if r else "",
            ])
    print(table(rows, ["источник", "тип", "вкл", "статус", "последний запуск", "собрано", "ошибка"]))
    return 0


def _print_results(results) -> None:
    rows = [[r.name, r.status, r.fetched, r.kept, r.new, r.updated, r.closed, f"{r.seconds}s",
             (r.error or "; ".join(r.warnings))[:70]] for r in results]
    print(table(rows, ["источник", "статус", "получено", "релевантных", "новых", "обновлено", "закрыто", "время", "заметки"]))


def cmd_fetch(args, cfg: Config) -> int:
    with Store(cfg.db_path) as store:
        t0 = time.monotonic()
        results = pipeline.run(cfg, store, only=args.source or None, dry_run=args.dry_run)
        _print_results(results)
        ov = analytics.overview(store)
        print(f"\nАктивных уникальных позиций: {ov['active']} (дублей схлопнуто: {ov['duplicates']}), "
              f"новых за 24 ч: {ov['new_24h']}. Время: {time.monotonic() - t0:.0f}s")
    return 0 if all(r.status in ("ok", "partial", "skipped") for r in results) else 2


def cmd_doctor(args, cfg: Config) -> int:
    """Live check of each source with a tiny limit — nothing is written to the database."""
    http = pipeline.build_http(cfg)
    rows = []
    items = cfg.sources if args.all else cfg.enabled_sources(args.source or None)
    for item in items:
        probe = {**item, "max_items": args.limit, "max_pages": 1, "pages": 1, "max_details": args.limit}
        t0 = time.monotonic()
        try:
            src = pipeline.build_source(probe, http)
            got, fetched, status, error = pipeline.collect(src, {"RUB": 1.0, "USD": 80.0}, 0.0)
            sample = got[0].title if got else ""
            rows.append([item["name"], item["type"], status, fetched, f"{time.monotonic() - t0:.1f}s",
                         (error or "; ".join(src.warnings) or sample)[:70]])
        except Exception as exc:
            rows.append([item["name"], item["type"], "config", 0, "", str(exc)[:70]])
    print(table(rows, ["источник", "тип", "статус", "получено", "время", "пример / ошибка"]))
    return 0


def _print_vacancies(rows: list[dict]) -> None:
    out = []
    for d in rows:
        out.append([
            f"{d.get('score') or 0:.0f}", d["title"], d.get("company") or "", format_salary(d),
            d.get("city") or d.get("location") or "", d["source"], d["uid"],
        ])
    print(table(out, ["скор", "позиция", "компания", "зарплата", "локация", "источник", "id"], max_width=42))


def cmd_search(args, cfg: Config) -> int:
    with Store(cfg.db_path) as store:
        rows = [row_to_dict(r) for r in store.search(args.query, active_only=not args.all, limit=args.limit * 3)]
    if args.domain:
        rows = [r for r in rows if r.get("primary_domain") == args.domain or args.domain in (r.get("domains") or [])]
    if args.remote:
        rows = [r for r in rows if r.get("work_format") == "remote"]
    if args.min_salary:
        rows = [r for r in rows if (r.get("salary_month_rub") or 0) >= args.min_salary]
    _print_vacancies(rows[: args.limit])
    return 0


def cmd_top(args, cfg: Config) -> int:
    with Store(cfg.db_path) as store:
        since = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
        where = "is_active=1 AND is_canonical=1 AND first_seen >= ?"
        params: tuple = (since,)
        if args.kind:
            where += " AND kind=?"
            params += (args.kind,)
        rows = [row_to_dict(r) for r in store.iter_rows(where, params, order="score DESC", limit=args.limit)]
    _print_vacancies(rows)
    return 0


def cmd_show(args, cfg: Config) -> int:
    with Store(cfg.db_path) as store:
        row = store.get(args.uid)
        if not row:
            print("не найдено")
            return 1
        d = row_to_dict(row)
        changes = store.conn.execute("SELECT at, field, old, new FROM changes WHERE uid=? ORDER BY at", (args.uid,)).fetchall()
        dups = store.conn.execute("SELECT uid, url FROM vacancies WHERE cluster_id=? AND uid != ?", (d["cluster_id"], args.uid)).fetchall()
    print(f"{d['title']}\n{d.get('company') or ''}  ·  {format_salary(d)}  ·  {d.get('city') or d.get('location') or ''}")
    print(f"{d['url']}\n")
    for key in ("primary_domain", "domains", "kind", "seniority", "work_format", "skills", "score", "score_reasons",
                "published_at", "first_seen", "last_seen", "is_active", "salary_month_rub", "salary_year_usd"):
        print(f"  {key:16} {d.get(key)}")
    if d.get("llm"):
        print(f"  {'llm':16} {json.dumps(d['llm'], ensure_ascii=False)[:600]}")
    if dups:
        print("\nТа же позиция в других источниках:")
        for r in dups:
            print(f"  {r['uid']}  {r['url']}")
    if changes:
        print("\nИстория изменений:")
        for c in changes:
            print(f"  {c['at'][:16]}  {c['field']}: {c['old']} → {c['new']}")
    print("\n" + (d.get("description") or "")[:3000])
    return 0


def cmd_stats(args, cfg: Config) -> int:
    with Store(cfg.db_path) as store:
        rep = analytics.full_report(store)
    ov = rep["overview"]
    print(f"Активных уникальных: {ov['active']}  (строк: {ov['active_rows']}, дублей: {ov['duplicates']})")
    print(f"Новых: 24ч {ov['new_24h']} · 7д {ov['new_7d']} · 30д {ov['new_30d']}   Закрыто за 7д: {ov['closed_7d']}")
    print(f"С зарплатой: {ov['salary_share']:.0%} · Удалённо: {ov['remote_share']:.0%} · Компаний: {ov['companies']}\n")
    print(table([[DOMAIN_LABELS.get(k, k), v] for k, v in rep["domains"]], ["направление", "позиций"]))
    print()
    if rep["salary_domestic"]:
        print("Зарплаты, ₽/мес на руки (медиана и P25–P75):")
        print(table([[DOMAIN_LABELS.get(r["group"], r["group"]), r["n"], _rub(r["p25"]), _rub(r["median"]), _rub(r["p75"])]
                     for r in rep["salary_domestic"]], ["направление", "n", "P25", "медиана", "P75"]))
        print()
    if rep["salary_global"]:
        print("Зарплаты, USD/год gross:")
        print(table([[DOMAIN_LABELS.get(r["group"], r["group"]), r["n"], _usd(r["p25"]), _usd(r["median"]), _usd(r["p75"])]
                     for r in rep["salary_global"]], ["направление", "n", "P25", "медиана", "P75"]))
        print()
    print("Работодатели:")
    print(table([[c["company"], c["active"], c["new_14d"], f"{c['momentum']:+d}"] for c in rep["companies"][:15]],
                ["компания", "активных", "новых 14д", "импульс"]))
    print()
    print("Навыки:")
    print(table([[s["skill"], s["count"], f"{s['share']:.0%}", f"{s['premium']:+.0%}" if s["premium"] is not None else "—"]
                 for s in rep["skills"][:15]], ["навык", "позиций", "доля", "премия"]))
    print()
    print("Источники:")
    print(table([[s["source"], s["active"], f"{s['exclusive_share']:.0%}", f"{s['salary_share']:.0%}", s["median_age_days"], s["last_status"]]
                 for s in rep["sources"]], ["источник", "активных", "эксклюзив", "с з/п", "возраст, дн", "статус"]))
    return 0


def cmd_report(args, cfg: Config) -> int:
    out = Path(args.output or Path(cfg.settings["report_dir"]) / "index.html")
    if not out.is_absolute():
        out = cfg.base_dir / out
    with Store(cfg.db_path) as store:
        path = render(store, out)
    print(f"Отчёт: {path}")
    return 0


def cmd_digest(args, cfg: Config) -> int:
    with Store(cfg.db_path) as store:
        items = digest.select(store, days=args.days, min_score=args.min_score, limit=args.limit,
                              only_unsent=not args.include_sent)
        if args.send:
            from finradar.notify import send_telegram

            tg = cfg.settings.get("telegram") or {}
            if items:
                n = send_telegram(digest.to_telegram_html(items), tg.get("bot_token"), tg.get("chat_id"))
                digest.mark_sent(store, items)
                print(f"Отправлено сообщений в Telegram: {n} ({len(items)} позиций)")
            else:
                print("Новых подходящих позиций нет — ничего не отправлено")
        else:
            print(digest.to_markdown(items))
    return 0


def cmd_export(args, cfg: Config) -> int:
    where = "1=1" if args.all else "is_active=1 AND is_canonical=1"
    with Store(cfg.db_path) as store:
        rows = [row_to_dict(r) for r in store.iter_rows(where, order="score DESC")]
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.format == "json":
        out.write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    elif args.format == "jsonl":
        out.write_text("\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in rows), encoding="utf-8")
    else:
        cols = ["uid", "title", "company", "primary_domain", "kind", "seniority", "work_format", "city", "country",
                "salary_min", "salary_max", "salary_currency", "salary_period", "salary_month_rub", "salary_year_usd",
                "score", "source", "url", "published_at", "first_seen", "last_seen", "is_active", "skills"]
        with out.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for r in rows:
                w.writerow([", ".join(r[c]) if isinstance(r.get(c), list) else r.get(c) for c in cols])
    print(f"Экспортировано {len(rows)} → {out}")
    return 0


def cmd_enrich(args, cfg: Config) -> int:
    from finradar.llm import enrich_store

    resume = Path(args.resume) if args.resume else Path(args.profile).parent / "resume.txt"
    with Store(cfg.db_path) as store:
        stats = enrich_store(store, cfg.settings, cfg.profile, resume_path=resume, limit=args.limit)
        rescore(store, Profile.from_dict(cfg.profile))
    print(stats)
    return 0


def cmd_rescore(args, cfg: Config) -> int:
    with Store(cfg.db_path) as store:
        stats = pipeline.postprocess(cfg, store)
    print(stats)
    return 0


# --------------------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="finradar", description="Агрегатор вакансий и возможностей: финансы, экономика, аналитика")
    p.add_argument("-c", "--config", default="config/sources.yaml", help="путь к sources.yaml")
    p.add_argument("-p", "--profile", default="config/profile.yaml", help="путь к profile.yaml")
    p.add_argument("-v", "--verbose", action="count", default=0)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="создать config/*.yaml и .env из примеров").set_defaults(func=cmd_init, needs_cfg=False)
    sub.add_parser("sources", help="список источников и статус последнего запуска").set_defaults(func=cmd_sources)

    f = sub.add_parser("fetch", help="собрать вакансии из всех включённых источников")
    f.add_argument("-s", "--source", action="append", help="только этот источник/тип (можно несколько)")
    f.add_argument("--dry-run", action="store_true", help="не писать в базу")
    f.set_defaults(func=cmd_fetch)

    d = sub.add_parser("doctor", help="живая проверка источников (по 5 позиций, без записи)")
    d.add_argument("-s", "--source", action="append")
    d.add_argument("--all", action="store_true", help="включая выключенные")
    d.add_argument("--limit", type=int, default=5)
    d.set_defaults(func=cmd_doctor)

    s = sub.add_parser("search", help="полнотекстовый поиск")
    s.add_argument("query")
    s.add_argument("--domain", choices=list(DOMAIN_LABELS))
    s.add_argument("--remote", action="store_true")
    s.add_argument("--min-salary", type=float, help="₽/мес на руки")
    s.add_argument("--all", action="store_true", help="включая закрытые")
    s.add_argument("--limit", type=int, default=30)
    s.set_defaults(func=cmd_search)

    t = sub.add_parser("top", help="лучшие совпадения с профилем")
    t.add_argument("--days", type=float, default=7)
    t.add_argument("--kind", help="vacancy / internship / fellowship / grant / competition ...")
    t.add_argument("--limit", type=int, default=30)
    t.set_defaults(func=cmd_top)

    sh = sub.add_parser("show", help="карточка позиции, дубли и история изменений")
    sh.add_argument("uid")
    sh.set_defaults(func=cmd_show)

    sub.add_parser("stats", help="аналитика рынка в терминале").set_defaults(func=cmd_stats)

    r = sub.add_parser("report", help="HTML-отчёт с аналитикой и поиском")
    r.add_argument("-o", "--output")
    r.set_defaults(func=cmd_report)

    dg = sub.add_parser("digest", help="дайджест новых подходящих позиций")
    dg.add_argument("--days", type=float, default=1)
    dg.add_argument("--min-score", type=float, default=40)
    dg.add_argument("--limit", type=int, default=30)
    dg.add_argument("--send", action="store_true", help="отправить в Telegram")
    dg.add_argument("--include-sent", action="store_true")
    dg.set_defaults(func=cmd_digest)

    e = sub.add_parser("export", help="выгрузка в CSV/JSON")
    e.add_argument("-f", "--format", choices=["csv", "json", "jsonl"], default="csv")
    e.add_argument("-o", "--output", default="reports/vacancies.csv")
    e.add_argument("--all", action="store_true", help="включая закрытые и дубли")
    e.set_defaults(func=cmd_export)

    en = sub.add_parser("enrich", help="LLM-обогащение лучших новых позиций (Claude, опционально)")
    en.add_argument("--limit", type=int)
    en.add_argument("--resume")
    en.set_defaults(func=cmd_enrich)

    sub.add_parser("rescore", help="пересчитать дедупликацию и скоринг (после правки profile.yaml)").set_defaults(func=cmd_rescore)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING - 10 * min(args.verbose, 2),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if getattr(args, "needs_cfg", True):
        if not Path(args.config).exists():
            print(f"Нет {args.config}. Выполните `finradar init`.", file=sys.stderr)
            return 1
        cfg = load_config(args.config, args.profile)
    else:
        cfg = None
    return int(args.func(args, cfg) or 0)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
