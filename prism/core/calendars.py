"""Календари рабочих дней.

Российский производственный календарь не генерируется алгоритмически:
переносы выходных устанавливаются ежегодным постановлением Правительства.
Поэтому календари РФ и КНР — загружаемые таблицы (``prism/data/calendars``,
плюс каталог из переменной окружения ``PRISM_CALENDAR_DIR``). За пределами
загруженных лет используется явное правило экстраполяции, и каждая такая
дата помечается флагом, который доходит до отчёта.

Календари USD (ФРС) и EUR (TARGET2) задаются правилами — они стабильны.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from .dates import BDC

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "calendars"


@dataclass(frozen=True)
class YearData:
    holidays: frozenset[date]
    working_weekends: frozenset[date]
    extrapolated: bool = False
    note: str = ""


@dataclass
class BusinessCalendar:
    code: str
    name: str
    weekend: frozenset[int] = frozenset({5, 6})
    source: str = ""
    status: str = "rule"
    verification_note: str = ""
    _years: dict[int, YearData] = field(default_factory=dict, repr=False)
    _rule: str | None = None
    _rule_data: dict = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------ data
    def year(self, y: int) -> YearData:
        yd = self._years.get(y)
        if yd is None:
            yd = _extrapolate(self, y)
            self._years[y] = yd
        return yd

    def covered_years(self) -> list[int]:
        return sorted(y for y, yd in self._years.items() if not yd.extrapolated)

    def coverage_flags(self, dates: Iterable[date]) -> list[str]:
        """Пометки для дат, попадающих в экстраполированные годы."""
        years = sorted({d.year for d in dates})
        out = []
        for y in years:
            yd = self.year(y)
            if yd.extrapolated:
                out.append(f"Календарь {self.code} на {y} г. не загружен: {yd.note}")
        return out

    # -------------------------------------------------------------- queries
    def is_business_day(self, d: date) -> bool:
        yd = self.year(d.year)
        if d in yd.holidays:
            return False
        if d.weekday() in self.weekend:
            return d in yd.working_weekends
        return True

    def is_holiday(self, d: date) -> bool:
        return not self.is_business_day(d)

    def adjust(self, d: date, bdc: BDC | str = BDC.MODIFIED_FOLLOWING) -> date:
        bdc = BDC(bdc)
        if bdc is BDC.UNADJUSTED or self.is_business_day(d):
            return d
        if bdc in (BDC.FOLLOWING, BDC.MODIFIED_FOLLOWING):
            out = d
            while not self.is_business_day(out):
                out += timedelta(days=1)
            if bdc is BDC.MODIFIED_FOLLOWING and out.month != d.month:
                return self.adjust(d, BDC.PRECEDING)
            return out
        out = d
        while not self.is_business_day(out):
            out -= timedelta(days=1)
        if bdc is BDC.MODIFIED_PRECEDING and out.month != d.month:
            return self.adjust(d, BDC.FOLLOWING)
        return out

    def advance_business_days(self, d: date, n: int) -> date:
        step = 1 if n >= 0 else -1
        out = d
        if n == 0:
            return self.adjust(d, BDC.FOLLOWING)
        k = abs(n)
        while k > 0:
            out += timedelta(days=step)
            if self.is_business_day(out):
                k -= 1
        return out

    def business_days_between(self, d0: date, d1: date, include_end: bool = False) -> int:
        """Число рабочих дней в [d0, d1) (или [d0, d1] при include_end)."""
        n, d = 0, d0
        while d < d1 or (include_end and d == d1):
            if self.is_business_day(d):
                n += 1
            d += timedelta(days=1)
        return n

    def business_days(self, d0: date, d1: date) -> list[date]:
        out, d = [], d0
        while d <= d1:
            if self.is_business_day(d):
                out.append(d)
            d += timedelta(days=1)
        return out

    def describe(self) -> dict:
        return {"code": self.code, "name": self.name, "source": self.source, "status": self.status,
                "covered_years": self.covered_years(), "verification_note": self.verification_note}


@dataclass
class JointCalendar(BusinessCalendar):
    """Объединённый календарь: рабочий день, если он рабочий во всех составляющих."""
    members: tuple[BusinessCalendar, ...] = ()

    def is_business_day(self, d: date) -> bool:
        return all(c.is_business_day(d) for c in self.members)

    def coverage_flags(self, dates: Iterable[date]) -> list[str]:
        dates = list(dates)
        out: list[str] = []
        for c in self.members:
            for f in c.coverage_flags(dates):
                if f not in out:
                    out.append(f)
        return out

    def covered_years(self) -> list[int]:
        sets = [set(c.covered_years()) for c in self.members]
        return sorted(set.intersection(*sets)) if sets else []


# ---------------------------------------------------------------------------
# Правила (rule-based)
# ---------------------------------------------------------------------------

def _easter(y: int) -> date:
    a = y % 19
    b, c = divmod(y, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = ((h + l_ - 7 * m + 114) % 31) + 1
    return date(y, month, day)


def _nth_weekday(y: int, m: int, wd: int, n: int) -> date:
    if n > 0:
        d = date(y, m, 1)
        d += timedelta(days=(wd - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)
    d = date(y + (m // 12), m % 12 + 1, 1) - timedelta(days=1)
    d -= timedelta(days=(d.weekday() - wd) % 7)
    return d


def _observed_us(d: date) -> date:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def _us_year(y: int) -> YearData:
    hs = {
        _observed_us(date(y, 1, 1)),
        _nth_weekday(y, 1, 0, 3),   # MLK
        _nth_weekday(y, 2, 0, 3),   # Presidents
        _nth_weekday(y, 5, 0, -1),  # Memorial
        _observed_us(date(y, 6, 19)),
        _observed_us(date(y, 7, 4)),
        _nth_weekday(y, 9, 0, 1),   # Labor
        _nth_weekday(y, 10, 0, 2),  # Columbus
        _observed_us(date(y, 11, 11)),
        _nth_weekday(y, 11, 3, 4),  # Thanksgiving
        _observed_us(date(y, 12, 25)),
    }
    return YearData(frozenset(h for h in hs if h.year == y), frozenset())


def _target_year(y: int) -> YearData:
    e = _easter(y)
    hs = {date(y, 1, 1), e - timedelta(days=2), e + timedelta(days=1), date(y, 5, 1), date(y, 12, 25), date(y, 12, 26)}
    return YearData(frozenset(hs), frozenset())


_RU_STATUTORY = [(1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6), (1, 7), (1, 8), (2, 23), (3, 8), (5, 1), (5, 9), (6, 12), (11, 4)]


def _ru_tk112(y: int) -> YearData:
    """Экстраполяция по ст. 112 ТК РФ: праздники; совпавшие с выходными (кроме
    январских) переносятся на следующий рабочий день. Переносы по постановлению
    Правительства неизвестны — это помечается."""
    hs: set[date] = set()
    for m, d in _RU_STATUTORY:
        hs.add(date(y, m, d))
    for m, d in _RU_STATUTORY:
        if m == 1:
            continue
        dd = date(y, m, d)
        if dd.weekday() >= 5:
            nxt = dd + timedelta(days=1)
            while nxt.weekday() >= 5 or nxt in hs:
                nxt += timedelta(days=1)
            hs.add(nxt)
    return YearData(frozenset(hs), frozenset(), True,
                    "применено правило ст. 112 ТК РФ без переносов по постановлению Правительства")


def _cn_approx(y: int, lny: date | None) -> YearData:
    hs = {date(y, 1, 1), date(y, 5, 1), date(y, 5, 2), date(y, 5, 3)}
    hs |= {date(y, 10, d) for d in range(1, 8)}
    note = "приближение: фиксированные праздники КНР"
    if lny is not None:
        hs |= {lny + timedelta(days=k) for k in range(-1, 7)}
        note += f", Новый год по лунному календарю ({lny.isoformat()}) — 8 дней"
    else:
        note += "; дата Нового года по лунному календарю неизвестна — КРИТИЧНО для CNY/RUB"
    return YearData(frozenset(h for h in hs if h.weekday() < 5), frozenset(), True, note)


def _weekends_only(y: int) -> YearData:
    return YearData(frozenset(), frozenset(), True, "только выходные дни, праздники не загружены")


def _extrapolate(cal: BusinessCalendar, y: int) -> YearData:
    rule = cal._rule
    if rule == "US":
        return _us_year(y)
    if rule == "TARGET":
        return _target_year(y)
    if rule == "RU_TK112":
        return _ru_tk112(y)
    if rule == "CN_APPROX":
        lny = cal._rule_data.get("lunar_new_year", {}).get(str(y))
        return _cn_approx(y, date.fromisoformat(lny) if lny else None)
    return _weekends_only(y)


# ---------------------------------------------------------------------------
# Реестр
# ---------------------------------------------------------------------------

def _load_json_calendar(path: Path) -> BusinessCalendar:
    raw = json.loads(path.read_text(encoding="utf-8"))
    cal = BusinessCalendar(
        code=raw["code"], name=raw.get("name", raw["code"]),
        weekend=frozenset(raw.get("weekend", [5, 6])), source=raw.get("source", ""),
        status=raw.get("status", "loaded"), verification_note=raw.get("verification_note", ""),
    )
    for y, yd in raw.get("years", {}).items():
        cal._years[int(y)] = YearData(
            frozenset(date.fromisoformat(s) for s in yd.get("holidays", [])),
            frozenset(date.fromisoformat(s) for s in yd.get("working_weekends", [])),
            False, yd.get("act", ""),
        )
    cal._rule = raw.get("extrapolation_rule")
    cal._rule_data = {k: v for k, v in raw.items() if k not in ("years",)}
    return cal


CCY_CALENDAR = {
    "RUB": "RU", "USD": "US", "EUR": "TARGET", "CNY": "CN", "CNH": "HK", "HKD": "HK",
    "AED": "AE", "TRY": "TR", "KZT": "KZ", "BYN": "BY", "INR": "IN", "GBP": "GB",
}


@lru_cache(maxsize=None)
def _base_calendar(code: str) -> BusinessCalendar:
    code = code.upper()
    dirs = [DATA_DIR]
    extra = os.environ.get("PRISM_CALENDAR_DIR")
    if extra:
        dirs.insert(0, Path(extra))
    for d in dirs:
        p = d / f"{code}.json"
        if p.exists():
            return _load_json_calendar(p)
    if code == "US":
        return BusinessCalendar("US", "США — расчётный календарь USD (ФРС)", source="правила ФРС США", status="rule", _rule="US")
    if code == "TARGET":
        return BusinessCalendar("TARGET", "TARGET2 — расчётный календарь EUR", source="правила ЕЦБ TARGET2", status="rule", _rule="TARGET")
    if code == "WEEKENDS":
        return BusinessCalendar("WEEKENDS", "Только выходные", status="rule", _rule="WEEKENDS")
    # прочие валюты: только выходные, с явной пометкой
    return BusinessCalendar(code, f"{code} — календарь не загружен (только выходные)", status="missing", _rule="WEEKENDS",
                            verification_note="Праздники не загружены: расчётные даты могут быть смещены.")


def get_calendar(spec: str) -> BusinessCalendar:
    """``"RU"``, ``"RUB"`` (по валюте), ``"RU+CN"`` / ``"RUB+CNY"`` — объединённый."""
    parts = [p.strip().upper() for p in spec.replace(",", "+").split("+") if p.strip()]
    codes = [CCY_CALENDAR.get(p, p) for p in parts]
    codes = list(dict.fromkeys(codes))
    if len(codes) == 1:
        return _base_calendar(codes[0])
    members = tuple(_base_calendar(c) for c in codes)
    return JointCalendar(code="+".join(codes), name=" + ".join(m.name for m in members), members=members,
                         status="joint", source="объединение календарей")


def pair_calendar(ccy1: str, ccy2: str) -> BusinessCalendar:
    return get_calendar(f"{ccy1}+{ccy2}")
