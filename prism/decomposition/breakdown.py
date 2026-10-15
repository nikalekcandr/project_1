"""Разложение цены сделки.

Прайсер выдаёт не одно число, а разложение передачи стоимости от клиента
банку:

    передача = (премия клиента, приведённая) − справедливая стоимость для клиента (mid)
             = издержки исполнения и хеджирования
             + резерв на модельную неопределённость
             + кредитная составляющая (CVA, с учётом WWR)
             + фондирование и капитал (FVA, KVA — вторая очередь)
             + остаток (наценка сверх обоснованных компонент)

Каждая компонента — с методом расчёта и допущениями.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from ..instruments.schema import Trade


@dataclass
class Breakdown:
    currency: str
    fair_value_client: float
    premium_pv: float
    transfer: float
    hedge_cost: float
    hedge_detail: list[dict[str, Any]]
    model_reserve: float
    credit: float
    credit_detail: dict[str, Any]
    funding: float
    capital: float
    residual: float
    notional_ref: float
    tenor_years: float
    notes: list[str] = field(default_factory=list)

    @property
    def residual_bp_pa(self) -> float:
        if self.notional_ref <= 0 or self.tenor_years <= 0:
            return float("nan")
        return self.residual / self.notional_ref / self.tenor_years * 1e4

    def waterfall(self) -> list[dict[str, Any]]:
        return [
            {"label": "Хеджирование и исполнение", "value": self.hedge_cost},
            {"label": "Модельная неопределённость", "value": self.model_reserve},
            {"label": "Кредитный риск (CVA)", "value": self.credit},
            {"label": "Фондирование (FVA)", "value": self.funding},
            {"label": "Капитал (KVA)", "value": self.capital},
            {"label": "Остаток (наценка)", "value": self.residual},
        ]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["waterfall"] = self.waterfall()
        d["residual_bp_pa"] = self.residual_bp_pa
        return d


def hedge_cost(trade: Trade, ctx, greeks: dict[str, Any], price_items: list[dict] | None = None,
               rebalance_days: int = 5) -> tuple[float, list[dict[str, Any]]]:
    """Оценка издержек исполнения и хеджирования (в валюте отчёта).

    * дельта: |Δ|·S·(полуспред спота) + |Δ_fwd|·(полуспред форвардных пунктов);
    * вега: Σ по срокам |вега|·полуспред волатильности (ATM bid/ask);
    * ставки: Σ |key-rate DV01|·полуспред свопов (б.п.);
    * динамическое перехеджирование (оценка типа Лиланда):
      (k/2)·S²·|Γ|·σ·√(2/π)·T/√Δt — допущение о частоте ребалансировки.
    """
    det = []
    total = 0.0
    vals = greeks.get("values", {})
    T = max((trade.maturity - ctx.ref_date).days / 365.0, 1e-6)
    for name, spec in trade.underlyings.items():
        g = vals.get(spec.id)
        if not isinstance(g, dict) or "delta" not in g:
            continue
        S = g["spot"]
        if spec.asset_class == "fx":
            fx = ctx.fx(spec.id)
            hs = (fx.spot_ask - fx.spot_bid) / 2 if fx.spot_ask and fx.spot_bid else 0.0005 * S
            pts_hs = 0.0
            if fx.points_halfspread:
                from ..core.dates import Tenor
                tt = sorted((Tenor.parse(k).approx_years, v) for k, v in fx.points_halfspread.items())
                pts_hs = float(np.interp(T, [a for a, _ in tt], [b for _, b in tt]))
            c_spot = abs(g["delta"]) * hs
            c_pts = abs(g.get("forward_delta", g["delta"])) * pts_hs
            det.append({"item": f"дельта {spec.id}: спред спота", "value": c_spot, "basis": f"|Δ|={abs(g['delta']):,.0f}, полуспред {hs:.4f}"})
            det.append({"item": f"дельта {spec.id}: спред форвардных пунктов", "value": c_pts, "basis": f"полуспред пунктов {pts_hs:.4f}"})
            total += c_spot + c_pts
            surf = ctx.fx_vol(spec.id)
            vhs = np.mean([p.halfspread for sl in surf.slices for p in sl.pillars if p.label == "ATM"] or [0.005])
            vb = greeks.get("buckets", {}).get(f"vega:{spec.id}")
            vega_abs = sum(abs(b["vega_1pt"]) for b in vb) if vb else abs(g.get("vega_1pt", 0.0))
            c_vega = vega_abs * vhs * 100
            det.append({"item": f"вега {spec.id}", "value": c_vega, "basis": f"Σ|вега по срокам|={vega_abs:,.0f} на 1 п., полуспред {vhs * 100:.2f} п."})
            total += c_vega
            sig = surf.atm_vol(T)
            gamma = abs(g.get("gamma", 0.0))
            dt = rebalance_days / 365.0
            # Σ по ребалансировкам: полуспред × |ΔΔ|·S, E|dS| = S·σ·√dt·√(2/π), число ребалансировок T/dt
            c_dyn = (hs / S) * S * S * gamma * sig * np.sqrt(2 / np.pi) * T / np.sqrt(dt)
            det.append({"item": f"динамическое перехеджирование {spec.id}", "value": c_dyn,
                        "basis": f"оценка типа Лиланда, ребалансировка раз в {rebalance_days} дн., Γ={gamma:.3g}"})
            total += c_dyn
        elif spec.asset_class in ("equity", "commodity"):
            hs = 0.0005 * S
            c = abs(g["delta"]) * hs + abs(g.get("vega_1pt", 0.0)) * 0.5
            det.append({"item": f"дельта и вега {spec.id}", "value": c, "basis": "полуспред 5 б.п. к споту, 0.5 п. к волатильности (допущение)"})
            total += c
    for key, rows in greeks.get("buckets", {}).items():
        if key.startswith("krd:"):
            cid = key.split(":")[1]
            hs_bp = _swap_halfspread_bp(ctx, cid)
            c = sum(abs(r["dv01"]) for r in rows) * hs_bp
            det.append({"item": f"ставки {cid} ({key.split(':')[2]})", "value": c,
                        "basis": f"Σ|key-rate DV01|×полуспред {hs_bp:.1f} б.п."})
            total += c
    for key, v in vals.items():
        if key.startswith("irvega:"):
            cid = key.split(":", 1)[1]
            rv = ctx.ir_vol(cid)
            c = abs(v["vega_1bp_normal"]) * rv.halfspread_bp
            det.append({"item": f"процентная вега {cid}", "value": c, "basis": f"полуспред {rv.halfspread_bp:.1f} б.п. нормальной волы"
                        + (" (допущение: рынка опционов нет)" if rv.kind.is_model_based else "")})
            total += c
    return total, det


def _swap_halfspread_bp(ctx, cid: str) -> float:
    rep = ctx.curve_fit_report(cid) if cid != "RUB.OFZ" else {"calibration": []}
    hs = []
    for r in rep["calibration"]:
        q = ctx.snapshot.get(r["quote_id"])
        if q is not None and q.bid is not None and q.ask is not None:
            hs.append((q.ask - q.bid) / 2 * 1e4)
    return float(np.mean(hs)) if hs else 5.0


def decompose(trade: Trade, ctx, fair_value: float, greeks: dict[str, Any], xva=None, checks: list[dict] | None = None,
              premium_override: float | None = None) -> Breakdown:
    rep = trade.report_currency
    disc = ctx.discount_curve(rep, trade.collateral.collateralized)
    prem_pv = 0.0
    if premium_override is not None:
        prem_pv = premium_override
    elif trade.premium is not None and trade.premium.amount:
        p = trade.premium
        amt = p.amount
        if p.unit == "pct_notional":
            leg = trade.legs[0]
            amt = p.amount * (leg.notional.amount if leg.notional else 1.0)
            if leg.notional and leg.notional.currency != rep:
                amt *= ctx.fx(f"{leg.notional.currency}{rep}").spot_value
        pd = p.payment_date or ctx.ref_date
        df = disc.df_date(pd) if pd > ctx.ref_date else 1.0
        prem_pv = (amt if p.payer == "client" else -amt) * df
    transfer = prem_pv - fair_value
    hc, hdet = hedge_cost(trade, ctx, greeks)
    model_res = 0.0
    for c in checks or []:
        if c.get("check") == "model_vv_vs_lv" and "diff" in c:
            model_res = 0.5 * abs(c["diff"])
    credit = 0.0
    cdet: dict[str, Any] = {}
    funding = capital = 0.0
    if xva is not None:
        credit = xva.cva_wwr_stochastic if xva.cva_wwr_stochastic is not None else xva.cva
        credit = max(credit, 0.0)
        cdet = {"cva": xva.cva, "cva_wwr_stochastic": xva.cva_wwr_stochastic, "cva_wwr_alpha": xva.cva_wwr_alpha,
                "dva": xva.dva, "method": xva.method.get("credit_client", {}).get("method")}
        funding = max(xva.fca - xva.fba, 0.0)
        capital = xva.kva
    residual = transfer - hc - model_res - credit - funding - capital
    leg = max(trade.legs, key=lambda l: len(l.components))
    notional = leg.notional.amount if leg.notional else 0.0
    if leg.notional and leg.notional.currency != rep:
        notional *= ctx.fx(f"{leg.notional.currency}{rep}").spot_value
    T = max((trade.maturity - ctx.ref_date).days / 365.0, 1e-6)
    notes = []
    if transfer < 0:
        notes.append("Передача стоимости отрицательна: по mid-оценке структура выгодна клиенту")
    if residual < 0:
        notes.append("Остаток отрицателен: обоснованные издержки превышают наценку (котировка конкурентна или оценка консервативна)")
    return Breakdown(rep, fair_value, prem_pv, transfer, hc, hdet, model_res, credit, cdet, funding, capital, residual,
                     notional, T, notes)
