"""Пакеты: кредит + обязательный дериватив, депозит + опцион, структурные ноты.

Главное требование: единая эффективная стоимость пакета, сопоставимая между
предложениями разных банков. Сравнивать компоненты по отдельности нельзя —
маржа может быть «спрятана» в деривативе, комиссиях или условиях кредита.

Эффективная ставка «всё включено» (для заёмщика):

    R_eff = −(PV процентов + PV деривативов + PV комиссий) / Σ N_i·τ_i·DF_i

— фиксированная ставка на том же графике номинала, эквивалентная по
приведённой стоимости всем платежам пакета при рыночных кривых. Для
депозита / структурного продукта — эффективная доходность к сравнению с
обычным депозитом или ОФЗ той же срочности.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from ..instruments.schema import Trade, load_trade
from ..pricing.engine import price_trade


class Fee(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    amount: float
    currency: str = "RUB"
    payment_date: str | None = None
    payer: str = "client"


class PackageMember(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str                       # loan | deposit | derivative | note | bond
    trade: dict[str, Any]
    description: str = ""


class Package(BaseModel):
    model_config = ConfigDict(extra="forbid")
    package_id: str
    bank: str
    kind: str = "loan_with_hedge"    # loan_with_hedge | deposit_with_option | structured_note
    description: str = ""
    members: list[PackageMember]
    fees: list[Fee] = Field(default_factory=list)
    benchmark_rate: float | None = None   # для депозита: ставка обычного депозита той же срочности


@dataclass
class PackageResult:
    package_id: str
    bank: str
    kind: str
    members: list[dict[str, Any]]
    fees_pv: float
    annuity: float
    effective_rate: float
    components_bp: dict[str, float]
    total_pv: float
    benchmark: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_package(path_or_dict) -> Package:
    if isinstance(path_or_dict, dict):
        return Package.model_validate(path_or_dict)
    from pathlib import Path
    return Package.model_validate(yaml.safe_load(Path(path_or_dict).read_text(encoding="utf-8")))


def _annuity(loan: Trade, ctx) -> float:
    """Σ N_i·τ_i·DF_i по графику процентных периодов кредита (ставка 100%)."""
    leg = next(l for l in loan.legs if any(c.kind in ("fixed", "float") for c in l.components))
    d = loan.model_dump(mode="python")
    ld = leg.model_dump(mode="python")
    ld["components"] = [{"kind": "fixed", "rate": 1.0, "position": "long"}]
    ld["modifiers"] = []
    ld["exchange_notional"] = "none"
    d["legs"] = [ld]
    d["modifiers"] = []
    return price_trade(Trade.model_validate(d), ctx).value


def value_package(pkg: Package, ctx) -> PackageResult:
    members = []
    total = 0.0
    host = None
    for m in pkg.members:
        tr = load_trade(m.trade)
        r = price_trade(tr, ctx)
        # для кредита/депозита: без потоков номинала, чтобы получить только проценты (номинал в эффективной ставке — база)
        interest_only = None
        if m.role in ("loan", "deposit"):
            host = tr
            d = tr.model_dump(mode="python")
            for ld in d["legs"]:
                ld["exchange_notional"] = "none"
            interest_only = price_trade(Trade.model_validate(d), ctx).value
        members.append({"role": m.role, "trade_id": tr.identification.trade_id, "product": tr.product,
                        "pv": r.value, "pv_interest": interest_only, "engine": r.engine, "description": m.description})
        total += r.value
    rep = "RUB"
    disc = ctx.discount_curve(rep, False)
    fees_pv = 0.0
    from datetime import date
    for f in pkg.fees:
        d = date.fromisoformat(f.payment_date) if f.payment_date else ctx.ref_date
        df = disc.df_date(d) if d > ctx.ref_date else 1.0
        fees_pv += (-f.amount if f.payer == "client" else f.amount) * df
    if host is None:
        raise ValueError("в пакете нет кредита или депозита")
    ann = _annuity(host, ctx)
    sign = -1.0 if pkg.kind == "loan_with_hedge" else 1.0
    interest_pv = sum(m["pv_interest"] for m in members if m["pv_interest"] is not None)
    deriv_pv = sum(m["pv"] for m in members if m["role"] not in ("loan", "deposit"))
    # для заёмщика: стоимость = −(процент + дериватив + комиссии) / аннуитет
    eff = sign * (interest_pv + deriv_pv + fees_pv) / ann
    comps = {
        "проценты по договору": sign * interest_pv / ann * 1e4,
        "деривативы (справедливая стоимость)": sign * deriv_pv / ann * 1e4,
        "комиссии": sign * fees_pv / ann * 1e4,
    }
    bench = {}
    notes = []
    if pkg.kind == "loan_with_hedge":
        # рыночная фиксированная ставка на том же графике — ориентир «идеального» хеджа без наценок
        float_leg_market = _market_float_equivalent(host, ctx, ann)
        if float_leg_market is not None:
            bench = {"market_fixed_equivalent": float_leg_market,
                     "explain": "ставка фиксированного свопа на КС по рынку на графике кредита (без маржи кредита)"}
        notes.append("Эффективная ставка — эквивалентная фиксированная ставка по всем платежам пакета при рыночных кривых")
    else:
        if pkg.benchmark_rate is not None:
            bench = {"benchmark_rate": pkg.benchmark_rate, "difference_bp": (eff - pkg.benchmark_rate) * 1e4}
    return PackageResult(pkg.package_id, pkg.bank, pkg.kind, members, fees_pv, ann, eff, comps, total + fees_pv, bench, notes)


def _market_float_equivalent(host: Trade, ctx, ann: float) -> float | None:
    leg = next((l for l in host.legs if any(c.kind == "float" for c in l.components)), None)
    if leg is None:
        return None
    d = host.model_dump(mode="python")
    ld = leg.model_dump(mode="python")
    ld["components"] = [{"kind": "float", "position": "long"}]
    ld["modifiers"] = []
    ld["exchange_notional"] = "none"
    d["legs"] = [ld]
    return price_trade(Trade.model_validate(d), ctx).value / ann


def compare_offers(packages: list[Package], ctx) -> dict[str, Any]:
    res = [value_package(p, ctx) for p in packages]
    best = min(res, key=lambda r: r.effective_rate) if res and res[0].kind == "loan_with_hedge" else \
        max(res, key=lambda r: r.effective_rate)
    rows = []
    for r in res:
        rows.append({"package": r.package_id, "bank": r.bank, "effective_rate": r.effective_rate,
                     "vs_best_bp": (r.effective_rate - best.effective_rate) * 1e4, "components_bp": r.components_bp})
    return {"results": [r.to_dict() for r in res], "table": rows, "best": best.package_id}
