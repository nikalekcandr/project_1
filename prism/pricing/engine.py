"""Маршрутизатор оценки: выбор движка по структуре сделки.

auto: аналитика, если структура ею покрывается; иначе — дерево Hull-White
для бермудских процентных структур; иначе — Монте-Карло. Выбор и причина
перехода фиксируются в результате.
"""
from __future__ import annotations

import time

from ..core.provenance import InputTracker
from ..instruments.schema import EarlyTerminationMod, ExerciseMod, Trade
from ..payoff.compile import compile_trade
from .analytic import AnalyticEngine, NotAnalytic
from .result import PricingResult


def _mc_config(trade: Trade, overrides: dict | None = None):
    from ..models.mc.engine import MCConfig
    m = trade.model
    vm = {"auto": "local_vol", "local_vol": "local_vol", "black": "black", "vanna_volga": "local_vol"}[m.vol_model]
    cfg = MCConfig(paths=m.paths, seed=m.seed, antithetic=m.antithetic, vol_model=vm, steps_per_year=m.time_steps_per_year,
                   target_stderr=None)
    for k, v in (overrides or {}).items():
        setattr(cfg, k, v)
    return cfg


def _is_bermudan_rates(cp) -> bool:
    mods = cp.modifiers
    if len(mods) != 1 or not isinstance(mods[0], (EarlyTerminationMod, ExerciseMod)):
        return False
    for leg in cp.legs:
        if not leg.is_rate or leg.modifiers:
            return False
        if any(c.kind not in ("fixed", "float") or c.modifiers for c in leg.components):
            return False
    return True


def price_trade(trade: Trade, ctx, *, engine: str | None = None, mc_overrides: dict | None = None,
                tracker: InputTracker | None = None, crosscheck: bool = False) -> PricingResult:
    t0 = time.perf_counter()
    tr = tracker or InputTracker()
    ctx = ctx.with_tracker(tr)
    cp = compile_trade(trade, ctx.ref_date)
    choice = engine or trade.model.engine
    fallback = None
    res: PricingResult | None = None
    base = dict(trade_id=trade.identification.trade_id, product=trade.product, currency=trade.report_currency)
    if choice in ("auto", "analytic"):
        try:
            ar = AnalyticEngine(ctx, trade.model.vol_model).price(trade, cp)
            methods = sorted({i.get("method", "") for i in ar.items if i.get("method")})
            res = PricingResult(value=ar.value, engine="actuarial" if ar.measure == "historical" else "analytic",
                                model="; ".join(methods), measure=ar.measure, items=ar.items, checks=ar.checks,
                                notes=ar.notes, **base)
        except NotAnalytic as e:
            if choice == "analytic":
                raise
            fallback = str(e)
    if res is None and choice in ("auto", "tree") and _is_bermudan_rates(cp):
        from ..models.rates.hw_tree import price_bermudan
        tr_res = price_bermudan(trade, cp, ctx)
        res = PricingResult(value=tr_res["value"], engine="tree", model=tr_res["model"], items=tr_res["items"],
                            exercise=tr_res.get("exercise", {}), **base)
    if res is None:
        from ..models.mc.engine import MCEngine
        cfg = _mc_config(trade, mc_overrides)
        mr = MCEngine(ctx, cfg).price(trade, cp)
        res = PricingResult(value=mr.value, engine="mc",
                            model=f"Монте-Карло: {('локальная волатильность (Дюпир)' if cfg.vol_model == 'local_vol' else 'Блэк с временной структурой')}"
                                  f", {mr.diagnostics.get('rate_model')}",
                            cashflows=mr.flows,
                            mc={"stderr": mr.stderr, "ci95": list(mr.ci95), "paths": mr.n_paths, "seed": mr.seed,
                                "convergence": mr.convergence, "diagnostics": {k: v for k, v in mr.diagnostics.items()
                                                                               if k != "martingale_corrections"}},
                            notes=mr.notes, exercise=mr.exercise, **base)
    res.fallback_reason = fallback
    if crosscheck:
        _crosschecks(res, trade, cp, ctx)
    res.flags = list(cp.flags)
    res.inputs = tr.to_list()
    res.warnings = list(tr.warnings)
    if ctx.snapshot.is_demo:
        res.warnings.insert(0, "ДЕМО-снапшот: рыночные данные иллюстративные, результат не является оценкой")
    if any(f for f in cp.flags):
        res.warnings.extend(f for f in cp.flags if f not in res.warnings)
    res.elapsed_ms = (time.perf_counter() - t0) * 1000
    return res


def quick_value(trade: Trade, ctx, engine: str | None = None, mc_overrides: dict | None = None) -> float:
    """Только число (для греков и сценариев): без сбора входов."""
    return price_trade(trade, ctx, engine=engine, mc_overrides=mc_overrides).value


def _crosschecks(res: PricingResult, trade: Trade, cp, ctx) -> None:
    from .crosscheck import lv_pde_value, parity_checks
    try:
        res.checks.extend(parity_checks(trade, cp, ctx))
    except Exception as e:  # pragma: no cover — проверка не должна ломать оценку
        res.checks.append({"check": "put_call_parity", "ok": False, "detail": f"не выполнена: {e}"})
    for it in res.items:
        if "vanilla" in it and "unit_pv" in it:
            ok = it["unit_pv"] <= it["vanilla"] * (1 + 1e-9) + 1e-12
            res.checks.append({"check": "barrier_le_vanilla", "ok": bool(ok),
                               "detail": f"период {it.get('period')}: барьерный {it['unit_pv']:.6g} ≤ ваниль {it['vanilla']:.6g}"})
    if res.engine == "analytic" and any("vanna-volga" in (i.get("method") or "") for i in res.items):
        try:
            lv = lv_pde_value(trade, cp, ctx)
        except Exception as e:  # pragma: no cover
            lv = None
            res.checks.append({"check": "model_vv_vs_lv", "ok": False, "detail": f"не выполнена: {e}"})
        if lv is not None:
            diff = res.value - lv["value"]
            res.checks.append({"check": "model_vv_vs_lv", "ok": True, "vv": res.value, "lv_pde": lv["value"],
                               "diff": diff, "detail": f"VV − LV(PDE) = {diff:,.0f} {res.currency}: модельная неопределённость "
                                                       f"барьерной части"})
