"""Компиляция сделки в форму для движков.

Сделка → ноги с развёрнутыми периодами (даты фиксинга, наблюдений, платежей,
номиналы с учётом амортизации), разрешённой наблюдаемой величиной и
модификаторами. Компиляция не зависит от рынка, кроме даты оценки.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np

from ..core.calendars import get_calendar
from ..core.dates import BDC
from ..core.daycount import DayCount
from ..core.schedule import Period, Schedule, explicit_periods, generate_periods, roll_dates
from ..instruments.schema import (AssetObs, AveragingMod, BarrierMod, Component, CPIObs, Leg, Modifier, RateObs,
                                  RealizedVarObs, SettlementSpec, Trade)


@dataclass
class CPeriod:
    idx: int
    start: date
    end: date
    fixing: date
    payment: date
    tau: float
    notional: float
    obs_dates: tuple[date, ...] = ()
    obs_weights: tuple[float, ...] = ()
    weight: float = 1.0


@dataclass
class CLeg:
    name: str
    spec: Leg
    observable: object
    periods: list[CPeriod]
    currency: str
    settlement: SettlementSpec
    components: list[Component]
    modifiers: list[Modifier]
    daycount: DayCount
    flags: list[str] = field(default_factory=list)

    def averaging(self, comp: Component | None = None) -> AveragingMod | None:
        mods = list(self.modifiers) + (list(comp.modifiers) if comp is not None else [])
        for m in mods:
            if isinstance(m, AveragingMod):
                return m
        return None

    @property
    def is_rate(self) -> bool:
        return isinstance(self.observable, RateObs)

    @property
    def is_cpi(self) -> bool:
        return isinstance(self.observable, CPIObs)


@dataclass
class CProduct:
    trade: Trade
    legs: list[CLeg]
    modifiers: list[Modifier]
    ref_date: date
    flags: list[str] = field(default_factory=list)

    @property
    def start(self) -> date:
        return self.trade.start

    @property
    def last_payment(self) -> date:
        return max(p.payment for leg in self.legs for p in leg.periods)

    def underlying_names(self) -> set[str]:
        out: set[str] = set()
        for leg in self.legs:
            out |= observable_names(leg.observable)
            for c in leg.components:
                for m in c.modifiers:
                    if getattr(m, "observable", None) is not None:
                        out |= observable_names(m.observable)
            for m in leg.modifiers:
                if getattr(m, "observable", None) is not None:
                    out |= observable_names(m.observable)
        return out

    def structure_modifier_types(self) -> set[str]:
        return {m.type for m in self.modifiers}

    def alive_periods(self) -> int:
        return sum(1 for leg in self.legs for p in leg.periods if p.payment > self.ref_date)


def observable_names(obs) -> set[str]:
    t = getattr(obs, "type", None)
    if t in ("asset", "performance", "realized_variance", "realized_vol"):
        return {obs.name}
    if t == "basket":
        return set(obs.names)
    if t == "spread":
        return {x["name"] for x in obs.terms}
    if t == "rate":
        return {"rate:" + obs.index}
    if t == "cpi":
        return {"cpi:" + obs.name}
    return set()


def _notional_at(leg: Leg, d: date) -> float:
    n = leg.notional
    if n is None:
        return 1.0
    amt = n.amount
    if n.schedule:
        for step in sorted(n.schedule, key=lambda s: s.date):
            if step.date <= d:
                amt = step.amount
    return amt


def _default_observable(trade: Trade, leg: Leg):
    if leg.observable is not None:
        return leg.observable
    name = leg.underlying
    if name is None:
        if len(trade.underlyings) == 1:
            name = next(iter(trade.underlyings))
        else:
            return None
    u = trade.underlyings[name]
    if u.asset_class == "rate":
        return RateObs(index=u.id)
    if u.asset_class == "inflation":
        return CPIObs(name=u.id)
    return AssetObs(name=name)


def compile_trade(trade: Trade, ref_date: date) -> CProduct:
    legs: list[CLeg] = []
    flags: list[str] = []
    for leg in trade.legs:
        s = leg.schedule
        cal = get_calendar(s.calendar)
        fcal = get_calendar(s.fixing_calendar) if s.fixing_calendar else cal
        pcal = get_calendar(s.payment_calendar) if s.payment_calendar else cal
        dc = DayCount.parse(s.daycount)
        avg = None
        for m in list(leg.modifiers) + [m for c in leg.components for m in c.modifiers]:
            if isinstance(m, AveragingMod):
                avg = m
        obs_freq = s.observation or (avg.frequency if avg and avg.frequency else ("daily" if avg else None))
        if s.dates:
            sched = explicit_periods(sorted(s.dates), sorted(s.payment_dates) if s.payment_dates else None, dc,
                                     start=s.start or trade.start)
            if obs_freq:
                # подрасписание наблюдений внутри явных периодов
                new = []
                for p in sched.periods:
                    if obs_freq == "daily":
                        ods = fcal.business_days(p.accrual_start, p.fixing_date) if new else fcal.business_days(p.accrual_start, p.fixing_date)
                        if new:
                            ods = [d for d in ods if d > p.accrual_start]
                    else:
                        ods = [fcal.adjust(d, BDC.PRECEDING) for d in roll_dates(p.accrual_start, p.fixing_date, obs_freq)[1:]]
                    ods = sorted(set(ods)) or [p.fixing_date]
                    new.append(Period(p.accrual_start, p.accrual_end, p.fixing_date, p.payment_date, p.accrual_fraction,
                                      tuple(ods), tuple(1.0 / len(ods) for _ in ods)))
                sched = Schedule(new, sched.flags)
            sched.flags.extend(cal.coverage_flags(s.dates))
        else:
            start = s.start or trade.start
            if s.end is None:
                raise ValueError(f"нога {leg.name}: не задан конец расписания")
            sched = generate_periods(start, s.end, s.frequency, cal, dc, BDC(s.bdc), backward=s.backward, eom=s.eom,
                                     fixing_lag=s.fixing_lag, fixing_in_arrears=s.fixing_in_arrears,
                                     fixing_calendar=fcal, payment_lag=s.payment_lag, payment_calendar=pcal,
                                     observation=obs_freq)
        periods = []
        for i, p in enumerate(sched.periods):
            w = s.weights[i] if s.weights and i < len(s.weights) else 1.0
            ow = p.observation_weights
            if avg is not None and avg.weights and len(avg.weights) == len(p.observation_dates):
                tot = sum(avg.weights)
                ow = tuple(x / tot for x in avg.weights)
            periods.append(CPeriod(i, p.accrual_start, p.accrual_end, p.fixing_date, p.payment_date, p.accrual_fraction,
                                   _notional_at(leg, p.accrual_start) * w, p.observation_dates, ow, w))
        obs = _default_observable(trade, leg)
        ccy = leg.currency or (leg.notional.currency if leg.notional and _is_rate_like(obs) else None)
        if ccy is None:
            ccy = _payment_ccy(trade, leg, obs)
        settle = leg.settlement or trade.settlement
        legs.append(CLeg(leg.name, leg, obs, periods, ccy, settle, list(leg.components), list(leg.modifiers), dc,
                         list(sched.flags)))
        for f in sched.flags:
            if f not in flags:
                flags.append(f)
    return CProduct(trade, legs, list(trade.modifiers), ref_date, flags)


def _is_rate_like(obs) -> bool:
    return isinstance(obs, (RateObs, CPIObs)) or obs is None


def _payment_ccy(trade: Trade, leg: Leg, obs) -> str:
    """Валюта выплаты ноги: котируемая валюта базиса (RUB для USDRUB), валюта цены товара/акции."""
    names = observable_names(obs) if obs is not None else set()
    for n in names:
        u = trade.underlyings.get(n)
        if u is None:
            continue
        if u.asset_class == "fx":
            return u.id[3:]
    if leg.notional is not None:
        return leg.notional.currency
    return trade.settlement.currency


def realized_var_obs(obs) -> bool:
    return isinstance(obs, RealizedVarObs)


def barrier_label(leg_name: str, comp_idx: int | None, mod_idx: int) -> str:
    return f"{leg_name}:{'leg' if comp_idx is None else comp_idx}:{mod_idx}"


def is_barrier(m) -> bool:
    return isinstance(m, BarrierMod)


def period_years(ref: date, d: date) -> float:
    return (d - ref).days / 365.0


def np_dates(ref: date, ds) -> np.ndarray:
    return np.array([(d - ref).days / 365.0 for d in ds])
