"""Полная оценка сделки: всё, что входит в отчёт, и аудиторская запись.

Слои строго разделены: снапшот → контекст рынка (кривые, поверхности) →
определение инструмента → движки оценки → риск-движок (греки, сценарии,
XVA) → разложение → отчёт.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .core.provenance import InputTracker
from .instruments.describe import describe_trade
from .instruments.schema import Trade
from .marketdata.context import MarketContext
from .marketdata.snapshot import MarketSnapshot


@dataclass
class ValuationOptions:
    greeks: bool = True
    stresses: bool = True
    grid: bool = True
    alternatives: bool = True
    profile: bool = True
    xva: bool = True
    crosscheck: bool = True
    barrier_profile: bool = True
    ifrs9_host: str | None = None
    market_rate_at_inception: float | None = None
    xva_paths: int = 4000
    greek_mc_paths: int | None = 20000
    engine: str | None = None

    @classmethod
    def fast(cls) -> "ValuationOptions":
        return cls(grid=False, barrier_profile=False, xva_paths=2000, greek_mc_paths=8000)

    @classmethod
    def price_only(cls) -> "ValuationOptions":
        return cls(greeks=False, stresses=False, grid=False, alternatives=False, profile=False, xva=False,
                   crosscheck=False, barrier_profile=False)


@dataclass
class Valuation:
    trade: Trade
    snapshot_id: str
    snapshot_hash: str
    snapshot_demo: bool
    valuation_time: str
    description: dict
    pricing: Any
    greeks: dict | None = None
    stresses: list | None = None
    grid: dict | None = None
    barrier: dict | None = None
    alternatives: list | None = None
    profile: Any = None
    xva: Any = None
    breakdown: Any = None
    ifrs9: Any = None
    nrd: dict | None = None
    market: dict = field(default_factory=dict)
    qc: list = field(default_factory=list)
    record: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        def conv(x):
            if x is None:
                return None
            if hasattr(x, "to_dict"):
                return x.to_dict()
            return x
        alts = None
        if self.alternatives is not None:
            alts = [{k: v for k, v in a.items() if k != "trade"} | {"trade": a["trade"].model_dump(mode="json")} for a in self.alternatives]
        return {
            "trade": self.trade.model_dump(mode="json"), "snapshot_id": self.snapshot_id, "snapshot_hash": self.snapshot_hash,
            "snapshot_demo": self.snapshot_demo, "valuation_time": self.valuation_time, "description": self.description,
            "pricing": conv(self.pricing), "greeks": self.greeks, "stresses": self.stresses, "grid": self.grid,
            "barrier": self.barrier, "alternatives": alts, "profile": conv(self.profile), "xva": conv(self.xva),
            "breakdown": conv(self.breakdown), "ifrs9": conv(self.ifrs9), "nrd": self.nrd, "market": self.market,
            "qc": self.qc, "record": self.record, "timings": self.timings, "errors": self.errors,
        }


def _step(v: Valuation, name: str, fn):
    t = time.perf_counter()
    try:
        return fn()
    except Exception as e:  # отдельный блок не должен ломать отчёт целиком; ошибка видна в отчёте
        v.errors.append(f"{name}: {type(e).__name__}: {e}")
        return None
    finally:
        v.timings[name] = round((time.perf_counter() - t) * 1000, 1)


def run_valuation(trade: Trade, snapshot: MarketSnapshot, options: ValuationOptions | None = None,
                  config: dict | None = None) -> Valuation:
    from .decomposition.alternatives import generate_alternatives, infer_purpose, protection_terms
    from .decomposition.breakdown import decompose
    from .decomposition.profile import hedge_profile
    from .packages.ifrs9 import assess_embedded
    from .pricing.engine import price_trade
    from .reporting.nrd import nrd_fields
    from .risk.greeks import GreekConfig, compute_greeks
    from .risk.scenarios import barrier_profile, run_stresses, spot_vol_grid
    from .xva.engine import XVAConfig, compute_xva
    from .audit.record import make_record

    opt = options or ValuationOptions()
    tracker = InputTracker()
    ctx = MarketContext(snapshot, config, tracker=tracker)
    v = Valuation(trade, snapshot.id, snapshot.content_hash, snapshot.is_demo,
                  datetime.now(timezone.utc).isoformat(timespec="seconds"), describe_trade(trade), None, qc=snapshot.qc)
    t0 = time.perf_counter()
    v.pricing = price_trade(trade, ctx, engine=opt.engine, crosscheck=opt.crosscheck, tracker=tracker)
    v.timings["pricing"] = round((time.perf_counter() - t0) * 1000, 1)
    base = v.pricing.value
    eng = opt.engine
    if opt.greeks:
        v.greeks = _step(v, "greeks", lambda: compute_greeks(trade, ctx, GreekConfig(mc_paths=opt.greek_mc_paths), engine=eng))
    mc_o = {"paths": opt.greek_mc_paths} if opt.greek_mc_paths else None
    if opt.stresses:
        v.stresses = _step(v, "stresses", lambda: run_stresses(trade, ctx, base, eng, mc_o))
    has_assets = any(u.asset_class in ("fx", "equity", "commodity") for u in trade.underlyings.values())
    if opt.grid and has_assets:
        v.grid = _step(v, "grid", lambda: spot_vol_grid(trade, ctx, base_value=base, engine=eng, mc_overrides=mc_o))
    if opt.barrier_profile and "barrier" in trade.modifier_types():
        v.barrier = _step(v, "barrier_profile", lambda: barrier_profile(trade, ctx, engine=eng))
    purpose = infer_purpose(trade)
    if opt.alternatives:
        v.alternatives = _step(v, "alternatives", lambda: generate_alternatives(trade, ctx))
    if opt.profile and v.alternatives is not None and purpose in ("buy_fx", "sell_fx", "buy_commodity", "sell_commodity", "pay_floating"):
        def prof():
            pt = protection_terms(trade, purpose)
            leg = pt["leg"]
            n_per = leg.notional.amount if leg.notional else 1.0
            n_periods = len(leg.schedule.dates) if leg.schedule.dates else max(1, len([1 for _ in range(1)]))
            from .payoff.compile import compile_trade
            cp = compile_trade(trade, ctx.ref_date)
            main = max(cp.legs, key=lambda l: len(l.components))
            live = [p for p in main.periods if p.payment > ctx.ref_date]
            if purpose == "pay_floating":
                exposure = sum(p.notional * p.tau for p in live)
                center = float(ctx.forecast_curve(trade.underlyings[leg.underlying].id if leg.underlying else "KEYRATE").zero(1.0))
                center = 365 * __import__("numpy").expm1(center / 365)
                xl = "средняя ставка за период"
            else:
                exposure = trade.purpose.exposure_notional or sum(p.notional for p in live)
                u = trade.underlyings[leg.underlying] if leg.underlying else next(iter(trade.underlyings.values()))
                center = ctx.fx(u.id).spot_value if u.asset_class == "fx" else ctx.commodity(u.id).forward(trade.maturity)
                xl = "курс на даты фиксинга" if u.asset_class == "fx" else "цена на даты фиксинга"
            upfront = {}
            for a in v.alternatives:
                if a["value"] > 0 and abs(a["value"]) > 1e-6:
                    from .marketdata.context import MarketContext as _MC
                    disc = ctx.discount_curve(trade.report_currency)
                    upfront[a["label"]] = a["value"] / disc.df_date(trade.maturity)
            prem = trade.premium.amount if trade.premium and trade.premium.payer == "client" else 0.0
            if prem:
                upfront["Предложенная структура"] = prem
            return hedge_profile(trade, [(a["label"], a["trade"]) for a in v.alternatives], ctx, purpose, exposure, center,
                                 x_label=xl, upfront=upfront)
        v.profile = _step(v, "profile", prof)
    if opt.xva:
        v.xva = _step(v, "xva", lambda: compute_xva([trade], ctx, XVAConfig(paths=opt.xva_paths)))
    if v.greeks is not None:
        v.breakdown = _step(v, "breakdown", lambda: decompose(trade, ctx, base, v.greeks, v.xva, v.pricing.checks))
    if opt.ifrs9_host:
        v.ifrs9 = _step(v, "ifrs9", lambda: assess_embedded(trade, opt.ifrs9_host, fair_value=base,
                                                            model_based_inputs=[u["id"] for u in v.pricing.model_based_inputs],
                                                            market_rate_at_inception=opt.market_rate_at_inception,
                                                            engine=v.pricing.model))
    v.nrd = nrd_fields(trade, base, ctx.ref_date.isoformat())
    v.market = _step(v, "market", lambda: _market_section(trade, ctx)) or {}
    # итоговый перечень входов (все блоки отчёта) и предупреждения
    v.pricing.inputs = tracker.to_list()
    for w in tracker.warnings:
        if w not in v.pricing.warnings:
            v.pricing.warnings.append(w)
    v.record = make_record(v, opt, ctx)
    return v


def _market_section(trade: Trade, ctx: MarketContext) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        out["meeting_path"] = ctx.meeting_path()
    except Exception as e:
        out["meeting_path_error"] = str(e)
    curves = {}
    for u in ctx.tracker.used.values():
        if u.id.startswith("curve:"):
            cid = u.id[6:]
            if cid in ctx.config["curves"]:
                curves[cid] = ctx.curve_fit_report(cid)
    out["curves"] = curves
    pairs = sorted({u.id for u in trade.underlyings.values() if u.asset_class == "fx"})
    out["cip"] = {}
    out["vol"] = {}
    for p in pairs:
        try:
            out["cip"][p] = ctx.cip_table(p)
        except Exception:
            pass
        try:
            out["vol"][p] = ctx.fx_vol(p).describe()
        except Exception:
            pass
    return out
