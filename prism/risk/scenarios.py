"""Сценарный анализ и стрессы.

* сетка спот × волатильность;
* параллельные и непараллельные сдвиги кривых (крутизна, «шок заседаний»);
* обязательный набор российских стрессов: ключевая ставка ±500 б.п.,
  курс рубля ±30%, одновременный сдвиг курса и ставки в одну сторону
  (ослабление рубля + рост ставки и наоборот).
"""
from __future__ import annotations

from typing import Any

import numpy as np

from ..instruments.schema import Trade
from ..marketdata.context import MarketContext, Shock
from ..pricing.engine import price_trade


def _pairs(trade: Trade) -> list[str]:
    return sorted({u.id for u in trade.underlyings.values() if u.asset_class == "fx" and u.id.endswith("RUB")})


def _asset_shocks(trade: Trade, rel: float) -> list[Shock]:
    out = []
    for u in trade.underlyings.values():
        if u.asset_class == "fx":
            out.append(Shock("fx", u.id, rel, "relative"))
        elif u.asset_class in ("equity", "commodity"):
            out.append(Shock(u.asset_class, u.id, rel, "relative"))
    return out


def _vol_shocks(trade: Trade, dv: float) -> list[Shock]:
    return [Shock("vol", u.id, dv) for u in trade.underlyings.values() if u.asset_class in ("fx", "equity", "commodity")]


def standard_stresses(trade: Trade) -> list[dict[str, Any]]:
    """Обязательный набор стрессов (российская реальность)."""
    fx_all = [Shock("fx", "*RUB", 0.30, "relative")]
    fx_down = [Shock("fx", "*RUB", -0.30, "relative")]
    # сдвиг рублёвых ставок сдвигает и форвардные пункты (покрытый паритет): F → F·exp(Δr·t)
    ks_up = [Shock("curve", "RUB.*", 0.05), Shock("fx_carry", "*RUB", -0.05)]
    ks_dn = [Shock("curve", "RUB.*", -0.05), Shock("fx_carry", "*RUB", 0.05)]
    ir_vol_up = [Shock("irvol", "*", 100.0)]
    return [
        {"id": "KS+500", "label": "Ключевая ставка +500 б.п. (все рублёвые кривые)", "shocks": ks_up},
        {"id": "KS-500", "label": "Ключевая ставка −500 б.п.", "shocks": ks_dn},
        {"id": "RUB-30", "label": "Ослабление рубля на 30% (валюта/RUB ×1.3)", "shocks": fx_all},
        {"id": "RUB+30", "label": "Укрепление рубля на 30% (валюта/RUB ×0.7)", "shocks": fx_down},
        {"id": "RUB-30&KS+500", "label": "Одновременно: рубль −30% и ставка +500 б.п.", "shocks": fx_all + ks_up},
        {"id": "RUB+30&KS-500", "label": "Одновременно: рубль +30% и ставка −500 б.п.", "shocks": fx_down + ks_dn},
        {"id": "MEETINGS+200", "label": "Шок ближайших заседаний: +200 б.п. на горизонте 6 мес., затухание к 2 годам",
         "shocks": [Shock("curve", "RUB.*", 0.0, fn=lambda t: 0.02 * np.clip(1.0 - np.maximum(np.asarray(t) - 0.5, 0) / 1.5, 0, 1))]},
        {"id": "STEEPENER", "label": "Крутизна: короткий конец −100 б.п., длинный +100 б.п.",
         "shocks": [Shock("curve", "RUB.*", 0.0, fn=lambda t: 0.01 * np.clip((np.asarray(t) - 2.0) / 3.0, -1, 1))]},
        {"id": "VOL+10", "label": "Волатильность +10 п. по всем базисам", "shocks": _vol_shocks(trade, 0.10) + ir_vol_up},
    ]


