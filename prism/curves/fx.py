"""Валютные форвардные кривые и диагностика покрытого процентного паритета.

Форвардная кривая строится из форвардных пунктов (рынок). Отдельно
вычисляется имплицированная рублёвая ставка из CIP и её базис к onshore-
ставке — базис сам по себе диагностичен. Для юаня различаются onshore CNY и
offshore CNH: разные кривые; для сделок внутри РФ применяется onshore.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np

from ..core.calendars import BusinessCalendar
from ..core.provenance import InputTracker, UsedInput
from .base import YieldCurve


@dataclass
class FXForwardCurve:
    pair: str                  # 'USDRUB' — цена 1 USD в RUB
    ref_date: date
    spot: float                # курс с расчётами в spot_date (TOM для рублёвых пар на Мосбирже)
    spot_date: date
    pillar_dates: list[date]
    outrights: np.ndarray      # аутрайт-форварды на pillar_dates
    calendar: BusinessCalendar | None = None
    inputs: list[UsedInput] = field(default_factory=list)
    spot_bid: float | None = None
    spot_ask: float | None = None
    points_halfspread: dict[str, float] = field(default_factory=dict)
    shock: float = 1.0         # мультипликативный шок курса (сценарии)
    carry: float = 0.0         # сдвиг ставки базовой валюты (ро иностранной валюты): F → F·exp(−carry·t)

    @property
    def base(self) -> str:
        return self.pair[:3]

    @property
    def quote(self) -> str:
        return self.pair[3:]

    def _t(self, d: date) -> float:
        return (d - self.spot_date).days / 365.0

    def forward(self, d: date | float) -> float:
        """Аутрайт на дату расчётов ``d`` (интерполяция log(F/S) линейно по времени)."""
        if not isinstance(d, date):
            t = float(d) - (self.spot_date - self.ref_date).days / 365.0
        else:
            t = self._t(d)
        ts = np.array([self._t(x) for x in self.pillar_dates])
        y = np.log(self.outrights / self.spot)
        ts = np.concatenate([[0.0], ts])
        y = np.concatenate([[0.0], y])
        if t <= ts[-1]:
            v = np.interp(t, ts, y) if t >= 0 else y[1] / ts[1] * t
        else:
            slope = (y[-1] - y[-2]) / (ts[-1] - ts[-2])
            v = y[-1] + slope * (t - ts[-1])
        tt = t + (self.spot_date - self.ref_date).days / 365.0
        return float(self.spot * np.exp(v)) * self.shock * float(np.exp(-self.carry * max(tt, 0.0)))

    def forward_t(self, t: np.ndarray | float) -> np.ndarray:
        """Аутрайт по времени ACT/365F от ref_date (векторно)."""
        t = np.atleast_1d(np.asarray(t, dtype=float))
        ts_off = (self.spot_date - self.ref_date).days / 365.0
        ts = np.concatenate([[0.0], np.array([self._t(x) for x in self.pillar_dates])])
        y = np.concatenate([[0.0], np.log(self.outrights / self.spot)])
        tt = t - ts_off
        slope_end = (y[-1] - y[-2]) / (ts[-1] - ts[-2])
        slope_0 = y[1] / ts[1]
        v = np.interp(tt, ts, y)
        v = np.where(tt > ts[-1], y[-1] + slope_end * (tt - ts[-1]), v)
        v = np.where(tt < 0, slope_0 * tt, v)
        return self.spot * np.exp(v) * self.shock * np.exp(-self.carry * np.maximum(t, 0.0))

    @property
    def spot_value(self) -> float:
        return self.spot * self.shock

    def spot_today(self) -> float:
        """Курс с расчётами сегодня (TOD), из наклона кривой к первой точке."""
        return float(self.forward_t(0.0)[0])

    def implied_foreign_curve(self, domestic: YieldCurve, cid: str | None = None) -> YieldCurve:
        """Имплицированная кривая базовой валюты, согласованная с аутрайтами:
        DFf(T) = F(T)/S_0 · DFd(T), где S_0 — курс TOD."""
        s0 = self.spot_today()
        ts = np.array([domestic.time(d) for d in self.pillar_dates])
        ts = ts[ts > 0]
        ly = np.log(self.forward_t(ts) / s0) + domestic.logdf_t(ts)
        return YieldCurve(cid or f"{self.base}.IMPLIED.{self.pair}", self.ref_date, ts, ly, "log_linear", self.base,
                          f"имплицированная из форвардных пунктов {self.pair} и кривой {domestic.id}",
                          inputs=list(self.inputs) + list(domestic.inputs))

    def register(self, tracker: InputTracker | None, role: str = "") -> None:
        if tracker is None:
            return
        for u in self.inputs:
            tracker.record(UsedInput(u.id, u.value, u.provenance, role or u.role, u.flags))

    def with_shock(self, factor: float) -> "FXForwardCurve":
        return FXForwardCurve(self.pair, self.ref_date, self.spot, self.spot_date, self.pillar_dates, self.outrights,
                              self.calendar, self.inputs, self.spot_bid, self.spot_ask, self.points_halfspread,
                              self.shock * factor, self.carry)

    def with_carry(self, dr: float) -> "FXForwardCurve":
        return FXForwardCurve(self.pair, self.ref_date, self.spot, self.spot_date, self.pillar_dates, self.outrights,
                              self.calendar, self.inputs, self.spot_bid, self.spot_ask, self.points_halfspread,
                              self.shock, self.carry + dr)

    def rolled(self, new_ref: date) -> "FXForwardCurve":
        # тета: «спот не меняется», форвардная кривая сдвигается по времени
        new_spot_date = self.spot_date + (new_ref - self.ref_date)
        ratio = self.spot / (self.forward(new_spot_date) / self.shock)
        keep = [i for i, x in enumerate(self.pillar_dates) if x > new_spot_date]
        return FXForwardCurve(self.pair, new_ref, self.spot, new_spot_date,
                              [self.pillar_dates[i] for i in keep], self.outrights[keep] * ratio,
                              self.calendar, self.inputs, self.spot_bid, self.spot_ask,
                              self.points_halfspread, self.shock, self.carry)


def cip_diagnostics(fx: FXForwardCurve, foreign: YieldCurve, domestic_onshore: YieldCurve,
                    foreign_dc: float = 360.0) -> list[dict[str, Any]]:
    """Имплицированная из CIP ставка котируемой (рублёвой) валюты и её базис к onshore.

    r_impl(T) — простая ставка ACT/365 такая, что
    (1 + r_impl·τ) = F/S · DFf(Ts)/DFf(T).
    """
    out = []
    for d, f in zip(fx.pillar_dates, fx.outrights):
        ts, tt = foreign.time(fx.spot_date), foreign.time(d)
        tau = (d - fx.spot_date).days / 365.0
        if tau <= 0:
            continue
        gross_f = foreign.df(ts) / foreign.df(tt)
        r_impl = ((f * fx.shock) / fx.spot_value * gross_f - 1.0) / tau
        r_on = float((domestic_onshore.df(ts) / domestic_onshore.df(tt) - 1.0) / tau)
        r_f = float((gross_f - 1.0) / ((d - fx.spot_date).days / foreign_dc))
        out.append({"date": d.isoformat(), "tenor_years": tau, "outright": float(f * fx.shock),
                    "points": float(f * fx.shock - fx.spot_value), "foreign_rate": r_f,
                    "implied_rate": float(r_impl), "onshore_rate": r_on,
                    "basis_bp": float((r_impl - r_on) * 1e4)})
    return out
