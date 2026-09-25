"""Командная строка: ``mmsim <команда>`` или ``python -m mmsim <команда>``.

Команды:
    fetch      — скачать и закэшировать данные MOEX ISS
    calibrate  — оценить σ, A, k
    run        — бэктест одной стратегии + HTML-отчёт
    compare    — сравнить несколько стратегий на одних данных
    sweep      — перебор параметра (например, γ)
    paper      — воспроизвести эксперимент Авельянеды–Стойкова (2008)
    synth      — сгенерировать синтетические данные в CSV
"""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from mmsim.config import SimConfig, load_market_data
from mmsim.data.moex import MoexUnavailable
from mmsim.engine import run_backtest
from mmsim.metrics import format_metrics, metrics_frame
from mmsim.models.calibration import calibrate, intensity_table
from mmsim.strategies import STRATEGIES, make_strategy


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("-c", "--config", help="TOML-файл конфигурации")
    p.add_argument("--source", choices=["moex", "csv", "synthetic"], help="источник данных")
    p.add_argument("--secid", help="тикер, например SBER")
    p.add_argument("--board", help="режим торгов (TQBR — акции, RFUD — фьючерсы)")
    p.add_argument("--from", dest="start", help="первый день бэктеста, YYYY-MM-DD")
    p.add_argument("--till", dest="end", help="последний день бэктеста, YYYY-MM-DD")
    p.add_argument("--strategy", choices=list(STRATEGIES), help="стратегия")
    p.add_argument("--gamma", type=float, help="неприятие риска γ")
    p.add_argument("--fill-model", choices=["candle", "trades", "intensity"], help="модель исполнения")
    p.add_argument("--out", help="каталог для отчёта")
    p.add_argument(
        "-s", "--set", action="append", default=[], metavar="РАЗДЕЛ.КЛЮЧ=ЗНАЧЕНИЕ",
        help="любой параметр конфигурации, например -s execution.max_inventory=20",
    )


def build_config(args) -> SimConfig:
    cfg = SimConfig.load(args.config) if getattr(args, "config", None) else SimConfig()
    direct = {
        "data.source": getattr(args, "source", None),
        "data.secid": getattr(args, "secid", None),
        "data.board": getattr(args, "board", None),
        "data.start": getattr(args, "start", None),
        "data.end": getattr(args, "end", None),
        "strategy.name": getattr(args, "strategy", None),
        "strategy.gamma": getattr(args, "gamma", None),
        "execution.fill_model": getattr(args, "fill_model", None),
        "report.out_dir": getattr(args, "out", None),
    }
    for key, value in direct.items():
        if value is not None:
            cfg.set(key, value)
    for item in getattr(args, "set", []) or []:
        key, sep, value = item.partition("=")
        if not sep:
            raise SystemExit(f"Ожидается РАЗДЕЛ.КЛЮЧ=ЗНАЧЕНИЕ, получено: {item}")
        cfg.set(key.strip(), value.strip())
    return cfg


def _load(cfg: SimConfig):
    def progress(day, n):
        print(f"  {day:%Y-%m-%d}: {n} свечей", file=sys.stderr)

    md, t0, t1 = load_market_data(cfg, progress if cfg.data.source == "moex" else None)
    print(md.summary())
    return md, t0, t1


def _strategy(cfg: SimConfig, **over):
    params = {**vars(cfg.strategy), **over}
    name = params.pop("name")
    return make_strategy(name, **params)


def _run(cfg: SimConfig, md, t0, t1, strategy=None):
    return run_backtest(
        md, strategy or _strategy(cfg), cfg.execution, cfg.calibration,
        cfg.sessions.use, cfg.sessions.custom, t0, t1,
    )


# ------------------------------------------------------------------ команды
def cmd_fetch(args) -> None:
    cfg = build_config(args)
    cfg.data.source = "moex"
    md, _, _ = _load(cfg)
    if args.csv:
        Path(args.csv).parent.mkdir(parents=True, exist_ok=True)
        md.candles.to_csv(args.csv)
        print(f"Свечи сохранены: {args.csv}")


