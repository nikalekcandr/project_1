"""Ступенчатый короткий конец рублёвой кривой на датах заседаний Банка России.

Ключевая ставка между заседаниями не меняется, поэтому форвардная ставка
кусочно постоянна, а скачки приходятся на даты *вступления решения в силу*
(обычно следующий рабочий день после объявления), а не на дату объявления.
Календарь заседаний — загружаемый вход (датасет снапшота), минимум на 12
месяцев вперёд.

Побочный выход: имплицированный рынком ожидаемый размер изменения ставки на
каждом заседании и вероятности соседних исходов (модель двух исходов с
шагом ``increment``, как в FedWatch).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np

from .base import YieldCurve


@dataclass(frozen=True)
class Meeting:
    announcement: date
    effective: date
    kind: str = "core"   # core — опорное (с прогнозом), regular

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Meeting":
        ann = date.fromisoformat(d["announcement"])
        eff = date.fromisoformat(d["effective"]) if d.get("effective") else ann + timedelta(days=3 if ann.weekday() == 4 else 1)
        return cls(ann, eff, d.get("kind", "regular"))


def load_meetings(dataset_data: dict[str, Any]) -> list[Meeting]:
    return sorted((Meeting.from_dict(m) for m in dataset_data["meetings"]), key=lambda m: m.effective)


def check_meeting_coverage(meetings: list[Meeting], as_of: date, months: int = 12) -> str | None:
    future = [m for m in meetings if m.announcement > as_of]
    if not future:
        return "нет будущих заседаний в календаре"
    if (future[-1].announcement - as_of).days < months * 30.4 - 62:
        return f"календарь заседаний покрывает только до {future[-1].announcement.isoformat()} (< {months} мес.)"
    return None


@dataclass
class MeetingExpectation:
    announcement: date
    effective: date
    rate_before: float
    rate_after: float
    expected_change_bp: float
    outcomes: list[tuple[float, float]]   # (изменение, б.п.; вероятность)

    def to_dict(self) -> dict[str, Any]:
        return {
            "announcement": self.announcement.isoformat(),
            "effective": self.effective.isoformat(),
            "rate_before": self.rate_before,
            "rate_after": self.rate_after,
            "expected_change_bp": self.expected_change_bp,
            "outcomes": [{"change_bp": c, "probability": p} for c, p in self.outcomes],
        }


def _two_outcome(delta_bp: float, inc: float) -> list[tuple[float, float]]:
    if abs(delta_bp) < 1e-9:
        return [(0.0, 1.0)]
    s = np.sign(delta_bp)
    k = int(np.floor(abs(delta_bp) / inc))
    lo = k * inc
    hi = (k + 1) * inc
    p_hi = (abs(delta_bp) - lo) / inc
    out = []
    if 1 - p_hi > 1e-6:
        out.append((float(s * lo), float(1 - p_hi)))
    if p_hi > 1e-6:
        out.append((float(s * hi), float(p_hi)))
    return out


def implied_meeting_path(curve: YieldCurve, meetings: list[Meeting], *, spread_to_key: float = 0.0,
                         increment_bp: float = 50.0, horizon_months: int = 18) -> list[MeetingExpectation]:
    """Имплицированная траектория ключевой ставки.

    Форвард на сегменте после заседания минус форвард до него — ожидаемое
    изменение (с точностью до срочной премии и выпуклости, которые здесь не
    выделяются). ``spread_to_key`` — постоянный спред индекса кривой к ключевой
    ставке (для кривой КС — 0, для RUONIA ≈ −0.2…−0.4 п.п.).
    """
    ref = curve.ref_date
    end = ref + timedelta(days=int(horizon_months * 30.5))
    out: list[MeetingExpectation] = []
    fut = [m for m in meetings if ref < m.effective <= end]
    eps = 0.5 / 365.0
    for m in fut:
        t = curve.time(m.effective)
        # непрерывная ставка → простая дневная ставка ACT/365 (конвенция КС/RUONIA)
        before = 365.0 * np.expm1(float(curve.inst_fwd(max(t - eps, 0.0))) / 365.0) - spread_to_key
        after = 365.0 * np.expm1(float(curve.inst_fwd(t + eps)) / 365.0) - spread_to_key
        d_bp = (after - before) * 1e4
        out.append(MeetingExpectation(m.announcement, m.effective, before, after, d_bp, _two_outcome(d_bp, increment_bp)))
    return out
