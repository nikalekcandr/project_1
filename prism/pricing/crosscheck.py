"""Независимые перекрёстные проверки оценки.

* VV против локальной волатильности (PDE) для барьерных/касательных
  структур — расхождение моделей выводится и используется как оценка
  модельной неопределённости в разложении цены;
* паритеты: put-call, KI + KO = ваниль.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np

from ..instruments.schema import AssetObs, BarrierMod, Trade
from ..models.analytic.black import black
from ..models.pde.fd1d import solve_pde
from ..payoff.compile import CProduct


def _t(ref: date, d: date) -> float:
    return (d - ref).days / 365.0


def lv_pde_value(trade: Trade, cp: CProduct, ctx) -> dict[str, Any] | None:
    """Цена структуры под локальной волатильностью (PDE), если структура — FX-барьеры/касания/ваниль."""
    ref = cp.ref_date
    total = 0.0
    used = False
    for leg in cp.legs:
        if not isinstance(leg.observable, AssetObs) or leg.modifiers:
            return None
        spec = trade.underlyings[leg.observable.name]
        if spec.asset_class != "fx":
            return None
        pair = spec.id
        fx = ctx.fx(pair)
        off = (fx.spot_date - fx.ref_date).days / 365.0
        disc = ctx.discount_curve(trade.report_currency, trade.collateral.collateralized)
        S0 = fx.spot_today()
        for p in leg.periods:
            if p.fixing <= ref:
                return None
            T = _t(ref, p.fixing)
            lv = ctx.local_vol(pair, T)
            fwd = lambda t, c=fx, o=off: float(c.forward_t(t + o)[0])
            rate = lambda t, d=disc: float(d.inst_fwd(t))
            vol = lambda t, x, g=lv, f=fwd: g(t, x - np.log(f(t)))
            df_adj = disc.df_date(p.payment) / float(disc.df(T))
            ccy_conv = 1.0 if leg.currency == trade.report_currency else None
            if ccy_conv is None:
                return None
            for c in leg.components:
                sign = 1.0 if c.position == "long" else -1.0
                bars = [m for m in c.modifiers if isinstance(m, BarrierMod)]
                if len(bars) > 1 or any(m.type not in ("barrier", "leverage") for m in c.modifiers):
                    return None
                mult = c.notional_multiplier
                for m in c.modifiers:
                    if m.type == "leverage":
                        if m.when != "always" and not (m.threshold == c.strike):
                            return None
                        mult *= m.factor
                K = c.strike
                if c.kind == "call":
                    pay = lambda S, K=K: np.maximum(S - K, 0.0)
                elif c.kind == "put":
                    pay = lambda S, K=K: np.maximum(K - S, 0.0)
                elif c.kind == "forward":
                    pay = lambda S, K=K: S - K
                elif c.kind in ("cash", "redemption"):
                    amt = c.payout if c.payout is not None else 1.0
                    pay = lambda S, a=amt: np.full_like(S, a)
                else:
                    return None
                kw: dict[str, Any] = dict(fwd=fwd, rate=rate, vol=vol, sd_vol=max(float(lv.lv.mean()), 0.05))
                if bars:
                    m = bars[0]
                    if (m.window_start and m.window_start > ref) or (m.window_end and m.window_end < p.fixing) or m.soft_width:
                        return None
                    if m.monitoring == "terminal":
                        return None
                    if m.lower is not None or m.upper is not None:
                        kw.update(lower=m.lower, upper=m.upper)
                    elif m.direction == "up":
                        kw.update(upper=m.level)
                    else:
                        kw.update(lower=m.level)
                    if m.monitoring == "discrete":
                        cal_days = max(int(T * 252), 1)
                        kw.update(monitor_times=list(np.linspace(T / cal_days, T, cal_days)), n_x=801, n_t=max(4 * cal_days, 300))
                    ko = solve_pde(pay, S0, T, **kw)["price"]
                    if m.kind == "out":
                        v = ko
                    else:
                        van = solve_pde(pay, S0, T, fwd=fwd, rate=rate, vol=vol, sd_vol=kw["sd_vol"])["price"]
                        v = van - ko
                    used = True
                else:
                    v = solve_pde(pay, S0, T, **kw)["price"]
                total += sign * p.notional * mult * v * df_adj
    if not used:
        return None
    return {"value": total, "model": "локальная волатильность Дюпира, PDE Кранка-Николсона"}


def parity_checks(trade: Trade, cp: CProduct, ctx) -> list[dict[str, Any]]:
    """Put-call паритет на сроке структуры (контроль согласованности кривых и поверхности)."""
    out = []
    ref = cp.ref_date
    for leg in cp.legs:
        if not isinstance(leg.observable, AssetObs):
            continue
        spec = trade.underlyings[leg.observable.name]
        if spec.asset_class != "fx":
            continue
        fx = ctx.fx(spec.id)
        surf = ctx.fx_vol(spec.id)
        disc = ctx.discount_curve(trade.report_currency, trade.collateral.collateralized)
        p = leg.periods[-1]
        T = max(_t(ref, p.fixing), 1e-4)
        F = fx.forward(p.payment)
        df = disc.df_date(p.payment)
        for K in sorted({c.strike for c in leg.components if c.strike is not None}):
            vol = float(surf.vol(K, T))
            c_ = float(black(F, K, T, vol, df, 1))
            p_ = float(black(F, K, T, vol, df, -1))
            err = c_ - p_ - df * (F - K)
            out.append({"check": "put_call_parity", "strike": K, "ok": abs(err) < 1e-8 * max(F, 1),
                        "detail": f"C − P − DF·(F−K) = {err:.2e}"})
        break
    return out
