"""Товарные форвардные кривые с явной сезонностью.

* форварды по месяцам поставки (котировки контрактов/индексов);
* для месяцев без котировок — сезонный профиль (мультипликативные
  месячные факторы) вокруг тренда между котируемыми точками; для газа,
  электроэнергии и агро сезонность определяет цену сильнее уровня;
* единицы измерения и коэффициенты пересчёта — часть описания базиса, а не
  захардкоженные константы;
* признак отсутствия торгуемого хеджа: риск-нейтральная оценка
  некорректна, отчёт обязан это указать.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np

from ..core.provenance import InputTracker, UsedInput

UNIT_CONVERSIONS = {
    # единица → (базовая единица, множитель); значения конвенционные и
    # переопределяются в описании инструмента при наличии договорных коэффициентов
    ("t", "bbl"): 7.33,        # Urals: баррелей в метрической тонне (типичная договорная конвенция)
    ("mmbtu", "mwh"): 0.293071,
    ("troy_oz", "g"): 31.1034768,
    ("kg", "troy_oz"): 32.1507466,
}


@dataclass
class CommodityCurve:
    asset: str
    ref_date: date
    currency: str
    unit: str
    months: list[tuple[int, int]]          # котируемые месяцы поставки
    prices: np.ndarray                     # форварды по котируемым месяцам
    seasonality: np.ndarray = field(default_factory=lambda: np.ones(12))
    tradeable_hedge: bool = True
    pricing_note: str = ""
    inputs: list[UsedInput] = field(default_factory=list)
    roll_rule: str = "last_business_day_before_delivery_month"
    shock: float = 1.0

    def _mi(self, ym: tuple[int, int]) -> float:
        return ym[0] * 12 + (ym[1] - 1)

    def forward_month(self, ym: tuple[int, int]) -> float:
        """Форвард на месяц поставки с сезонностью для некотируемых месяцев."""
        x = np.array([self._mi(m) for m in self.months], dtype=float)
        s = np.array([self.seasonality[m[1] - 1] for m in self.months])
        deseason = np.log(self.prices / s)
        xm = self._mi(ym)
        if xm <= x[0]:
            base = deseason[0]
        elif xm >= x[-1]:
            base = deseason[-1]
        else:
            base = np.interp(xm, x, deseason)
        for m, p in zip(self.months, self.prices):
            if m == ym:
                return float(p) * self.shock
        return float(np.exp(base) * self.seasonality[ym[1] - 1]) * self.shock

    def forward(self, d: date) -> float:
        return self.forward_month((d.year, d.month))

    def forward_t(self, t: np.ndarray) -> np.ndarray:
        """Векторно: форвард месяца поставки, содержащего дату ref + t·365 дней."""
        t = np.atleast_1d(np.asarray(t, float))
        days = np.round(t * 365).astype("int64")
        d64 = np.datetime64(self.ref_date, "D") + days
        months = d64.astype("datetime64[M]").astype("int64")          # месяцы от 1970-01
        mi = np.array([(y - 1970) * 12 + (m - 1) for (y, m) in self.months], dtype=float)
        s = np.array([self.seasonality[m - 1] for (_, m) in self.months])
        deseason = np.log(self.prices / s)
        base = np.interp(months.astype(float), mi, deseason)
        cal_month = (months % 12).astype(int)
        out = np.exp(base) * self.seasonality[cal_month]
        # котируемые месяцы — точные котировки
        lookup = {int(k): float(p) for k, p in zip(mi, self.prices)}
        exact = np.array([lookup.get(int(m), np.nan) for m in months])
        out = np.where(np.isnan(exact), out, exact)
        return out * self.shock

    def with_shock(self, f: float) -> "CommodityCurve":
        return CommodityCurve(self.asset, self.ref_date, self.currency, self.unit, self.months, self.prices,
                              self.seasonality, self.tradeable_hedge, self.pricing_note, self.inputs, self.roll_rule,
                              self.shock * f)

    def register(self, tracker: InputTracker | None, role: str = "") -> None:
        if tracker is None:
            return
        for u in self.inputs:
            tracker.record(u)
        if not self.tradeable_hedge:
            tracker.warn(f"Базис {self.asset}: нет ликвидного торгуемого хеджа — риск-нейтральная оценка "
                         f"некорректна, результат помечен как оценка по исторической мере")

    def describe(self) -> dict[str, Any]:
        return {"asset": self.asset, "unit": self.unit, "currency": self.currency,
                "tradeable_hedge": self.tradeable_hedge,
                "points": [{"month": f"{y}-{m:02d}", "price": float(p)} for (y, m), p in zip(self.months, self.prices)]}


@dataclass
class EquityForward:
    """Форвард на акцию/индекс с дискретными дивидендами и ставкой заимствования бумаги."""
    asset: str
    ref_date: date
    spot: float
    currency: str
    dividends: list[tuple[date, float]]    # (экс-дата, сумма)
    borrow: float = 0.0                    # ставка заимствования (repo/lending fee), непрерывная
    inputs: list[UsedInput] = field(default_factory=list)
    shock: float = 1.0

    def pv_dividends(self, t_end: float, disc) -> float:
        pv = 0.0
        for d, amt in self.dividends:
            t = (d - self.ref_date).days / 365.0
            if 0 < t <= t_end:
                pv += amt * float(disc.df(t))
        return pv

    def forward_t(self, t, disc) -> np.ndarray:
        t = np.atleast_1d(np.asarray(t, dtype=float))
        s = self.spot * self.shock
        out = np.empty_like(t)
        for i, tt in enumerate(t):
            out[i] = (s - self.pv_dividends(tt, disc)) * np.exp(-self.borrow * tt) / float(disc.df(tt))
        return out

    def dividend_times(self) -> list[tuple[float, float]]:
        return [((d - self.ref_date).days / 365.0, a) for d, a in self.dividends if d > self.ref_date]

    def with_shock(self, f: float) -> "EquityForward":
        return EquityForward(self.asset, self.ref_date, self.spot, self.currency, self.dividends, self.borrow,
                             self.inputs, self.shock * f)

    def register(self, tracker: InputTracker | None, role: str = "") -> None:
        if tracker is None:
            return
        for u in self.inputs:
            tracker.record(u)