def cmd_calibrate(args) -> None:
    from mmsim.execution import build_grid
    from mmsim.report import _save, plot_intensity
    from mmsim.sessions import resolve_sessions

    cfg = build_config(args)
    md, t0, t1 = _load(cfg)
    sess = resolve_sessions(cfg.sessions.use, cfg.sessions.custom)
    grid = build_grid(md, sess, cfg.execution.requote_seconds, use_trades=cfg.execution.fill_model == "trades")
    bars = grid.bars
    if t0 or t1:
        days = pd.DatetimeIndex(bars.index).normalize()
        mask = np.ones(len(bars), dtype=bool)
        if t0:
            mask &= days >= pd.Timestamp(t0)
        if t1:
            mask &= days <= pd.Timestamp(t1)
        bars = bars[mask]
    tick = md.instrument.tick_size
    p = calibrate(bars, grid.step_seconds, tick, bars["session_id"].to_numpy())
    session_sec = sum(s.seconds for s in sess)
    print("\nПараметры модели (шаг %g с):" % grid.step_seconds)
    print("  " + p.describe(float(bars["close"].mean()), session_sec))
    tbl = intensity_table(bars, grid.step_seconds, tick, bars["session_id"].to_numpy())
    show = tbl[(tbl["p_hit"] > 0.005) & (tbl["p_hit"] < 0.995)].copy()
    show["delta_ticks"] = show["delta"] / tick
    print("\nЭмпирическая интенсивность:")
    print(show[["delta_ticks", "delta", "p_hit", "lambda"]].to_string(index=False, float_format=lambda v: f"{v:.5g}"))
    if cfg.report.out_dir:
        out = Path(cfg.report.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        _save(plot_intensity(tbl, p.A, p.k, tick), out, "intensity")
        tbl.to_csv(out / "intensity.csv", index=False)
        print(f"\nГрафик: {out / 'intensity.png'}")


def cmd_run(args) -> None:
    from mmsim.report import write_report

    cfg = build_config(args)
    md, t0, t1 = _load(cfg)
    res = _run(cfg, md, t0, t1)
    print(f"\n{res.strategy}\n" + format_metrics(res.metrics))
    path = write_report(res, cfg.report.out_dir, cfg.report.plot_day)
    print(f"\nОтчёт: {path}")


def _parse_strategy_spec(spec: str) -> tuple[str, dict]:
    """``as:gamma=0.05,horizon=rolling`` → ("as", {...})."""
    name, _, rest = spec.partition(":")
    params = {}
    for kv in filter(None, rest.split(",")):
        k, _, v = kv.partition("=")
        try:
            params[k.strip()] = int(v) if v.strip().lstrip("-").isdigit() else float(v)
        except ValueError:
            params[k.strip()] = v.strip()
    return name.strip(), params


def cmd_compare(args) -> None:
    from mmsim.report import write_compare_report

    cfg = build_config(args)
    md, t0, t1 = _load(cfg)
    specs = args.strategies or ["as", "as_symmetric", "glft", "glft_exact", "fixed"]
    results = []
    for spec in specs:
        name, params = _parse_strategy_spec(spec)
        base = {k: v for k, v in vars(cfg.strategy).items() if k != "name"}
        strat = make_strategy(name, **{**base, **params})
        print(f"  … {strat.label()}", file=sys.stderr)
        results.append(_run(cfg, md, t0, t1, strat))
    mf = metrics_frame(results)

    def fmt(v):
        if isinstance(v, float) and v.is_integer() and abs(v) < 1e6:
            return f"{int(v):,}".replace(",", " ")
        return f"{v:,.2f}".replace(",", " ") if isinstance(v, float) else str(v)

    with pd.option_context("display.width", 250, "display.max_columns", 20):
        print("\n" + mf.map(fmt).to_string())
    path = write_compare_report(results, cfg.report.out_dir)
    print(f"\nОтчёт: {path}")


def cmd_sweep(args) -> None:
    from mmsim.report import write_sweep_report

    cfg = build_config(args)
    md, t0, t1 = _load(cfg)
    rows = []
    res = None
    for raw in filter(None, (x.strip() for x in args.values.split(","))):
        c = copy.deepcopy(cfg)
        c.set(args.param, raw)
        v = float(raw)
        res = _run(c, md, t0, t1)
        m = res.metrics
        rows.append({args.param: v, **{k: m[k] for k in m if k != "strategy"}})
        pnl = f"{m['pnl_total']:,.0f}".replace(",", " ")
        print(f"  {args.param}={v:g}: P&L {pnl}, Шарп {m['sharpe_annual']:.2f}, "
              f"ст.откл. позиции {m['inventory_std']:.2f}", file=sys.stderr)
    table = pd.DataFrame(rows)
    path = write_sweep_report(table, args.param, res, cfg.report.out_dir)
    print(f"\nОтчёт: {path}")


def cmd_paper(args) -> None:
    from mmsim import paper
    from mmsim.report import _save, plot_paper

    setup = paper.PaperSetup(n_paths=args.paths, seed=args.seed)
    tbl = paper.table(setup=setup)
    labels = {"inventory": "inventory", "symmetric": "symmetric"}
    show = tbl.assign(strategy=tbl["strategy"].map(labels)).round(3)
    print("Эксперимент Авельянеды–Стойкова (2008): s=100, T=1, σ=2, dt=0.005, A=140, k=1.5,"
          f" {setup.n_paths} траекторий\n")
    print(show.to_string(index=False))
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        tbl.to_csv(out / "paper_table.csv", index=False)
        inv, _, path = paper.simulate(0.1, "inventory", setup, keep_path=True)
        sym, _ = paper.simulate(0.1, "symmetric", setup)
        _save(plot_paper(tbl, {"inventory": inv, "symmetric": sym}, path), out, "paper")
        print(f"\nТаблица и график: {out}")


def cmd_synth(args) -> None:
    from mmsim.data.synthetic import SyntheticConfig, generate

    md = generate(SyntheticConfig(secid=args.secid, days=args.days, start_date=args.start, seed=args.seed))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    md.candles.to_csv(out / f"{args.secid}_candles_1m.csv")
    md.trades.to_csv(out / f"{args.secid}_trades.csv")
    print(md.summary())
    print(f"Сохранено в {out}")


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mmsim", description="Симулятор маркет-мейкинга Авельянеды–Стойкова на данных MOEX")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("fetch", help="скачать данные MOEX ISS в кэш")
    _common(s)
    s.add_argument("--csv", help="дополнительно сохранить свечи в CSV")
    s.set_defaults(func=cmd_fetch)

    s = sub.add_parser("calibrate", help="оценить σ, A, k")
    _common(s)
    s.set_defaults(func=cmd_calibrate)

    s = sub.add_parser("run", help="бэктест стратегии")
    _common(s)
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("compare", help="сравнить стратегии")
    _common(s)
    s.add_argument("strategies", nargs="*", help="спецификации вида as:gamma=0.05,horizon=rolling glft fixed:half_spread_ticks=8")
    s.set_defaults(func=cmd_compare)

    s = sub.add_parser("sweep", help="перебор параметра")
    _common(s)
    s.add_argument("--param", default="strategy.gamma", help="параметр, например strategy.gamma")
    s.add_argument("--values", required=True, help="значения через запятую")
    s.set_defaults(func=cmd_sweep)

    s = sub.add_parser("paper", help="эксперимент из статьи AS (2008)")
    s.add_argument("--paths", type=int, default=1000)
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--out", help="каталог для таблицы и графика")
    s.set_defaults(func=cmd_paper)

    s = sub.add_parser("synth", help="синтетические данные в CSV")
    s.add_argument("--secid", default="SBER")
    s.add_argument("--days", type=int, default=10)
    s.add_argument("--from", dest="start", default="2025-09-01")
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("--out", default="data/synthetic")
    s.set_defaults(func=cmd_synth)
    return p


def main(argv=None) -> int:
    args = make_parser().parse_args(argv)
    try:
        args.func(args)
    except MoexUnavailable as err:
        print(f"Ошибка: {err}", file=sys.stderr)
        return 2
    except ValueError as err:
        print(f"Ошибка: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