def run_stresses(trade: Trade, ctx: MarketContext, base_value: float | None = None, engine: str | None = None,
                 mc_overrides: dict | None = None) -> list[dict[str, Any]]:
    base = base_value if base_value is not None else price_trade(trade, ctx, engine=engine, mc_overrides=mc_overrides).value
    out = []
    for s in standard_stresses(trade):
        try:
            v = price_trade(trade, ctx.with_shocks(s["shocks"]), engine=engine, mc_overrides=mc_overrides).value
            out.append({"id": s["id"], "label": s["label"], "value": v, "pnl": v - base})
        except Exception as e:  # pragma: no cover
            out.append({"id": s["id"], "label": s["label"], "error": str(e)})
    return out


def spot_vol_grid(trade: Trade, ctx: MarketContext, spot_shifts=(-0.3, -0.2, -0.1, -0.05, 0.0, 0.05, 0.1, 0.2, 0.3),
                  vol_shifts=(-0.05, 0.0, 0.05, 0.10), base_value: float | None = None, engine: str | None = None,
                  mc_overrides: dict | None = None) -> dict[str, Any]:
    base = base_value if base_value is not None else price_trade(trade, ctx, engine=engine, mc_overrides=mc_overrides).value
    grid = []
    for dv in vol_shifts:
        row = []
        for ds in spot_shifts:
            sh = _asset_shocks(trade, ds) + _vol_shocks(trade, dv)
            v = price_trade(trade, ctx.with_shocks(sh), engine=engine, mc_overrides=mc_overrides).value
            row.append(v - base)
        grid.append(row)
    return {"spot_shifts": list(spot_shifts), "vol_shifts": list(vol_shifts), "pnl": grid, "base": base}


def barrier_profile(trade: Trade, ctx: MarketContext, proximity: float = 0.03, span: float = 0.08, n: int = 17,
                    engine: str | None = None) -> dict[str, Any] | None:
    """Профиль чувствительности в окрестности барьера.

    Поведение дельты и гаммы вблизи барьера нелинейно — показывается явно:
    цена, дельта и гамма на сетке спота вокруг барьера сейчас и ближе к
    экспирации. Предупреждение — если спот ближе ``proximity`` к барьеру.
    """
    from ..instruments.schema import BarrierMod
    levels = []
    for leg in trade.legs:
        mods = list(leg.modifiers) + [m for c in leg.components for m in c.modifiers]
        for m in mods:
            if isinstance(m, BarrierMod):
                for lv in (m.level, m.lower, m.upper):
                    if lv is not None:
                        levels.append(lv)
    for m in trade.modifiers:
        if isinstance(m, BarrierMod):
            for lv in (m.level, m.lower, m.upper):
                if lv is not None:
                    levels.append(lv)
    fx_specs = [u for u in trade.underlyings.values() if u.asset_class == "fx"]
    if not levels or not fx_specs:
        return None
    aid = fx_specs[0].id
    S = ctx.fx(aid).spot_value
    nearest = min(levels, key=lambda b: abs(b / S - 1))
    dist = abs(nearest / S - 1)
    warn = dist < proximity
    rel = np.linspace(nearest / S - 1 - span / 2, nearest / S - 1 + span / 2, n)
    days_left = (trade.maturity - ctx.ref_date).days
    horizons = [0] + ([int(days_left * 0.5), int(days_left * 0.9)] if days_left > 20 else [])
    curves = []
    for hd in horizons:
        c = ctx.rolled(hd) if hd else ctx
        vals = []
        for r in rel:
            try:
                vals.append(price_trade(trade, c.with_shocks([Shock("fx", aid, r, "relative")]), engine=engine,
                                        mc_overrides={"paths": 8000, "smoothing": 0.003}).value)
            except Exception:
                vals.append(float("nan"))
        spots = S * (1 + rel)
        v = np.array(vals)
        delta = np.gradient(v, spots)
        gamma = np.gradient(delta, spots)
        curves.append({"days_forward": hd, "spots": spots.tolist(), "values": v.tolist(), "delta": delta.tolist(),
                       "gamma": gamma.tolist()})
    return {"underlying": aid, "spot": S, "barrier": nearest, "distance": dist, "warning": warn,
            "message": (f"Спот {S:.4g} в {dist:.1%} от барьера {nearest:.4g}: дельта и гамма нелинейны"
                        if warn else f"Ближайший барьер {nearest:.4g} в {dist:.1%} от спота"), "profiles": curves}
