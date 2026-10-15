"""Кривые вероятностей дефолта (интенсивности) и прокси-методы.

Ликвидного рынка CDS в РФ нет, поэтому интенсивности строятся косвенно.
Допустимые методы в порядке предпочтения:

1. спред облигаций эмитента к ОФЗ (КБД) сопоставимой дюрации;
2. спред облигаций сопоставимых эмитентов той же отрасли и рейтинга;
3. маппинг рейтинга АКРА / Эксперт РА на кумулятивные вероятности дефолта
   по публикуемой статистике агентств (физическая мера — помечается).

Модуль общий: один источник кредитных кривых и для кредитных деривативов,
и для CVA по любой сделке. Метод и все входы фиксируются в объекте кривой.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Sequence

import numpy as np

from ..core.provenance import DataKind, InputTracker, Provenance, UsedInput
from .base import YieldCurve


@dataclass
class HazardCurve:
    entity: str
    ref_date: date
    times: np.ndarray          # концы сегментов, лет
    hazards: np.ndarray        # интенсивность на сегменте
    recovery: float = 0.4
    method: str = ""
    method_rank: int = 0       # 1, 2, 3 — порядок предпочтения; 0 — задано вручную
    details: dict[str, Any] = field(default_factory=dict)
    inputs: list[UsedInput] = field(default_factory=list)
    measure: str = "risk_neutral"   # или 'physical' для рейтингового маппинга
    hazard_mult: float = 1.0        # сценарный множитель

    def cum_hazard(self, t) -> np.ndarray:
        t = np.atleast_1d(np.asarray(t, dtype=float))
        edges = np.concatenate([[0.0], self.times])
        h = self.hazards * self.hazard_mult
        cum = np.concatenate([[0.0], np.cumsum(h * np.diff(edges))])
        i = np.clip(np.searchsorted(edges, t, side="right") - 1, 0, len(h) - 1)
        return cum[i] + h[i] * (t - edges[i])

    def survival(self, t) -> np.ndarray:
        return np.exp(-self.cum_hazard(np.maximum(t, 0.0)))

    def default_prob(self, t0, t1) -> np.ndarray:
        return self.survival(t0) - self.survival(t1)

    def hazard(self, t) -> np.ndarray:
        t = np.atleast_1d(np.asarray(t, dtype=float))
        i = np.clip(np.searchsorted(self.times, t, side="left"), 0, len(self.hazards) - 1)
        return self.hazards[i] * self.hazard_mult

    def spread_approx(self, t: float = 5.0) -> float:
        """Эквивалентный кредитный спред (треугольник: s ≈ λ̄·(1−R))."""
        return float(self.cum_hazard(t)[0] / t * (1 - self.recovery))

    def shocked(self, mult: float) -> "HazardCurve":
        c = HazardCurve(self.entity, self.ref_date, self.times, self.hazards, self.recovery, self.method,
                        self.method_rank, self.details, self.inputs, self.measure, self.hazard_mult * mult)
        return c

    def register(self, tracker: InputTracker | None, role: str = "") -> None:
        if tracker is None:
            return
        kind = DataKind.DERIVED if self.method_rank in (1, 2) else DataKind.MODEL
        prov = Provenance(f"кредитная кривая {self.entity}: {self.method}", None, kind,
                          note=("физическая мера (рейтинговая статистика)" if self.measure == "physical" else ""),
                          derived_from=tuple(u.id for u in self.inputs))
        tracker.record(UsedInput(f"credit:{self.entity}", round(self.spread_approx(), 6), prov, role))
        for u in self.inputs:
            tracker.record(u)

    def describe(self) -> dict[str, Any]:
        return {"entity": self.entity, "method": self.method, "method_rank": self.method_rank,
                "recovery": self.recovery, "measure": self.measure,
                "spread_5y_bp": self.spread_approx(5.0) * 1e4,
                "pd_1y": float(1 - self.survival(1.0)[0]), "pd_5y": float(1 - self.survival(5.0)[0]),
                "details": self.details, "inputs": [u.id for u in self.inputs]}


def _hazard_from_cum(points: Sequence[tuple[float, float]]) -> tuple[np.ndarray, np.ndarray]:
    """Кусочно-постоянная интенсивность по точкам кумулятивной интенсивности H(t);
    H делается неубывающим (интенсивность неотрицательна)."""
    pts = sorted(points)
    ts, hs = [], []
    prev_t, prev_h = 0.0, 0.0
    for t, h in pts:
        h = max(h, prev_h)
        if t <= prev_t + 1e-6:
            continue
        ts.append(t)
        hs.append((h - prev_h) / (t - prev_t))
        prev_t, prev_h = t, h
    if not ts:
        raise ValueError("недостаточно точек для кредитной кривой")
    return np.array(ts), np.array(hs)


@dataclass
class BondObs:
    id: str
    issuer: str
    yield_: float          # годовая эффективная доходность (YTM)
    duration: float        # дюрация, лет
    sector: str = ""
    rating: str = ""
    provenance: Provenance | None = None


def from_bond_spreads(entity: str, ref: date, bonds: Sequence[BondObs], ofz: YieldCurve,
                      recovery: float = 0.4, method_rank: int = 1, label: str | None = None) -> HazardCurve:
    """Метод 1/2: спред доходности к КБД на дюрации облигации."""
    pts, det, inputs = [], [], []
    by_d: dict[float, list[float]] = {}
    for b in bonds:
        y_cc = np.log1p(b.yield_)
        z = float(ofz.zero(b.duration))
        s = max(y_cc - z, 0.0)
        by_d.setdefault(round(b.duration, 2), []).append(s)
        det.append({"bond": b.id, "issuer": b.issuer, "yield": b.yield_, "duration": b.duration,
                    "ofz_zero": z, "spread_bp": s * 1e4})
        if b.provenance is not None:
            inputs.append(UsedInput(f"CREDIT.BOND.{b.id}", b.yield_, b.provenance, "доходность облигации для прокси-спреда"))
    for d, ss in by_d.items():
        s = float(np.median(ss))
        pts.append((d, s * d / (1 - recovery)))
    if len(pts) == 1:
        d, h = pts[0]
        pts = [(max(d, 0.5), h * max(d, 0.5) / d), (30.0, h / d * 30.0)]
    else:
        last_d, last_h = sorted(pts)[-1]
        pts.append((30.0, last_h / last_d * 30.0))
    ts, hz = _hazard_from_cum(pts)
    name = label or ("спред облигаций эмитента к КБД" if method_rank == 1 else "спред облигаций сопоставимых эмитентов к КБД")
    return HazardCurve(entity, ref, ts, hz, recovery, name, method_rank, {"bonds": det}, inputs)


def from_rating(entity: str, ref: date, rating: str, table: dict[str, Any], provenance: Provenance,
                recovery: float = 0.4, risk_premium_mult: float = 1.0) -> HazardCurve:
    """Метод 3: рейтинг → кумулятивные PD по горизонтам (физическая мера)."""
    agency = table.get("agency", "")
    rows = table["cumulative_pd"]
    key = rating.upper().replace(" ", "")
    if key not in rows:
        raise KeyError(f"рейтинг {rating} отсутствует в таблице {agency}")
    horizons = [float(h) for h in table["horizons"]]
    pds = rows[key]
    pts = [(h, -np.log(max(1 - pd, 1e-12)) * risk_premium_mult) for h, pd in zip(horizons, pds)]
    last_t, last_h = pts[-1]
    pts.append((30.0, last_h / last_t * 30.0))
    ts, hz = _hazard_from_cum(pts)
    inp = UsedInput(f"RATING.{agency}.{key}", pds, provenance, "кумулятивные PD по рейтингу")
    return HazardCurve(entity, ref, ts, hz, recovery, f"маппинг рейтинга {agency} {rating} на статистику дефолтов",
                       3, {"rating": rating, "agency": agency, "risk_premium_mult": risk_premium_mult}, [inp],
                       measure="physical")


def flat_hazard(entity: str, ref: date, spread: float, recovery: float = 0.4, note: str = "задано вручную") -> HazardCurve:
    lam = spread / (1 - recovery)
    return HazardCurve(entity, ref, np.array([30.0]), np.array([lam]), recovery, note, 0)
