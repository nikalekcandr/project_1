"""Контроль качества рыночных данных на загрузке.

Проверки: устаревание котировки относительно порога, пропуски в сетке
сроков, выбросы относительно предыдущего снапшота, нарушение монотонности
там, где она обязательна, базовая санитария значений, bid ≤ ask.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import timedelta
from typing import Any

from ..core.dates import Tenor
from .snapshot import MarketSnapshot


@dataclass
class QCFinding:
    severity: str   # info | warning | error
    check: str      # staleness | gap | outlier | monotonicity | sanity | spread
    quote_id: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Пороги устаревания по префиксу (самый длинный совпавший префикс)
STALENESS = {
    "FX.": timedelta(hours=26),
    "RATE.": timedelta(days=4),
    "SWAP.": timedelta(days=4),
    "BASIS.": timedelta(days=4),
    "VOL.": timedelta(days=4),
    "CURVE.": timedelta(days=4),
    "CMDTY.": timedelta(days=4),
    "EQ.": timedelta(days=4),
    "CREDIT.": timedelta(days=7),
    "INFL.": timedelta(days=7),
    "RATE.RUB.KEYRATE": timedelta(days=60),
}

# Ожидаемые сетки сроков для семейств
EXPECTED_GRIDS = {
    "SWAP.RUB.KEYRATE.": ["3M", "6M", "9M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y"],
    "RATE.RUB.RUSFAR.": ["ON", "1W", "2W", "1M", "3M"],
}

# Пороги выбросов: (абсолютный, относительный) по префиксу
OUTLIER = {
    "RATE.": (0.015, None),
    "SWAP.": (0.0125, None),
    "BASIS.": (0.005, None),
    "VOL.": (0.04, None),
    "FX.": (None, 0.06),
    "EQ.": (None, 0.15),
    "CMDTY.": (None, 0.12),
}

SANITY = {
    "RATE.": (-0.05, 0.6),
    "SWAP.": (-0.05, 0.6),
    "VOL.": (-0.5, 3.0),   # RR может быть отрицательным
    "FX.": (-1e9, 1e9),
}


def _match(prefix_map: dict, qid: str):
    best = None
    for p in prefix_map:
        if qid.startswith(p) and (best is None or len(p) > len(best)):
            best = p
    return prefix_map[best] if best else None


def run_qc(snap: MarketSnapshot, previous: MarketSnapshot | None = None) -> list[QCFinding]:
    out: list[QCFinding] = []
    # 1. устаревание
    for qid, q in snap.quotes.items():
        lim = _match(STALENESS, qid)
        if lim is None or q.provenance.as_of is None:
            continue
        age = snap.as_of - q.provenance.as_of
        if age > lim:
            out.append(QCFinding("warning", "staleness", qid,
                                 f"котировка устарела: возраст {age} при пороге {lim}"))
        if age < timedelta(0):
            out.append(QCFinding("error", "staleness", qid, "время котировки позже времени снапшота"))
    # 2. пропуски в сетке
    for prefix, grid in EXPECTED_GRIDS.items():
        have = {k[len(prefix):] for k in snap.quotes if k.startswith(prefix)}
        if not have:
            continue
        missing = [t for t in grid if t not in have]
        for t in missing:
            out.append(QCFinding("warning", "gap", prefix + t, f"нет точки {t} в сетке {prefix.rstrip('.')}"))
    # пропуски по поверхностям волатильности: у каждого срока должны быть ATM/RR25/BF25
    vol_tenors: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for qid in snap.quotes:
        if qid.startswith("VOL.") and qid.count(".") == 3:
            _, pair, pillar, tenor = qid.split(".")
            vol_tenors[pair][tenor].add(pillar)
    for pair, by_t in vol_tenors.items():
        for tenor, pillars in by_t.items():
            for need in ("ATM", "RR25", "BF25"):
                if need not in pillars and "ATM" in pillars:
                    out.append(QCFinding("warning", "gap", f"VOL.{pair}.{need}.{tenor}", f"нет столпа {need} на сроке {tenor}"))
    # 3. выбросы относительно предыдущего дня
    if previous is not None:
        for qid, q in snap.quotes.items():
            p = previous.get(qid)
            th = _match(OUTLIER, qid)
            if p is None or th is None or not isinstance(q.value, (int, float)) or not isinstance(p.value, (int, float)):
                continue
            ab, rel = th
            d = float(q.value) - float(p.value)
            if ab is not None and abs(d) > ab:
                out.append(QCFinding("warning", "outlier", qid, f"изменение {d:+.4g} к предыдущему снапшоту превышает порог {ab}"))
            if rel is not None and p.value and abs(d / float(p.value)) > rel:
                out.append(QCFinding("warning", "outlier", qid, f"изменение {d / float(p.value):+.2%} превышает порог {rel:.0%}"))
    # 4. монотонность общей дисперсии ATM по срокам
    for pair, by_t in vol_tenors.items():
        pts = []
        for tenor in by_t:
            q = snap.get(f"VOL.{pair}.ATM.{tenor}")
            if q is not None:
                pts.append((Tenor.parse(tenor).approx_years, float(q.value), tenor))
        pts.sort()
        for (t0, v0, n0), (t1, v1, n1) in zip(pts, pts[1:]):
            if v1 * v1 * t1 < v0 * v0 * t0 - 1e-12:
                out.append(QCFinding("error", "monotonicity", f"VOL.{pair}.ATM.{n1}",
                                     f"общая дисперсия ATM убывает между {n0} и {n1}: календарный арбитраж"))
    # 5. санитария и bid/ask
    for qid, q in snap.quotes.items():
        rng = _match(SANITY, qid)
        if rng is not None and isinstance(q.value, (int, float)):
            lo, hi = rng
            if not (lo <= float(q.value) <= hi):
                out.append(QCFinding("error", "sanity", qid, f"значение {q.value} вне допустимого диапазона [{lo}, {hi}]"))
        if qid.startswith("VOL.") and ".ATM." in qid and isinstance(q.value, (int, float)) and q.value <= 0:
            out.append(QCFinding("error", "sanity", qid, "неположительная ATM-волатильность"))
        if q.bid is not None and q.ask is not None and q.bid > q.ask:
            out.append(QCFinding("error", "spread", qid, f"bid {q.bid} > ask {q.ask}"))
    # 6. календарь заседаний ЦБ — покрытие на 12 месяцев вперёд
    if "cbr_meetings" in snap.datasets:
        from datetime import date
        dates = sorted(date.fromisoformat(m["announcement"]) for m in snap.dataset("cbr_meetings").data["meetings"])
        horizon = snap.as_of.date() + timedelta(days=365)
        if not dates or dates[-1] < horizon - timedelta(days=62):
            out.append(QCFinding("error", "gap", "cbr_meetings",
                                 "календарь заседаний Совета директоров Банка России покрывает менее 12 месяцев вперёд"))
    # 7. demo-флаг
    if snap.is_demo:
        out.append(QCFinding("warning", "sanity", "*", "ДЕМО-снапшот: значения иллюстративные, не для реальной оценки"))
    return out


def qc_summary(findings: list[QCFinding]) -> dict[str, int]:
    s = {"error": 0, "warning": 0, "info": 0}
    for f in findings:
        s[f.severity] = s.get(f.severity, 0) + 1
    return s
