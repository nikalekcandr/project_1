"""Даты, сроки (тенора), правила переноса."""
from __future__ import annotations

import calendar as _cal
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:  # pragma: no cover
    from .calendars import BusinessCalendar

DateLike = Union[date, datetime, str]


def to_date(d: DateLike) -> date:
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    if isinstance(d, str):
        return date.fromisoformat(d[:10])
    raise TypeError(f"не дата: {d!r}")


class BDC(str, Enum):
    """Правило переноса даты на рабочий день (business day convention)."""
    FOLLOWING = "following"
    MODIFIED_FOLLOWING = "modified_following"
    PRECEDING = "preceding"
    MODIFIED_PRECEDING = "modified_preceding"
    UNADJUSTED = "unadjusted"


@dataclass(frozen=True)
class Tenor:
    n: int
    unit: str  # D, B (рабочие дни), W, M, Y

    _RX = re.compile(r"^\s*(\d+)\s*([DBWMY])\s*$", re.I)
    _SPECIAL = {"ON": (1, "B"), "TN": (2, "B"), "SN": (3, "B"), "TOD": (0, "B"), "TOM": (1, "B"), "SPOT": (2, "B")}

    @classmethod
    def parse(cls, s: "str | Tenor") -> "Tenor":
        if isinstance(s, Tenor):
            return s
        key = s.strip().upper()
        if key in cls._SPECIAL:
            n, u = cls._SPECIAL[key]
            return cls(n, u)
        m = cls._RX.match(key)
        if not m:
            raise ValueError(f"непонятный срок: {s!r}")
        return cls(int(m.group(1)), m.group(2).upper())

    def __str__(self) -> str:
        return f"{self.n}{self.unit}"

    @property
    def approx_years(self) -> float:
        return {"D": 1 / 365.0, "B": 1 / 252.0, "W": 7 / 365.0, "M": 1 / 12.0, "Y": 1.0}[self.unit] * self.n

    @property
    def months(self) -> int | None:
        if self.unit == "M":
            return self.n
        if self.unit == "Y":
            return 12 * self.n
        return None


def add_months(d: date, months: int, eom: bool = False) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    y += d.year
    m += 1
    last = _cal.monthrange(y, m)[1]
    if eom and d.day == _cal.monthrange(d.year, d.month)[1]:
        return date(y, m, last)
    return date(y, m, min(d.day, last))


def add_tenor(d: date, tenor: "str | Tenor", cal: "BusinessCalendar | None" = None,
              bdc: BDC = BDC.MODIFIED_FOLLOWING, eom: bool = False) -> date:
    t = Tenor.parse(tenor)
    if t.unit == "B":
        if cal is None:
            raise ValueError("для рабочих дней нужен календарь")
        return cal.advance_business_days(d, t.n)
    if t.unit == "D":
        out = d + timedelta(days=t.n)
    elif t.unit == "W":
        out = d + timedelta(weeks=t.n)
    else:
        out = add_months(d, t.months, eom)
    if cal is not None:
        out = cal.adjust(out, bdc)
    return out


def date_range(start: date, end: date) -> list[date]:
    n = (end - start).days
    return [start + timedelta(days=i) for i in range(n + 1)]


def year_fraction_act365(d0: date, d1: date) -> float:
    return (d1 - d0).days / 365.0
