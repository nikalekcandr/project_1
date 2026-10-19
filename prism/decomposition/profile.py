"""Профиль выплат на дату исполнения и зоны защиты.

Сценарий «скачок к уровню X сразу после даты оценки и далее без изменений»:
для барьеров это означает касание, если X за барьером; для TARF —
накопление (X − K)+ на каждом фиксинге до достижения цели. Конвенция
явная и пишется в отчёт.

Для хеджера рассчитывается эффективный курс/ставка с учётом выплат
дериватива и выделяются зоны:
* «защита не работает» — неблагоприятный для клиента уровень, где
  дериватив не компенсирует движение (например, за KO-барьером);
* «хуже, чем без хеджа» — уровень, где эффективный курс хуже рыночного;
  причина определяется по конструкции сделки (плечо, проданный опцион,
  включающийся при касании барьера, или фиксация курса).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np

from ..instruments.schema import BarrierMod, LeverageMod, RateObs, Trade
from ..payoff.compile import CPeriod, CProduct, compile_trade
from ..payoff.evaluate import Evaluator, MarketView


class ScenarioView(MarketView):
    """Детерминированный сценарий: все будущие наблюдения базиса = levels[i] (путь i)."""

    def __init__(self, cp: CProduct, ctx, levels: np.ndarray, names: set[str]):
        self.p = cp
        self.ctx = ctx
        self.ref = cp.ref_date
        self.levels = np.asarray(levels, float)
        self.n = len(levels)
        self.names = names

    def warn(self, msg):
        pass

    def state_knocked(self, label):
        return bool(self.p.trade.state.knocked.get(label, False))

    def _asset(self, name: str, d: date) -> np.ndarray:
        spec = self.p.trade.underlyings[name]
        if d < self.ref and self.ctx.has_fixing(spec.id, spec.fixing.source, d):
            return np.full(self.n, self.ctx.fixing(spec.id, spec.fixing.source, d))
        if d <= self.ref:
            return np.full(self.n, self._spot(spec))
        return self.levels.copy()

    def _spot(self, spec):
        if spec.asset_class == "fx":
            return self.ctx.fx(spec.id).spot_value
        if spec.asset_class == "equity":
            e = self.ctx.equity(spec.id)
            return e.spot * e.shock
        if spec.asset_class == "commodity":
            return self.ctx.commodity(spec.id).forward(self.ref)
        return float(self.levels.mean())

    def obs_matrix(self, obs, dates):
        t = obs.type
        if t == "rate":
            return self.rate_daily(obs, dates)
        if t == "asset":
            return np.column_stack([self._asset(obs.name, d) for d in dates])
        if t == "performance":
            init = obs.initial or self._asset(obs.name, self.p.start)[0]
            return np.column_stack([self._asset(obs.name, d) / init for d in dates])
        if t == "spread":
            # сценарий по первому базису, остальные — по форвардам (спред сдвигается на уровень)
            return np.column_stack([self.levels for _ in dates])
        if t == "basket":
            return np.column_stack([self.levels for _ in dates])
        raise ValueError(t)

    def obs_grid(self, obs, d0, d1):
        ds = [d0, d1]
        m = self.obs_matrix(obs, ds)
        return ds, np.log(np.maximum(m, 1e-300)), np.zeros((self.n, 1))

    def rate_period(self, obs: RateObs, p: CPeriod) -> np.ndarray:
        return self.levels.copy()

    def rate_daily(self, obs, dates):
        return np.column_stack([self.levels for _ in dates])

    def fx_value(self, pair, d, source):
        return np.full(self.n, self.ctx.fx(pair).forward(d))

    def df(self, ccy, d):
        return 1.0   # профиль — в недисконтированных суммах

    def state_vars(self, d):
        return self.levels[:, None]


def scenario_cash(trade: Trade, ctx, levels: np.ndarray) -> dict[str, Any]:
    """Недисконтированные выплаты по каждому сценарию уровня (с точки зрения клиента)."""
    cp = compile_trade(trade, ctx.ref_date)
    names = cp.underlying_names()
    mv = ScenarioView(cp, ctx, levels, names)
    flows = Evaluator(cp, mv, 0.0).flows()
    total = np.zeros(len(levels))
    for f in flows:
        if f.hit_dist is not None:
            total += sum((h for _, h in f.hit_dist), np.zeros(len(levels)))
        else:
            total += f.amount
    return {"levels": np.asarray(levels).tolist(), "cash": total.tolist(), "n_flows": len(flows)}


@dataclass
class ProfileResult:
    x: list[float]
    x_label: str
    series: dict[str, list[float]]
    unhedged: list[float]
    zones: list[dict[str, Any]]
    summary: list[str]
    convention: str
    forward: float
    exposure: float

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict
        return asdict(self)


def _worse_reason(trade: Trade) -> tuple[str, str]:
    """(короткая метка зоны, объяснение) — почему структура хуже позиции без хеджа на благоприятном движении."""
    comps = [c for leg in trade.legs for c in leg.components]
    mods = [m for c in comps for m in c.modifiers] + [m for leg in trade.legs for m in leg.modifiers] + list(trade.modifiers)
    if any(isinstance(m, LeverageMod) and m.factor > 1 for m in mods) or any(c.notional_multiplier > 1 + 1e-12 for c in comps):
        return "плечо на благоприятном движении", "клиент переплачивает из-за плеча: объём обязательства увеличен"
    if any(c.position == "short" and any(isinstance(m, BarrierMod) and m.kind == "in" for m in c.modifiers) for c in comps):
        return "обязательство после касания барьера", ("после касания барьера клиент обязан исполнить проданный опцион "
                                                       "по курсу защиты, хотя рынок выгоднее")
    if any(c.position == "short" for c in comps):
        return "проданный опцион", "выгода от благоприятного движения отдана банку через проданный опцион"
    if trade.premium is not None and trade.premium.payer == "client" and trade.premium.amount > 0:
        return "уплаченная премия", "уплаченная премия: защита не понадобилась, а её стоимость уже понесена"
    return "фиксация уровня", "уровень зафиксирован: выгода от благоприятного движения не достаётся клиенту"


def hedge_profile(trade: Trade, alternatives: list[tuple[str, Trade]], ctx, purpose: str, exposure_units: float,
                  center: float, span: float = 0.4, n: int = 161, x_label: str = "курс на дату исполнения",
                  upfront: dict[str, float] | None = None) -> ProfileResult:
    """Эффективный курс (ставка) хеджера по структуре и альтернативам.

    purpose: 'buy_fx' / 'buy_commodity' (защита от роста) или 'sell_fx' / 'sell_commodity' (от падения),
    'pay_floating' (заёмщик по плавающей ставке).
    exposure_units — объём реальной позиции клиента за весь срок (в единицах базиса;
    для ставки — номинал × срок, т.е. сумма τ·N).
    """
    lo, hi = center * (1 - span), center * (1 + span)
    if purpose == "pay_floating":
        lo, hi = max(center - 0.08, 0.0), center + 0.12
    x = np.linspace(lo, hi, n)
    buyer = purpose in ("buy_fx", "buy_commodity", "pay_floating")
    series = {}
    for label, tr in [("Предложенная структура", trade)] + alternatives:
        cash = np.asarray(scenario_cash(tr, ctx, x)["cash"])
        per_unit = (cash - (upfront or {}).get(label, 0.0)) / max(exposure_units, 1e-12)
        eff = x - per_unit if buyer else x + per_unit
        series[label] = eff.tolist()
    unhedged = x.tolist()
    eff_s = np.asarray(series["Предложенная структура"])
    zones = []
    summary = []
    # «хуже, чем без хеджа»: эффективный курс хуже рынка
    worse = (eff_s > x + 1e-9 * center) if buyer else (eff_s < x - 1e-9 * center)
    short_reason, long_reason = _worse_reason(trade)
    what = "курс" if "fx" in purpose else "уровень"
    for a, b in _intervals(x, worse):
        zones.append({"type": "worse_than_unhedged", "from": a, "to": b,
                      "label": f"хуже, чем без хеджа ({short_reason})"})
        adverse_side = a >= center if buyer else b <= center
        if adverse_side:   # неблагоприятное движение: защита не действует, а издержки структуры остаются
            summary.append(f"При уровне {_fmt(a)}–{_fmt(b)} эффективный {what} хуже рыночного: защиты нет, "
                           f"а издержки структуры остаются ({short_reason})")
        else:
            summary.append(f"При уровне {_fmt(a)}–{_fmt(b)} эффективный {what} хуже рыночного: {long_reason}")
    # «защита не работает»: на неблагоприятном движении защита сначала действовала, а затем отключилась
    slope = np.gradient(eff_s, x)
    order = np.arange(len(x)) if buyer else np.arange(len(x))[::-1]
    protected_seen = False
    off = np.zeros(len(x), bool)
    for i in order:
        adverse = x[i] > center if buyer else x[i] < center
        if not adverse:
            continue
        if abs(slope[i]) < 0.1:
            protected_seen = True
        elif protected_seen and abs(slope[i]) > 0.5:
            off[i] = True
    protected = np.abs(slope) < 0.1
    for a, b in _intervals(x, off):
        # если дальше по неблагоприятному направлению защита снова включается — это коридор по конструкции
        # (коллар, participating), а не отключение защиты
        beyond = (x > b) if buyer else (x < a)
        if np.any(protected & beyond):
            zones.append({"type": "corridor", "from": a, "to": b,
                          "label": "коридор без защиты: уровень следует за рынком до следующего страйка"})
            summary.append(f"При уровне {_fmt(a)}–{_fmt(b)} — коридор без защиты по конструкции: эффективный уровень "
                           f"следует за рынком, защита снова действует дальше")
            continue
        zones.append({"type": "protection_off", "from": a, "to": b,
                      "label": "защита отключается: эффективный уровень следует за рынком"})
        summary.append(f"При уровне {_fmt(a)}–{_fmt(b)} структура перестаёт защищать: эффективный уровень снова "
                       f"движется вместе с рынком (барьер отключения или достижение цели)")
    if not summary:
        summary.append("Во всём рассмотренном диапазоне структура защищает и не хуже позиции без хеджа")
    return ProfileResult(x.tolist(), x_label, series, unhedged, zones, summary,
                         "сценарий: скачок к уровню сразу после даты оценки и далее без изменений; суммы без дисконтирования",
                         center, exposure_units)


def _intervals(x: np.ndarray, mask: np.ndarray) -> list[tuple[float, float]]:
    out = []
    i = 0
    n = len(x)
    while i < n:
        if mask[i]:
            j = i
            while j + 1 < n and mask[j + 1]:
                j += 1
            if j > i:
                out.append((float(x[i]), float(x[j])))
            i = j + 1
        else:
            i += 1
    return out


def _fmt(v: float) -> str:
    return f"{v:.4f}" if abs(v) < 1 else f"{v:,.2f}".replace(",", " ")
