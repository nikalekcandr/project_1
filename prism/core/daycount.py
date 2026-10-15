"""Базисы расчёта (day count conventions).

ACT/365F — рублёвые потоки; ACT/360 — USD, EUR, CNY; 30/360 — отдельные
купонные структуры. Базис задаётся на уровне ноги сделки и не выводит
лаги фиксинга/платежа.
"""
from __future__ import annotations

import calendar as _cal
from datetime import date
from enum import Enum


class DayCount(str, Enum):
    ACT_365F = "ACT/365F"
    ACT_360 = "ACT/360"
    ACT_ACT_ISDA = "ACT/ACT"
    THIRTY_360 = "30/360"      # US bond basis
    THIRTY_E_360 = "30E/360"   # Eurobond basis
    ACT_364 = "ACT/364"

    @classmethod
    def parse(cls, s: "str | DayCount") -> "DayCount":
        if isinstance(s, DayCount):
            return s
        key = s.strip().upper().replace(" ", "")
        aliases = {
            "ACT/365": cls.ACT_365F, "ACT/365F": cls.ACT_365F, "ACT/365FIXED": cls.ACT_365F, "A365F": cls.ACT_365F,
            "ACT/360": cls.ACT_360, "A360": cls.ACT_360,
            "ACT/ACT": cls.ACT_ACT_ISDA, "ACT/ACTISDA": cls.ACT_ACT_ISDA,
            "30/360": cls.THIRTY_360, "30U/360": cls.THIRTY_360, "BONDBASIS": cls.THIRTY_360,
            "30E/360": cls.THIRTY_E_360, "EUROBOND": cls.THIRTY_E_360,
            "ACT/364": cls.ACT_364,
        }
        if key not in aliases:
            raise ValueError(f"неизвестный базис: {s!r}")
        return aliases[key]

    def year_fraction(self, d0: date, d1: date) -> float:
        if self is DayCount.ACT_365F:
            return (d1 - d0).days / 365.0
        if self is DayCount.ACT_360:
            return (d1 - d0).days / 360.0
        if self is DayCount.ACT_364:
            return (d1 - d0).days / 364.0
        if self is DayCount.ACT_ACT_ISDA:
            return _act_act_isda(d0, d1)
        if self is DayCount.THIRTY_360:
            return _thirty_360_us(d0, d1)
        if self is DayCount.THIRTY_E_360:
            return _thirty_e_360(d0, d1)
        raise AssertionError(self)


def _act_act_isda(d0: date, d1: date) -> float:
    if d1 < d0:
        return -_act_act_isda(d1, d0)
    if d0.year == d1.year:
        return (d1 - d0).days / (366.0 if _cal.isleap(d0.year) else 365.0)
    out = (date(d0.year + 1, 1, 1) - d0).days / (366.0 if _cal.isleap(d0.year) else 365.0)
    out += d1.year - d0.year - 1
    out += (d1 - date(d1.year, 1, 1)).days / (366.0 if _cal.isleap(d1.year) else 365.0)
    return out


def _thirty_360_us(d0: date, d1: date) -> float:
    dd0, dd1 = d0.day, d1.day
    if dd0 == 31:
        dd0 = 30
    if dd1 == 31 and dd0 == 30:
        dd1 = 30
    return (360 * (d1.year - d0.year) + 30 * (d1.month - d0.month) + (dd1 - dd0)) / 360.0


def _thirty_e_360(d0: date, d1: date) -> float:
    dd0, dd1 = min(d0.day, 30), min(d1.day, 30)
    return (360 * (d1.year - d0.year) + 30 * (d1.month - d0.month) + (dd1 - dd0)) / 360.0


DEFAULT_DAYCOUNT = {
    "RUB": DayCount.ACT_365F,
    "USD": DayCount.ACT_360,
    "EUR": DayCount.ACT_360,
    "CNY": DayCount.ACT_360,
    "CNH": DayCount.ACT_360,
    "HKD": DayCount.ACT_365F,
    "AED": DayCount.ACT_360,
    "TRY": DayCount.ACT_360,
    "KZT": DayCount.ACT_365F,
    "BYN": DayCount.ACT_365F,
    "INR": DayCount.ACT_365F,
}


def default_daycount(ccy: str) -> DayCount:
    return DEFAULT_DAYCOUNT.get(ccy.upper(), DayCount.ACT_365F)
