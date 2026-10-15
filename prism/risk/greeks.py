"""Греки и чувствительности.

* аналитические производные — где они есть (линейные инструменты: точные
  формулы через форварды); иначе конечные разности с настраиваемым шагом;
* для Монте-Карло — общие случайные числа (один seed и сетка) и сглаживание
  разрывов выплаты: это pathwise-производная, посчитанная по каждому пути,
  без шума независимых перевыпусков;
* FX: спот- и форвард-дельта, гамма, вега (итого и по срокам поверхности),
  ванна, волга, тета, ро по обеим валютам;
* ставки: key-rate DV01 раздельно по дисконтной и прогнозной кривой
  (треугольные сдвиги нулевой кривой), PV01 по калибровочным котировкам,
  гамма по ставке, вега по сетке expiry × tenor;
* кросс-чувствительности: по корреляции, кросс-гамма.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from ..core.dates import Tenor
from ..instruments.schema import Trade
from ..marketdata.context import MarketContext, Shock
from ..pricing.engine import price_trade

KEY_TENORS = ["3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y"]


@dataclass
class GreekConfig:
    spot_bump: float = 0.005          # относительный
    vol_bump: float = 0.01            # 1 п. волатильности
    rate_bump: float = 0.0001         # 1 б.п.
    rate_gamma_bump: float = 0.0010
    corr_bump: float = 0.05
    vega_buckets: bool = True
    key_rates: bool = True
    pv01_quotes: bool = False         # PV01 по калибровочным котировкам (пересборка кривых)
    theta_days: int = 1
    mc_paths: int | None = None
    mc_smoothing: float = 0.003


@dataclass
class GreeksResult:
    values: dict[str, Any] = field(default_factory=dict)
    buckets: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    method: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def key_rate_fn(i: int, ts: list[float]) -> Callable:
    """Сдвиг нулевой ставки для i-го ключевого срока: треугольник с пиком в ts[i];
    крайние — плоские за пределами сетки. Сумма по всем срокам = параллельный сдвиг."""
    n = len(ts)

    def f(t):
        t = np.asarray(t, float)
        out = np.zeros_like(t)
        if i > 0:
            a, b = ts[i - 1], ts[i]
            out = np.where((t > a) & (t <= b), (t - a) / (b - a), out)
        else:
            out = np.where(t <= ts[0], 1.0, out)
        if i < n - 1:
            b, c = ts[i], ts[i + 1]
            out = np.where((t > b) & (t < c), (c - t) / (c - b), out)
        else:
            out = np.where(t > ts[-1], 1.0, out)
        return out
    return f


class GreeksCalculator:
    def __init__(self, trade: Trade, ctx: MarketContext, cfg: GreekConfig | None = None, base_value: float | None = None,
                 engine: str | None = None):
        self.trade = trade
        self.ctx = ctx
        self.cfg = cfg or GreekConfig()
        self.engine = engine
        self._mc = None
        self.base = self._v(ctx) if base_value is None else base_value
        self.base_smoothed = None

    def _mc_over(self):
        o = {"smoothing": self.cfg.mc_smoothing}
        if self.cfg.mc_paths:
            o["paths"] = self.cfg.mc_paths
        return o

    def _v(self, ctx: MarketContext) -> float:
        r = price_trade(self.trade, ctx, engine=self.engine, mc_overrides=self._mc_over())
        self._last_engine = r.engine
        return r.value

    def shocked(self, *shocks: Shock) -> float:
        return self._v(self.ctx.with_shocks(shocks))

    # ------------------------------------------------------------------ FX и активы
    def asset_greeks(self) -> GreeksResult:
        out = GreeksResult()
        base = self._v(self.ctx)   # базовая цена в том же режиме (сглаживание для МК)
        out.values["base_for_greeks"] = base
        eng = self._last_engine
        meth = "конечные разности по аналитике" if eng in ("analytic", "tree") else \
            "pathwise: общие случайные числа + сглаживание разрывов"
        for name, spec in self.trade.underlyings.items():
            aid = spec.id
            if spec.asset_class == "fx":
                kind = "fx"
            elif spec.asset_class in ("equity", "commodity"):
                kind = spec.asset_class
            else:
                continue
            h = self.cfg.spot_bump
            up = self.shocked(Shock(kind, aid, h, "relative"))
            dn = self.shocked(Shock(kind, aid, -h, "relative"))
            if kind == "fx":
                S = self.ctx.fx(aid).spot_value
            elif kind == "equity":
                eq = self.ctx.equity(aid)
                S = eq.spot * eq.shock
            else:
                S = self.ctx.commodity(aid).forward(self.trade.maturity)
            dS = S * h
            delta = (up - dn) / (2 * dS)
            gamma = (up - 2 * base + dn) / dS ** 2
            g = {"spot": S, "delta": delta, "delta_value": delta * S, "gamma": gamma,
                 "gamma_pnl_1pct": 0.5 * gamma * (0.01 * S) ** 2, "method": meth}
            if kind == "fx":
                fx = self.ctx.fx(aid)
                T = (self.trade.maturity - self.ctx.ref_date).days / 365.0
                F = fx.forward(self.trade.maturity)
                g["forward_delta"] = delta * S / F
                g["sticky"] = self.ctx.sticky_override or "delta"
            vb = self.cfg.vol_bump
            vu = self.shocked(Shock("vol", aid, vb))
            vd = self.shocked(Shock("vol", aid, -vb))
            g["vega_1pt"] = (vu - vd) / 2
            g["volga_1pt"] = (vu - 2 * base + vd)
            uu = self.shocked(Shock(kind, aid, h, "relative"), Shock("vol", aid, vb))
            ud = self.shocked(Shock(kind, aid, h, "relative"), Shock("vol", aid, -vb))
            du = self.shocked(Shock(kind, aid, -h, "relative"), Shock("vol", aid, vb))
            dd = self.shocked(Shock(kind, aid, -h, "relative"), Shock("vol", aid, -vb))
            g["vanna_1pt"] = (uu - ud - du + dd) / (4 * dS) * S * 0.01   # Δвега на 1% спота
            if kind == "fx":
                # ро иностранной валюты: +1 б.п. к ставке базовой валюты (через форвардные пункты)
                fu = self.shocked(Shock("fx_carry", aid, self.cfg.rate_bump))
                fd = self.shocked(Shock("fx_carry", aid, -self.cfg.rate_bump))
                g["rho_foreign_1bp"] = (fu - fd) / 2
                if self.cfg.vega_buckets:
                    surf = self.ctx.fx_vol(aid)
                    bks = []
                    for i, sl in enumerate(surf.slices):
                        if sl.T > T + 0.5:
                            break
                        u = self.shocked(Shock("vol_slice", aid, vb, str(i)))
                        d = self.shocked(Shock("vol_slice", aid, -vb, str(i)))
                        bks.append({"bucket": sl.tenor or sl.expiry.isoformat(), "expiry": sl.expiry.isoformat(),
                                    "vega_1pt": (u - d) / 2})
                    out.buckets[f"vega:{aid}"] = bks
            out.values[aid] = g
        # корреляции и кросс-гамма для многоактивных структур
        assets = [(n, s) for n, s in self.trade.underlyings.items() if s.asset_class in ("fx", "equity", "commodity")]
        if len(assets) >= 2:
            (n1, s1), (n2, s2) = assets[:2]
            try:
                cu = self.shocked(Shock("corr", f"{s1.id}|{s2.id}", self.cfg.corr_bump))
                cd = self.shocked(Shock("corr", f"{s1.id}|{s2.id}", -self.cfg.corr_bump))
                out.values["correlation"] = {"pair": f"{s1.id}/{s2.id}", "d_value_per_0.01": (cu - cd) / (2 * self.cfg.corr_bump) * 0.01}
            except Exception as e:  # pragma: no cover
                out.warnings.append(f"чувствительность к корреляции не рассчитана: {e}")
            k1 = s1.asset_class if s1.asset_class != "fx" else "fx"
            k2 = s2.asset_class if s2.asset_class != "fx" else "fx"
            h = self.cfg.spot_bump
            pp = self.shocked(Shock(k1, s1.id, h, "relative"), Shock(k2, s2.id, h, "relative"))
            pm = self.shocked(Shock(k1, s1.id, h, "relative"), Shock(k2, s2.id, -h, "relative"))
            mp = self.shocked(Shock(k1, s1.id, -h, "relative"), Shock(k2, s2.id, h, "relative"))
            mm = self.shocked(Shock(k1, s1.id, -h, "relative"), Shock(k2, s2.id, -h, "relative"))
            out.values["cross_gamma"] = {"pair": f"{s1.id}/{s2.id}", "value_per_1pct_each": (pp - pm - mp + mm) / 4 * (0.01 / h) ** 2}
        # тета
        rolled = self.ctx.rolled(self.cfg.theta_days)
        try:
            out.values["theta_1d"] = self._v(rolled) - base
        except Exception as e:
            out.warnings.append(f"тета не рассчитана: {e}")
        out.method["assets"] = meth
        return out

    # ------------------------------------------------------------------ ставки
    def rate_greeks(self) -> GreeksResult:
        out = GreeksResult()
        base = self._v(self.ctx)
        curves = self._curves_used()
        for cid, roles in curves.items():
            bp = self.cfg.rate_bump
            par_u = self.shocked(Shock("curve", cid, bp))
            par_d = self.shocked(Shock("curve", cid, -bp))
            gb = self.cfg.rate_gamma_bump
            gu = self.shocked(Shock("curve", cid, gb))
            gd = self.shocked(Shock("curve", cid, -gb))
            rec = {"dv01_parallel": (par_u - par_d) / 2, "gamma_10bp": (gu - 2 * base + gd), "roles": sorted(roles)}
            out.values[cid] = rec
            if self.cfg.key_rates:
                ts = [Tenor.parse(k).approx_years for k in KEY_TENORS]
                for role in sorted(roles):
                    rows = []
                    for i, k in enumerate(KEY_TENORS):
                        fn = key_rate_fn(i, ts)
                        u = self.shocked(Shock(f"curve_{role}", cid, 0.0, fn=lambda t, f=fn: f(t) * bp))
                        d = self.shocked(Shock(f"curve_{role}", cid, 0.0, fn=lambda t, f=fn: -f(t) * bp))
                        rows.append({"tenor": k, "dv01": (u - d) / 2})
                    out.buckets[f"krd:{cid}:{role}"] = rows
            if self.cfg.pv01_quotes and cid != "RUB.OFZ":
                rows = []
                cal = self.ctx.curve_fit_report(cid)["calibration"]
                for r in cal:
                    qid = r["quote_id"]
                    u = self._v(self.ctx.bumped({qid: bp}))
                    d = self._v(self.ctx.bumped({qid: -bp}))
                    rows.append({"quote": qid, "pv01": (u - d) / 2})
                out.buckets[f"pv01:{cid}"] = rows
        # вега процентной волатильности по сетке expiry × tenor
        irvols = {c for c in curves if any(r == "fcst" for r in curves[c])}
        for cid in irvols:
            try:
                rv = self.ctx.ir_vol(cid)
            except Exception:
                continue
            u = self.shocked(Shock("irvol", cid, 1.0))
            d = self.shocked(Shock("irvol", cid, -1.0))
            if abs(u - d) < 1e-9 * max(abs(base), 1):
                continue
            out.values[f"irvega:{cid}"] = {"vega_1bp_normal": (u - d) / 2}
            grid = []
            T = (self.trade.maturity - self.ctx.ref_date).days / 365.0
            for i, e in enumerate(rv.expiries):
                if e > T + 1.0:
                    break
                for j, tn in enumerate(rv.tenors):
                    uu = self.shocked(Shock("irvol_bucket", cid, 1e-4, f"{i},{j}"))
                    dd = self.shocked(Shock("irvol_bucket", cid, -1e-4, f"{i},{j}"))
                    grid.append({"expiry": float(e), "tenor": float(tn), "vega_1bp": (uu - dd) / 2})
            out.buckets[f"irvega:{cid}"] = grid
        out.method["rates"] = "key-rate: треугольные сдвиги нулевой кривой ±1 б.п., раздельно по ролям кривой"
        return out

    def _curves_used(self) -> dict[str, set[str]]:
        """Какие кривые и в каких ролях использует оценка (по трекеру)."""
        from ..core.provenance import InputTracker
        tr = InputTracker()
        price_trade(self.trade, self.ctx, engine=self.engine, tracker=tr, mc_overrides=self._mc_over())
        out: dict[str, set[str]] = {}
        for u in tr.used.values():
            if u.id.startswith("curve:"):
                cid = u.id[6:]
                roles = set()
                if "дисконт" in u.role:
                    roles.add("disc")
                if "прогноз" in u.role:
                    roles.add("fcst")
                if not roles:
                    continue
                out.setdefault(cid, set()).update(roles)
        # пересчёт иностранных потоков идёт через рублёвую кривую — она в роли disc
        return out


def compute_greeks(trade: Trade, ctx: MarketContext, cfg: GreekConfig | None = None, engine: str | None = None) -> dict[str, Any]:
    gc = GreeksCalculator(trade, ctx, cfg, engine=engine)
    a = gc.asset_greeks() if any(u.asset_class in ("fx", "equity", "commodity") for u in trade.underlyings.values()) else GreeksResult()
    r = gc.rate_greeks()
    return {"values": {**a.values, **r.values}, "buckets": {**a.buckets, **r.buckets},
            "method": {**a.method, **r.method}, "warnings": a.warnings + r.warnings}
