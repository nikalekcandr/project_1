"""Набор валидации: арбитражные проверки, бенчмарки, регрессия.

* арбитраж на каждом построении: DF > 0 и убывают, форварды конечны и не
  ниже минимума, butterfly/calendar по поверхностям, put-call паритет,
  барьер ≤ ванили, KI + KO = ваниль, монотонность по страйку и сроку;
* бенчмарки: закрытые формулы, МК против аналитики, сверка с QuantLib;
* репрайсинг калибровочных инструментов: ≤ 0.5 б.п. по ставкам;
* устойчивость при высоких ставках (до 30%) и резких сдвигах;
* регрессия: эталонные сделки с зафиксированными ценами на привязанном
  снапшоте; отклонение выше порога требует явного подтверждения.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

GOLDEN_PATH = Path(__file__).resolve().parents[2] / "tests" / "golden" / "golden.json"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    group: str = ""


@dataclass
class SuiteResult:
    checks: list[Check] = field(default_factory=list)

    def add(self, group: str, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append(Check(name, bool(ok), detail, group))

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)


def arbitrage_checks(ctx, res: SuiteResult) -> None:
    for cid in ctx.config["curves"]:
        try:
            rep = ctx.curve_fit_report(cid)
        except Exception as e:  # pragma: no cover
            res.add("кривые", f"{cid}: построение", False, str(e))
            continue
        c = ctx.curve(cid)
        ts = np.linspace(0.01, 30, 600)
        dfs = c.df(ts)
        res.add("кривые", f"{cid}: DF > 0 и убывают", bool(np.all(dfs > 0) and np.all(np.diff(dfs) < 0)),
                f"min DF {dfs.min():.4f}")
        f = c.inst_fwd(ts)
        res.add("кривые", f"{cid}: форварды конечны и ≥ −5%", bool(np.all(np.isfinite(f)) and f.min() > -0.05), f"min {f.min():.4%}")
        res.add("кривые", f"{cid}: репрайсинг ≤ 0.5 б.п.", rep["max_error_bp"] <= 0.5, f"{rep['max_error_bp']:.3f} б.п.")
    for pair in ctx.config.get("fx_vol", {}):
        try:
            s = ctx.fx_vol(pair)
        except Exception as e:  # pragma: no cover
            res.add("волатильность", f"{pair}: построение", False, str(e))
            continue
        arb = s.check_arbitrage()
        bad = [a for a in arb if not a["ok"]]
        res.add("волатильность", f"{pair}: butterfly/calendar/форвардная дисперсия", not bad,
                "; ".join(f"{a['check']} {a['expiry']}: {a['detail']}" for a in bad) or f"{len(arb)} проверок")
        # монотонность цены колла по страйку и по сроку
        from ..models.analytic.black import black
        T = 0.5
        F = s.forward(T)
        Ks = F * np.linspace(0.7, 1.4, 40)
        c = np.array([float(black(F, K, T, s.vol(K, T), 1.0, 1)) for K in Ks])
        res.add("волатильность", f"{pair}: колл убывает и выпукл по страйку", bool(np.all(np.diff(c) < 0) and np.all(np.diff(c, 2) > -1e-10)))
        Ts = np.linspace(0.05, 1.0, 20)
        cT = [float(black(s.forward(t), F, t, s.vol(F, t), 1.0, 1)) for t in Ts]
        res.add("волатильность", f"{pair}: ATM-колл растёт по сроку", bool(np.all(np.diff(cT) > 0)))


def parity_and_barrier_checks(ctx, res: SuiteResult) -> None:
    from ..instruments.templates import build
    from ..pricing.engine import price_trade
    from ..instruments.templates import render
    from ..instruments.schema import load_trade
    vd = render("fx_barrier", {"strike": 88.0})
    vd["legs"][0]["components"][0]["modifiers"] = []
    van = price_trade(load_trade(vd), ctx).value      # та же сделка без барьера
    for direction, level in (("up", 98.0), ("down", 76.0)):
        ko = price_trade(build("fx_barrier", {"strike": 88.0, "barrier": level, "direction": direction, "kind": "out"}), ctx).value
        ki = price_trade(build("fx_barrier", {"strike": 88.0, "barrier": level, "direction": direction, "kind": "in"}), ctx).value
        res.add("паритеты", f"KI + KO = ваниль ({direction})", abs(ki + ko - van) < 1e-6 * abs(van) + 1e-6, f"{ki + ko:,.2f} vs {van:,.2f}")
        res.add("паритеты", f"KO ≤ ваниль ({direction})", ko <= van * (1 + 1e-9))
    # монотонность по страйку для ванили
    vals = [price_trade(build("fx_vanilla", {"strike": k}), ctx).value for k in (80, 85, 90, 95)]
    res.add("паритеты", "колл убывает по страйку (оценка сделки)", all(a > b for a, b in zip(vals, vals[1:])))
    # put-call паритет на сделках
    call = price_trade(build("fx_vanilla", {"option": "call", "strike": 88.0}), ctx).value
    put = price_trade(build("fx_vanilla", {"option": "put", "strike": 88.0}), ctx).value
    res.add("паритеты", "C − P = форвард (те же даты)", abs((call - put) - _fwd_same_dates(ctx)) < 1e-6 * abs(call) + 1.0,
            f"C−P {call - put:,.2f}")


def _fwd_same_dates(ctx) -> float:
    from ..instruments.templates import render
    from ..instruments.schema import load_trade
    from ..pricing.engine import price_trade
    d = render("fx_vanilla", {"option": "call", "strike": 88.0})
    d["legs"][0]["components"] = [{"kind": "forward", "strike": 88.0}]
    return price_trade(load_trade(d), ctx).value


def quantlib_benchmarks(res: SuiteResult) -> None:
    try:
        import QuantLib as ql
    except ImportError:
        res.add("QuantLib", "сверка с QuantLib", True, "QuantLib не установлен — пропущено")
        return
    from ..models.analytic.barriers import barrier_price, double_barrier_ko, double_no_touch
    from ..models.analytic.black import black, bachelier
    from ..models.analytic.spread import kirk
    today = ql.Date(15, 10, 2026)
    ql.Settings.instance().evaluationDate = today
    dc = ql.Actual365Fixed()
    for r, q, vol in ((0.16, 0.035, 0.17), (0.30, 0.04, 0.25), (0.05, 0.10, 0.12)):
        spot = ql.QuoteHandle(ql.SimpleQuote(82.5))
        rts = ql.YieldTermStructureHandle(ql.FlatForward(today, r, dc, ql.Continuous))
        qts = ql.YieldTermStructureHandle(ql.FlatForward(today, q, dc, ql.Continuous))
        vts = ql.BlackVolTermStructureHandle(ql.BlackConstantVol(today, ql.NullCalendar(), vol, dc))
        proc = ql.BlackScholesMertonProcess(spot, qts, rts, vts)
        T = 1.0
        exd = today + 365
        err = 0.0
        for cp, qlt in ((1, ql.Option.Call), (-1, ql.Option.Put)):
            for X in (75.0, 85.0, 95.0):
                o = ql.VanillaOption(ql.PlainVanillaPayoff(qlt, X), ql.EuropeanExercise(exd))
                o.setPricingEngine(ql.AnalyticEuropeanEngine(proc))
                F = 82.5 * math.exp((r - q) * T)
                err = max(err, abs(o.NPV() - float(black(F, X, T, vol, math.exp(-r * T), cp))))
                for H, d_, k_, qbt in ((70.0, "down", "out", ql.Barrier.DownOut), (70.0, "down", "in", ql.Barrier.DownIn),
                                       (100.0, "up", "out", ql.Barrier.UpOut), (100.0, "up", "in", ql.Barrier.UpIn)):
                    for reb in (0.0, 1.5):
                        b = ql.BarrierOption(qbt, H, reb, ql.PlainVanillaPayoff(qlt, X), ql.EuropeanExercise(exd))
                        b.setPricingEngine(ql.AnalyticBarrierEngine(proc))
                        err = max(err, abs(b.NPV() - barrier_price(82.5, X, H, T, r, q, vol, cp, d_, k_, reb, True)))
                db = ql.DoubleBarrierOption(ql.DoubleBarrier.KnockOut, 65.0, 105.0, 0.0, ql.PlainVanillaPayoff(qlt, X), ql.EuropeanExercise(exd))
                db.setPricingEngine(ql.AnalyticDoubleBarrierEngine(proc))
                err = max(err, abs(db.NPV() - double_barrier_ko(82.5, X, 65.0, 105.0, T, r, q, vol, cp)))
        dnt = ql.DoubleBarrierOption(ql.DoubleBarrier.KnockOut, 65.0, 105.0, 0.0, ql.CashOrNothingPayoff(ql.Option.Call, 0.0, 1.0),
                                     ql.EuropeanExercise(exd))
        dnt.setPricingEngine(ql.AnalyticDoubleBarrierBinaryEngine(proc))
        err = max(err, abs(dnt.NPV() - double_no_touch(82.5, 65.0, 105.0, T, r, q, vol)))
        res.add("QuantLib", f"GK, барьеры (8 типов × ребейт), двойной барьер, DNT при r={r:.0%}", err < 1e-7, f"макс. расхождение {err:.2e}")
    # Башелье
    from scipy.special import ndtr
    F, K, T, sn = 0.15, 0.16, 1.5, 0.02
    d = (F - K) / (sn * math.sqrt(T))
    ref = (F - K) * ndtr(d) + sn * math.sqrt(T) * math.exp(-0.5 * d * d) / math.sqrt(2 * math.pi)
    res.add("закрытые формулы", "Башелье", abs(float(bachelier(F, K, T, sn)) - ref) < 1e-14)
    # Кирк (QuantLib: BasketOption + SpreadBasketPayoff + KirkEngine)
    def _proc(S, v):
        return ql.BlackScholesMertonProcess(ql.QuoteHandle(ql.SimpleQuote(S)), ql.YieldTermStructureHandle(ql.FlatForward(today, 0.0, dc)),
                                            ql.YieldTermStructureHandle(ql.FlatForward(today, 0.04, dc)),
                                            ql.BlackVolTermStructureHandle(ql.BlackConstantVol(today, ql.NullCalendar(), v, dc)))
    opt = ql.BasketOption(ql.SpreadBasketPayoff(ql.PlainVanillaPayoff(ql.Option.Call, 10.0)), ql.EuropeanExercise(today + 365))
    opt.setPricingEngine(ql.KirkEngine(_proc(68.0, 0.32), _proc(56.5, 0.36), 0.9))
    g = math.exp(0.04)
    mine = kirk(68.0 * g, 56.5 * g, 10.0, 1.0, 0.32, 0.36, 0.9, math.exp(-0.04))
    res.add("QuantLib", "Кирк (спред-опцион)", abs(opt.NPV() - mine) < 1e-8, f"{opt.NPV():.8f} vs {mine:.8f}")
    # бермудский свопцион: дерево Hull-White
    from ..models.rates.hw_tree import HWTree
    for r in (0.14, 0.30):
        curve = ql.YieldTermStructureHandle(ql.FlatForward(today, r, dc, ql.Continuous))
        cal = ql.NullCalendar()
        sched = ql.Schedule(today + ql.Period(1, ql.Years), today + ql.Period(5, ql.Years), ql.Period(ql.Annual), cal, ql.Unadjusted,
                            ql.Unadjusted, ql.DateGeneration.Forward, False)
        K = r + 0.005
        idx = ql.IborIndex("X", ql.Period(1, ql.Years), 0, ql.RUBCurrency(), cal, ql.Unadjusted, False, dc, curve)
        swap = ql.VanillaSwap(ql.VanillaSwap.Payer, 1.0, sched, K, dc, sched, idx, 0.0, dc)
        ex = [sched[i] for i in range(4)]
        sw = ql.Swaption(swap, ql.BermudanExercise(ex))
        sw.setPricingEngine(ql.TreeSwaptionEngine(ql.HullWhite(curve, 0.1, 0.012), 400))
        tt = lambda x: dc.yearFraction(today, x)
        flows = []
        for i in range(len(sched) - 1):
            s_, e_ = sched[i], sched[i + 1]
            flows += [(tt(e_), -K * dc.yearFraction(s_, e_), tt(s_)), (tt(s_), 1.0, tt(s_)), (tt(e_), -1.0, tt(s_))]
        tree = HWTree(lambda x, rr=r: -rr * np.asarray(x), 0.1, 0.012, tt(sched[len(sched) - 1]), 100)
        snap = lambda x: int(round(x / tree.dt))
        cash = {}
        for t_, a_, st in flows:
            cash.setdefault(snap(t_), []).append((a_ * math.exp(-r * t_) / math.exp(-r * tree.times[snap(t_)]), st))
        exs = {snap(tt(d_)): tt(d_) for d_ in ex}
        U = np.zeros(len(tree.js))
        W = np.zeros(len(tree.js))
        for i in range(tree.N, -1, -1):
            e = exs.get(i)
            later = []
            for a_, st in cash.get(i, []):
                if e is not None and st < e - 1e-9:
                    later.append(a_)
                else:
                    U += a_
            if e is not None:
                W = np.maximum(U, W)
            for a_ in later:
                U += a_
            if i > 0:
                U = tree.step_back(U, i - 1)
                W = tree.step_back(W, i - 1)
        mine = float(W[tree.jmax])
        res.add("QuantLib", f"бермудский свопцион, дерево HW (r={r:.0%})", abs(mine - sw.NPV()) < 2e-3 * sw.NPV() + 1e-6,
                f"{mine:.6f} vs QL {sw.NPV():.6f}")


def flat_smile_context(ctx):
    """Контекст на исправленном снапшоте с плоской улыбкой (RR = BF = 0) — для проверки численных методов."""
    from ..marketdata.context import MarketContext
    snap = ctx.snapshot
    changes = {}
    for q in snap.find("VOL."):
        parts = q.id.split(".")
        if len(parts) == 4 and parts[2] in ("RR25", "BF25", "RR10", "BF10"):
            changes[q.id] = q.with_value(0.0, note="валидация: плоская улыбка")
    return MarketContext(snap.derive(changes, "валидация численных методов на плоской улыбке"), ctx.config)


def mc_vs_analytic(ctx, res: SuiteResult, paths: int = 40000) -> None:
    """МК против аналитики на одинаковых модельных допущениях (плоская улыбка);
    на реальной улыбке расхождение — модельное и выводится как информация."""
    from ..instruments.templates import build
    from ..pricing.engine import price_trade
    fctx = flat_smile_context(ctx)
    for tid, params in (("fx_vanilla", {"strike": 88.0}), ("fx_asian", {}), ("fx_forward", {}),
                        ("fx_barrier", {}), ("fx_touch", {})):
        tr = build(tid, params)
        a = price_trade(tr, fctx, engine="analytic").value
        m = price_trade(tr, fctx, engine="mc", mc_overrides={"paths": paths, "vol_model": "black"})
        z = abs(m.value - a) / max(m.mc["stderr"], 1e-9)
        res.add("МК против аналитики", f"{tid} (плоская улыбка): |МК − аналитика| ≤ 4σ",
                z <= 4.0 or abs(m.value - a) < 1e-6 * abs(a) + 1,
                f"аналитика {a:,.0f}, МК {m.value:,.0f} ± {m.mc['stderr']:,.0f} ({z:.1f}σ)")
    tr = build("fx_asian")
    a = price_trade(tr, ctx, engine="analytic").value
    m = price_trade(tr, ctx, engine="mc", mc_overrides={"paths": paths})
    res.add("МК против аналитики", "fx_asian на рыночной улыбке: модельное расхождение (информация)", True,
            f"моменты (вола на страйке) {a:,.0f} vs МК локальная вола {m.value:,.0f} ± {m.mc['stderr']:,.0f}: "
            f"{(m.value - a) / abs(a):+.2%}")


def high_rate_stability(res: SuiteResult) -> None:
    """Численная устойчивость на ставках до 30% и при резких сдвигах."""
    from ..models.analytic.barriers import barrier_price, double_barrier_ko
    from ..models.analytic.black import black
    from ..models.pde.fd1d import solve_pde
    ok = True
    worst = 0.0
    for r in (0.0, 0.16, 0.21, 0.30, 0.45):
        for q in (0.0, 0.05):
            fwd = lambda t, rr=r, qq=q: 82.5 * math.exp((rr - qq) * t)
            pde = solve_pde(lambda S: np.maximum(S - 90, 0), 82.5, 1.0, fwd=fwd, rate=lambda t, rr=r: rr,
                            vol=lambda t, x: np.full_like(x, 0.2), upper=110.0)["price"]
            an = barrier_price(82.5, 90, 110.0, 1.0, r, q, 0.2, 1, "up", "out")
            v = [an, pde, double_barrier_ko(82.5, 90, 60, 110, 1.0, r, q, 0.2, 1), float(black(fwd(1), 90, 1.0, 0.2, math.exp(-r), 1))]
            if not all(math.isfinite(x) and x >= 0 for x in v):
                ok = False
            worst = max(worst, abs(pde - an))
    res.add("устойчивость", "аналитика и PDE при ставках 0–45%", ok and worst < 2e-3, f"макс. |PDE − аналитика| {worst:.2e}")


def regression(ctx, res: SuiteResult, update: bool = False, tol_rel: float = 1e-8, reason: str = "") -> None:
    from ..instruments.templates import build
    from ..pricing.engine import price_trade
    ids = ["fx_forward", "ndf", "fx_vanilla", "fx_barrier", "fx_double_barrier", "fx_touch", "fx_dnt", "fx_collar", "fx_forward_extra",
           "fx_leveraged_forward", "fx_asian", "irs_keyrate", "ois_ruonia", "basis_swap", "cap_floor", "ir_collar", "swaption",
           "cancellable_swap", "zcis", "cds", "cln", "commodity_asian_option", "equity_option", "variance_swap", "weather_hdd",
           "fx_tarf", "fx_accumulator", "barrier_cap", "autocallable"]
    vals = {}
    for tid in ids:
        r = price_trade(build(tid), ctx, mc_overrides={"paths": 8000})
        vals[tid] = r.value
    if update or not GOLDEN_PATH.exists():
        if GOLDEN_PATH.exists() and not reason.strip():
            raise ValueError("обновление эталонов требует явной причины (--reason)")
        from datetime import datetime, timezone
        from ..version import code_version
        old = json.loads(GOLDEN_PATH.read_text(encoding="utf-8")) if GOLDEN_PATH.exists() else {}
        changed = {k: {"old": old.get("values", {}).get(k), "new": v} for k, v in vals.items()
                   if old.get("values", {}).get(k) is None or abs(v - old["values"][k]) > tol_rel * max(abs(old["values"][k]), 1.0)}
        history = list(old.get("history", []))
        history.append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "reason": reason or "первичная запись",
                        "code": code_version().get("source_hash"), "changed": changed})
        GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN_PATH.write_text(json.dumps({"snapshot": ctx.snapshot.id, "snapshot_hash": ctx.snapshot.content_hash,
                                           "mc_paths": 8000, "values": vals, "history": history}, ensure_ascii=False, indent=1),
                               encoding="utf-8")
        res.add("регрессия", "эталонные цены записаны", True, f"{GOLDEN_PATH}; изменено: {len(changed)}; причина: {reason}")
        return
    gold = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    if gold["snapshot_hash"] != ctx.snapshot.content_hash:
        res.add("регрессия", "снапшот эталона", False, "эталон привязан к другому снапшоту")
        return
    for tid, v in vals.items():
        g = gold["values"].get(tid)
        if g is None:
            res.add("регрессия", tid, False, "нет эталона — требуется явное подтверждение (--update-golden)")
            continue
        ok = abs(v - g) <= tol_rel * max(abs(g), 1.0)
        res.add("регрессия", tid, ok, "" if ok else f"эталон {g:,.4f}, сейчас {v:,.4f}: требуется подтверждение и запись причины")


def run_suite(quick: bool = False, verbose: bool = False, update_golden: bool = False, reason: str = "") -> bool:
    from ..marketdata.context import MarketContext
    from ..marketdata.demo import build_demo_snapshot
    res = SuiteResult()
    ctx = MarketContext(build_demo_snapshot())
    arbitrage_checks(ctx, res)
    parity_and_barrier_checks(ctx, res)
    quantlib_benchmarks(res)
    high_rate_stability(res)
    if not quick:
        mc_vs_analytic(ctx, res)
        regression(ctx, res, update=update_golden, reason=reason)
    if verbose:
        cur = None
        for c in res.checks:
            if c.group != cur:
                print(f"\n[{c.group}]")
                cur = c.group
            print(f"  {'✓' if c.ok else '✕'} {c.name}" + (f" — {c.detail}" if c.detail else ""))
        print(f"\nитого: {sum(c.ok for c in res.checks)}/{len(res.checks)} пройдено")
    return res.ok
