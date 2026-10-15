"""Ванильная альтернатива с тем же экономическим назначением.

Назначение (покупка/продажа валюты или товара, плата по плавающей ставке)
берётся из ``trade.purpose`` либо выводится из структуры. Для него строятся
стандартные альтернативы на том же расписании и номинале без плеча:

* форвард / процентный своп по рыночной ставке (нулевая стоимость);
* ванильный опцион на уровне защиты структуры (с премией);
* коллар нулевой стоимости с тем же уровнем защиты.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
from scipy.optimize import brentq

from ..instruments.schema import Component, Leg, RateObs, Trade
from ..pricing.engine import price_trade


def infer_purpose(trade: Trade) -> str:
    if trade.purpose.type != "other":
        return trade.purpose.type
    for leg in trade.legs:
        u = trade.underlyings.get(leg.underlying) if leg.underlying else (next(iter(trade.underlyings.values())) if trade.underlyings else None)
        cls = u.asset_class if u else None
        for c in leg.components:
            if cls == "rate":
                if c.kind in ("cap",) and c.position == "long":
                    return "pay_floating"
                if c.kind == "fixed" and c.position == "short":
                    return "pay_floating"
                if c.kind == "floor" and c.position == "long":
                    return "receive_floating"
            elif cls in ("fx", "commodity"):
                buy = "buy_fx" if cls == "fx" else "buy_commodity"
                sell = "sell_fx" if cls == "fx" else "sell_commodity"
                if c.kind in ("call", "forward") and c.position == "long":
                    return buy
                if c.kind == "put" and c.position == "long":
                    return sell
                if c.kind == "forward" and c.position == "short":
                    return sell
    return "investment"


def _main_leg(trade: Trade) -> Leg:
    return max(trade.legs, key=lambda l: len(l.components))


def protection_terms(trade: Trade, purpose: str) -> dict[str, Any]:
    """Уровень защиты и защищённый номинал на период (без плеча)."""
    leg = _main_leg(trade)
    want = {"buy_fx": ("call", "forward"), "buy_commodity": ("call", "forward"), "sell_fx": ("put",),
            "sell_commodity": ("put",), "pay_floating": ("cap", "fixed"), "receive_floating": ("floor",)}.get(purpose, ())
    strike, notional = None, None
    for c in leg.components:
        if c.kind in want and (c.position == "long" or (c.kind == "fixed" and c.position == "short")):
            strike = c.strike if c.kind != "fixed" else c.rate
            notional = leg.notional.amount if leg.notional else 1.0
            break
    if strike is None:
        for c in leg.components:
            if c.strike is not None:
                strike = c.strike
                notional = leg.notional.amount if leg.notional else 1.0
                break
    return {"strike": strike, "notional": notional, "leg": leg}


def _with_components(trade: Trade, leg: Leg, comps: list[dict], product: str, schedule_override=None) -> Trade:
    d = trade.model_dump(mode="python")
    ld = leg.model_dump(mode="python")
    ld["components"] = comps
    ld["modifiers"] = []
    if schedule_override is not None:
        ld["schedule"] = schedule_override
    d["legs"] = [ld]
    d["modifiers"] = []
    d["product"] = product
    d["premium"] = None
    d["state"] = {}
    d["identification"]["trade_id"] = trade.identification.trade_id + ":" + product
    return Trade.model_validate(d)


def generate_alternatives(trade: Trade, ctx) -> list[dict[str, Any]]:
    purpose = infer_purpose(trade)
    pt = protection_terms(trade, purpose)
    leg = pt["leg"]
    K = pt["strike"]
    out: list[dict[str, Any]] = []
    if purpose in ("buy_fx", "sell_fx", "buy_commodity", "sell_commodity"):
        buy = purpose.startswith("buy")
        # форвард по рынку на каждую дату: нулевая стоимость — страйк = форвард
        base_fwd = _with_components(trade, leg, [{"kind": "forward", "strike": 0.0, "position": "long" if buy else "short"}],
                                    "форвард")
        f0 = price_trade(base_fwd, ctx).value
        n_units = _units(leg)
        dfw = _annuity_units(trade, leg, ctx)
        Fm = abs(f0) / dfw if dfw > 0 else 0.0
        fwd = _with_components(trade, leg, [{"kind": "forward", "strike": Fm, "position": "long" if buy else "short"}],
                               "Форвард по рынку")
        out.append({"label": "Форвард по рынку", "trade": fwd, "description": f"Фиксация курса на уровне среднего форварда {Fm:,.4f} без плеча",
                    "strike": Fm})
        if K is not None:
            opt_kind = "call" if buy else "put"
            van = _with_components(trade, leg, [{"kind": opt_kind, "strike": K, "position": "long"}], f"Ванильный {opt_kind}")
            out.append({"label": f"Ванильный опцион ({'колл' if buy else 'пут'}) K={K:,.4f}", "trade": van,
                        "description": "Защита на уровне структуры без продажи опционов клиентом; требует уплаты премии",
                        "strike": K})
            other = "put" if buy else "call"

            def collar_val(k2):
                tr = _with_components(trade, leg, [{"kind": opt_kind, "strike": K, "position": "long"},
                                                   {"kind": other, "strike": k2, "position": "short"}], "коллар")
                return price_trade(tr, ctx).value
            try:
                lo, hi = (Fm * 0.4, K * 0.99999) if buy else (K * 1.00001, Fm * 2.5)
                k2 = brentq(collar_val, lo, hi, xtol=1e-6 * Fm)
                col = _with_components(trade, leg, [{"kind": opt_kind, "strike": K, "position": "long"},
                                                    {"kind": other, "strike": k2, "position": "short"}], "Коллар нулевой стоимости")
                out.append({"label": f"Коллар нулевой стоимости {min(K, k2):,.2f}–{max(K, k2):,.2f}", "trade": col,
                            "description": f"Защита на уровне {K:,.4f}, отказ от выгоды за уровнем {k2:,.4f}; без плеча",
                            "strike": K, "strike2": k2})
            except ValueError:
                pass
    elif purpose == "pay_floating":
        rleg = next((l for l in trade.legs if any(c.kind in ("float", "cap", "floor") for c in l.components)), leg)
        base = _with_components(trade, rleg, [{"kind": "float", "position": "long"}], "плавающая нога")
        fl = price_trade(base, ctx).value
        ann_tr = _with_components(trade, rleg, [{"kind": "fixed", "rate": 1.0, "position": "long"}], "аннуитет")
        ann = price_trade(ann_tr, ctx).value
        par = fl / ann if ann else 0.0
        irs = _with_components(trade, rleg, [{"kind": "float", "position": "long"}, {"kind": "fixed", "rate": par, "position": "short"}],
                               "Процентный своп по рынку")
        out.append({"label": f"Процентный своп (фиксация {par:.2%})", "trade": irs,
                    "description": "Полная фиксация ставки по рынку, нулевая стоимость", "strike": par})
        if K is not None:
            cap = _with_components(trade, rleg, [{"kind": "cap", "strike": K, "position": "long"}], "Ванильный кэп")
            out.append({"label": f"Ванильный кэп {K:.2%}", "trade": cap,
                        "description": "Защита от роста ставки выше страйка без условий отключения; премия", "strike": K})

            def collar_val(k2):
                tr = _with_components(trade, rleg, [{"kind": "cap", "strike": K, "position": "long"},
                                                    {"kind": "floor", "strike": k2, "position": "short"}], "коллар")
                return price_trade(tr, ctx).value
            try:
                k2 = brentq(collar_val, 0.0001, K - 1e-6, xtol=1e-7)
                col = _with_components(trade, rleg, [{"kind": "cap", "strike": K, "position": "long"},
                                                     {"kind": "floor", "strike": k2, "position": "short"}], "Процентный коллар")
                out.append({"label": f"Процентный коллар {k2:.2%}–{K:.2%}", "trade": col,
                            "description": f"Кэп {K:.2%} оплачен продажей флора {k2:.2%}; нулевая стоимость", "strike": K, "strike2": k2})
            except ValueError:
                pass
    for a in out:
        r = price_trade(a["trade"], ctx)
        a["value"] = r.value
        a["engine"] = r.engine
    return out


def _units(leg: Leg) -> float:
    return leg.notional.amount if leg.notional else 1.0


def _annuity_units(trade: Trade, leg: Leg, ctx) -> float:
    """Σ N_i·DF_i по периодам ноги (для перевода PV форварда в средний форвардный курс)."""
    tr = _with_components(trade, leg, [{"kind": "cash", "payout": 1.0, "position": "long"}], "аннуитет")
    return price_trade(tr, ctx).value
