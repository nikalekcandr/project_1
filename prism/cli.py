"""Командная строка Prism.

    prism snapshot demo                 создать демо-снапшоты в хранилище
    prism snapshot list | show ID | qc ID [--prev ID] | correct ID --set Q=V --reason "..."
    prism templates                     каталог структур (шаблоны термшитов)
    prism new TEMPLATE [--set k=v] [-o trade.yaml]
    prism price trade.yaml [--snapshot ID] [--report r.html] [--json r.json] [--record rec.json] [--fast|--price-only]
    prism replay rec.json               воспроизвести оценку «бит в бит»
    prism compare a.yaml b.yaml ...     сравнить пакеты (кредит + хедж) разных банков
    prism portfolio DIR [--xva] [--workers N]   переоценка портфеля (параллельно)
    prism validate                      арбитражные проверки, сверка с QuantLib, регрессия
    prism serve [--port 8000]           веб-интерфейс
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import yaml


def _store(args):
    from .marketdata.store import SnapshotStore
    return SnapshotStore(getattr(args, "store", None))


def _snapshot(args):
    st = _store(args)
    sid = getattr(args, "snapshot", None)
    if sid:
        return st.load(sid)
    if not st.ids():
        from .marketdata.demo import demo_store_snapshots
        cur, _ = demo_store_snapshots(st)
        print(f"Хранилище пусто — создан демо-снапшот {cur.id}", file=sys.stderr)
        return cur
    return st.latest()


def _fmt(v: float) -> str:
    return f"{v:,.2f}".replace(",", " ")


def _print_table(headers, rows):
    cols = list(zip(*([headers] + [[str(c) for c in r] for r in rows]))) if rows else [[h] for h in headers]
    widths = [max(len(str(x)) for x in col) for col in cols]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    print(line)
    print("  ".join("─" * w for w in widths))
    for r in rows:
        print("  ".join(str(c).rjust(w) if isinstance(c, (int, float)) or (isinstance(c, str) and c[:1] in "-0123456789") else str(c).ljust(w)
                        for c, w in zip(r, widths)))


# --------------------------------------------------------------------------- snapshot
def cmd_snapshot(args):
    st = _store(args)
    if args.action == "demo":
        from .marketdata.demo import demo_store_snapshots
        cur, prev = demo_store_snapshots(st)
        print(f"создано: {prev.id}\nсоздано: {cur.id}\nхранилище: {st.root}")
    elif args.action == "list":
        rows = []
        for sid in st.ids():
            s = st.load(sid)
            rows.append([sid, s.as_of.isoformat()[:16], len(s.quotes), len(s.datasets), "да" if s.is_demo else "", s.parent_id or ""])
        _print_table(["id", "as_of", "котировок", "датасетов", "демо", "исправляет"], rows)
    elif args.action == "show":
        s = st.load(args.id)
        print(f"{s.id}\nas_of {s.as_of}\nхэш {s.content_hash}\nкотировок {len(s.quotes)}, датасетов {len(s.datasets)}")
        if s.correction:
            print("исправление:", json.dumps(dict(s.correction), ensure_ascii=False))
        fams = {}
        for q in s.quotes:
            fams[q.split(".")[0]] = fams.get(q.split(".")[0], 0) + 1
        print("семейства:", ", ".join(f"{k}:{v}" for k, v in sorted(fams.items())))
    elif args.action == "qc":
        from .marketdata.qc import qc_summary, run_qc
        s = st.load(args.id)
        prev = st.load(args.prev) if args.prev else None
        f = run_qc(s, prev)
        _print_table(["уровень", "проверка", "котировка", "сообщение"], [[x.severity, x.check, x.quote_id, x.message] for x in f])
        print(qc_summary(f))
    elif args.action == "correct":
        s = st.load(args.id)
        changes = {}
        for kv in args.set or []:
            k, v = kv.split("=", 1)
            changes[k] = s.quote(k).with_value(float(v), note=f"исправление: {args.reason}")
        new = st.correct(args.id, changes, args.reason)
        print(f"создан исправленный снапшот {new.id} (родитель {s.id}); исходный не изменён")


# --------------------------------------------------------------------------- templates
def cmd_templates(args):
    from .instruments.templates import list_templates
    rows = [[t["id"], t.get("group", ""), t["name"]] for t in list_templates()]
    rows.sort(key=lambda r: (r[1], r[0]))
    _print_table(["шаблон", "группа", "структура"], rows)


def cmd_new(args):
    from .instruments.templates import render, template_meta
    params = {}
    for kv in args.set or []:
        k, v = kv.split("=", 1)
        params[k] = v
    data = render(args.template, params)
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=None)
    header = f"# {template_meta(args.template)['name']}\n# сгенерировано из шаблона {args.template}; правьте поля под термшит\n"
    if args.output:
        Path(args.output).write_text(header + text, encoding="utf-8")
        print(f"записано: {args.output}")
    else:
        print(header + text)


# --------------------------------------------------------------------------- price
def cmd_price(args):
    from .audit.record import save_record
    from .instruments.schema import load_trade
    from .reporting.html import save_report
    from .valuation import ValuationOptions, run_valuation
    trade = load_trade(args.trade)
    snap = _snapshot(args)
    if args.price_only:
        opts = ValuationOptions.price_only()
    elif args.fast:
        opts = ValuationOptions.fast()
    else:
        opts = ValuationOptions()
    if args.engine:
        opts.engine = args.engine
    if args.ifrs9_host:
        opts.ifrs9_host = args.ifrs9_host
    t = time.time()
    v = run_valuation(trade, snap, opts)
    p = v.pricing
    print(f"{trade.product}\nснапшот {snap.id}{' (ДЕМО)' if snap.is_demo else ''}")
    print(f"справедливая стоимость для клиента: {_fmt(p.value)} {p.currency}   [{p.engine}: {p.model}]")
    if p.mc:
        print(f"  МК: ст. ошибка {_fmt(p.mc['stderr'])}, 95% ДИ [{_fmt(p.mc['ci95'][0])}; {_fmt(p.mc['ci95'][1])}], путей {p.mc['paths']}")
    if v.breakdown:
        b = v.breakdown
        print("разложение:")
        for w in [{"label": "передача стоимости банку", "value": b.transfer}] + b.waterfall():
            print(f"  {w['label']:<34s} {_fmt(w['value']):>18s}")
    if v.alternatives:
        print("ванильные альтернативы:")
        for a in v.alternatives:
            print(f"  {a['label']:<46s} {_fmt(a['value']):>18s}")
    if v.profile:
        for s in v.profile.summary:
            print("  •", s)
    for w in p.warnings[:10]:
        print("  ⚠", w)
    for e in v.errors:
        print("  ✕", e)
    if args.report:
        print("отчёт:", save_report(v, args.report))
    if args.json:
        Path(args.json).write_text(json.dumps(v.to_dict(), ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print("json:", args.json)
    rec_path = args.record or (str(Path(args.report).with_suffix(".record.json")) if args.report else None)
    if rec_path:
        save_record(v.record, rec_path)
        print("аудиторская запись:", rec_path)
    print(f"время: {time.time() - t:.1f} с")


def cmd_replay(args):
    from .audit.record import replay
    res = replay(args.record, _store(args))
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    sys.exit(0 if res.get("ok") else 1)


def cmd_compare(args):
    from .marketdata.context import MarketContext
    from .packages.package import compare_offers, load_package
    snap = _snapshot(args)
    ctx = MarketContext(snap)
    pk = [load_package(p) for p in args.packages]
    res = compare_offers(pk, ctx)
    rows = [[r["package"], r["bank"], f"{r['effective_rate']:.3%}", f"{r['vs_best_bp']:+.1f}"] +
            [f"{v:,.1f}" for v in r["components_bp"].values()] for r in res["table"]]
    hdr = ["пакет", "банк", "эфф. ставка", "к лучшему, б.п."] + list(res["table"][0]["components_bp"].keys())
    _print_table(hdr, rows)
    print("лучшее предложение:", res["best"])
    if args.json:
        Path(args.json).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def _price_files(job):
    """Переоценка части портфеля в отдельном процессе: свой контекст рынка на том же снапшоте (детерминизм — seed сделки)."""
    import warnings
    from .instruments.schema import load_trade
    from .marketdata.context import MarketContext
    from .marketdata.store import SnapshotStore
    from .pricing.engine import price_trade
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    store_dir, snap_id, files, paths = job
    ctx = MarketContext(SnapshotStore(store_dir).load(snap_id))
    out = []
    for f in files:
        try:
            tr = load_trade(f)
            t = time.time()
            r = price_trade(tr, ctx, mc_overrides={"paths": paths} if paths else None)
            out.append((f, [tr.identification.trade_id, tr.product[:48], r.engine, _fmt(r.value), f"{(time.time() - t) * 1000:.0f}"], True))
        except Exception as e:
            out.append((f, [Path(f).stem, f"ОШИБКА: {e}"[:60], "", "", ""], False))
    return out


def cmd_portfolio(args):
    from .instruments.schema import load_trade
    from .marketdata.context import MarketContext
    snap = _snapshot(args)
    files = [str(f) for f in sorted(Path(args.dir).glob("*.yaml"))]
    t0 = time.time()
    store_dir = str(_store(args).root)
    workers = max(1, min(args.workers or 1, len(files) or 1))
    if workers == 1:
        res = _price_files((store_dir, snap.id, files, args.paths))
    else:
        from concurrent.futures import ProcessPoolExecutor
        chunks = [files[i::workers] for i in range(workers)]
        with ProcessPoolExecutor(max_workers=workers) as ex:
            res = [r for part in ex.map(_price_files, [(store_dir, snap.id, c, args.paths) for c in chunks]) for r in part]
        order = {f: i for i, f in enumerate(files)}
        res.sort(key=lambda r: order[r[0]])
    rows = [r[1] for r in res]
    trades = [load_trade(f) for f, _, ok in res if ok]
    ctx = MarketContext(snap)
    _print_table(["сделка", "продукт", "движок", "стоимость", "мс"], rows)
    print(f"сделок: {len(trades)}, процессов: {workers}, время: {time.time() - t0:.1f} с")
    if args.xva and trades:
        from .xva.engine import compute_xva
        by_ns: dict[str, list] = {}
        for tr in trades:
            ns = tr.identification.netting_set or f"{tr.identification.client}/{tr.identification.bank}"
            by_ns.setdefault(ns, []).append(tr)
        for ns, trs in by_ns.items():
            x = compute_xva(trs, ctx)
            print(f"неттинг-сет {ns}: сделок {len(trs)}, CVA {_fmt(x.cva)}, DVA {_fmt(x.dva)}, EPE {_fmt(x.epe)} ({x.netting})")


def cmd_validate(args):
    from .validation.suite import run_suite
    ok = run_suite(quick=args.quick, verbose=True, update_golden=args.update_golden, reason=args.reason or "")
    sys.exit(0 if ok else 1)


def cmd_serve(args):
    try:
        import uvicorn
    except ImportError:
        print("нужны пакеты fastapi и uvicorn: pip install 'prism-otc[web]'")
        sys.exit(1)
    from .web.app import create_app
    uvicorn.run(create_app(args.store), host=args.host, port=args.port, log_level="info")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="prism", description="Prism — независимый прайсер внебиржевых ПФИ (РФ)")
    ap.add_argument("--store", help="каталог хранилища снапшотов (по умолчанию ./snapshots или PRISM_SNAPSHOT_DIR)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot", help="снапшоты рынка")
    s.add_argument("action", choices=["demo", "list", "show", "qc", "correct"])
    s.add_argument("id", nargs="?")
    s.add_argument("--prev")
    s.add_argument("--set", action="append")
    s.add_argument("--reason", default="")
    s.set_defaults(fn=cmd_snapshot)
    s = sub.add_parser("templates", help="каталог шаблонов структур")
    s.set_defaults(fn=cmd_templates)
    s = sub.add_parser("new", help="сделка из шаблона")
    s.add_argument("template")
    s.add_argument("--set", action="append", help="параметр шаблона k=v")
    s.add_argument("-o", "--output")
    s.set_defaults(fn=cmd_new)
    s = sub.add_parser("price", help="оценка сделки")
    s.add_argument("trade")
    s.add_argument("--snapshot")
    s.add_argument("--engine", choices=["auto", "analytic", "mc", "tree"])
    s.add_argument("--report")
    s.add_argument("--json")
    s.add_argument("--record")
    s.add_argument("--fast", action="store_true")
    s.add_argument("--price-only", action="store_true")
    s.add_argument("--ifrs9-host", choices=["financial_liability", "financial_asset", "non_financial", "lease"])
    s.set_defaults(fn=cmd_price)
    s = sub.add_parser("replay", help="воспроизвести оценку по аудиторской записи")
    s.add_argument("record")
    s.set_defaults(fn=cmd_replay)
    s = sub.add_parser("compare", help="сравнить пакеты предложений банков")
    s.add_argument("packages", nargs="+")
    s.add_argument("--snapshot")
    s.add_argument("--json")
    s.set_defaults(fn=cmd_compare)
    s = sub.add_parser("portfolio", help="переоценка портфеля сделок из каталога")
    s.add_argument("dir")
    s.add_argument("--snapshot")
    s.add_argument("--xva", action="store_true")
    s.add_argument("--paths", type=int)
    s.add_argument("--workers", type=int, default=1, help="число процессов для параллельной переоценки")
    s.set_defaults(fn=cmd_portfolio)
    s = sub.add_parser("validate", help="набор проверок и сверок")
    s.add_argument("--quick", action="store_true")
    s.add_argument("--update-golden", action="store_true", help="перезаписать эталонные цены (требует --reason)")
    s.add_argument("--reason", help="причина изменения эталонов — сохраняется в истории golden.json")
    s.set_defaults(fn=cmd_validate)
    s = sub.add_parser("serve", help="веб-интерфейс")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=cmd_serve)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
