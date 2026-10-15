"""Прогнозная кривая ИПЦ Росстата.

* базовый месяц — последний опубликованный на дату оценки (по календарю
  публикаций Росстата — входные данные);
* опорные точки — нулевые инфляционные ставки (ZCIS) или безубыточная
  инфляция ОФЗ-ИН против обычных ОФЗ той же дюрации;
* сезонность моделируется явно (мультипликативные месячные факторы, сумма
  лог-факторов за год = 0, поэтому годовые точки воспроизводятся точно) —
  иначе короткие сделки систематически смещены;
* первая публикация и уточнённая величина хранятся раздельно; контракт
  указывает, какая применяется.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np

from ..core.provenance import DataKind, InputTracker, Provenance, UsedInput


def month_key(y: int, m: int) -> str:
    return f"{y:04d}-{m:02d}"


def parse_month(s: str) -> tuple[int, int]:
    y, m = s.split("-")[:2]
    return int(y), int(m)


def add_m(ym: tuple[int, int], k: int) -> tuple[int, int]:
    y, m = ym
    n = y * 12 + (m - 1) + k
    return n // 12, n % 12 + 1


def months_between(a: tuple[int, int], b: tuple[int, int]) -> int:
    return (b[0] * 12 + b[1]) - (a[0] * 12 + a[1])


def estimate_seasonality(index: dict[str, float], years: int = 5) -> np.ndarray:
    """Месячные сезонные лог-факторы s[1..12] (сумма = 0) по истории индекса."""
    keys = sorted(index)
    mom = {}
    for k0, k1 in zip(keys, keys[1:]):
        mom[k1] = np.log(index[k1] / index[k0])
    by_year: dict[int, dict[int, float]] = {}
    for k, v in mom.items():
        y, m = parse_month(k)
        by_year.setdefault(y, {})[m] = v
    full = sorted(y for y, d in by_year.items() if len(d) == 12)[-years:]
    if not full:
        return np.zeros(12)
    dev = np.zeros(12)
    for y in full:
        arr = np.array([by_year[y][m] for m in range(1, 13)])
        dev += arr - arr.mean()
    dev /= len(full)
    return dev - dev.mean()


@dataclass
class CPICurve:
    ref_date: date
    history_first: dict[str, float]
    history_revised: dict[str, float]
    published: dict[str, str]                  # месяц → дата публикации
    pillars_years: np.ndarray                  # T, лет от базового месяца
    pillar_rates: np.ndarray                   # годовая инфляция (ZC), доли
    seasonality: np.ndarray = field(default_factory=lambda: np.zeros(12))
    inputs: list[UsedInput] = field(default_factory=list)
    shock: float = 0.0                         # параллельный сдвиг годовой инфляции

    def __post_init__(self):
        pub = [k for k, d in self.published.items() if d and date.fromisoformat(d) <= self.ref_date]
        if not pub:
            pub = sorted(self.history_first)
        self.base_month = parse_month(max(pub))
        self.base_index = self.history_revised.get(month_key(*self.base_month)) or self.history_first[month_key(*self.base_month)]

    def is_published(self, ym: tuple[int, int]) -> bool:
        d = self.published.get(month_key(*ym))
        return bool(d) and date.fromisoformat(d) <= self.ref_date

    def index(self, ym: tuple[int, int], version: str = "revised") -> tuple[float, str]:
        k = month_key(*ym)
        if self.is_published(ym):
            src = self.history_revised if version == "revised" and k in self.history_revised else self.history_first
            return float(src[k]), f"опубликовано ({'уточн.' if src is self.history_revised else 'первая публ.'})"
        n = months_between(self.base_month, ym)
        if n <= 0:
            # месяц раньше базового, но не опубликован в выбранной версии — берём доступную
            return float(self.history_first.get(k, self.base_index)), "история"
        t = n / 12.0
        z = np.log1p(np.interp(t, self.pillars_years, self.pillar_rates) + self.shock)
        seas = sum(self.seasonality[add_m(self.base_month, j)[1] - 1] for j in range(1, n + 1))
        return float(self.base_index * np.exp(z * t + seas)), "прогноз"

    def index_for_date(self, d: date, lag_months: int = 3, interpolate: bool = False,
                       version: str = "revised") -> float:
        ym = add_m((d.year, d.month), -lag_months)
        i0, _ = self.index(ym, version)
        if not interpolate:
            return i0
        i1, _ = self.index(add_m(ym, 1), version)
        nd = ((date(*add_m((d.year, d.month), 1), 1) - date(d.year, d.month, 1)).days)
        w = (d.day - 1) / nd
        return i0 + w * (i1 - i0)

    def register(self, tracker: InputTracker | None, role: str = "") -> None:
        if tracker is None:
            return
        for u in self.inputs:
            tracker.record(u)
        tracker.record(UsedInput("cpi:seasonality", [round(float(x), 6) for x in self.seasonality],
                                 Provenance("оценка сезонности по истории ИПЦ Росстата", None, DataKind.HISTORICAL),
                                 role or "сезонность ИПЦ"))

    def with_shock(self, dz: float) -> "CPICurve":
        c = CPICurve(self.ref_date, self.history_first, self.history_revised, self.published, self.pillars_years,
                     self.pillar_rates, self.seasonality, self.inputs, self.shock + dz)
        return c

    def describe(self) -> dict[str, Any]:
        return {"base_month": month_key(*self.base_month), "base_index": self.base_index,
                "pillars": [{"t": float(t), "rate": float(r)} for t, r in zip(self.pillars_years, self.pillar_rates)],
                "seasonality": [float(x) for x in self.seasonality]}


def default_publication_date(ym: tuple[int, int]) -> date:
    """Правило-фоллбэк: ИПЦ за месяц публикуется около 12-го числа следующего месяца."""
    y, m = add_m(ym, 1)
    return date(y, m, 12) + timedelta(days=0)
