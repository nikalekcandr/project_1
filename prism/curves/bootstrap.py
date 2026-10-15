"""Калибровка кривых: инструменты и глобальный подбор.

Параметры — форвардные ставки на сегментах между узлами (эквивалентно
лог-дисконт-факторам в узлах). Невязки — в базисных пунктах котировки.
В ступенчатой области (короткий конец между заседаниями ЦБ) число
сегментов обычно больше числа инструментов; тогда добавляется слабый
штраф на изменение форварда между соседними заседаниями (минимальная
траектория ставки), который не мешает точному репрайсингу.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Sequence

import numpy as np
from scipy.optimize import least_squares

from ..core.calendars import BusinessCalendar
from ..core.dates import BDC, add_tenor
from ..core.daycount import DayCount
from ..core.schedule import roll_dates
from .base import CalibrationRecord, YieldCurve

SELF = "__self__"


@dataclass
class CurveInstrument:
    name: str
    quote_id: str
    market: float
    maturity: date

    def model(self, curve: YieldCurve, others: dict[str, YieldCurve]) -> float:  # pragma: no cover
        raise NotImplementedError

    @staticmethod
    def _get(curve: YieldCurve, others: dict[str, YieldCurve], key: str) -> YieldCurve:
        return curve if key == SELF else others[key]


@dataclass
class DepositInstrument(CurveInstrument):
    start: date = None
    daycount: DayCount = DayCount.ACT_365F

    def model(self, curve, others):
        t0, t1 = curve.time(self.start), curve.time(self.maturity)
        tau = self.daycount.year_fraction(self.start, self.maturity)
        return float((curve.df(t0) / curve.df(t1) - 1.0) / tau)


@dataclass
class FRAInstrument(DepositInstrument):
    pass


@dataclass
class SwapInstrument(CurveInstrument):
    """Фиксированная нога против плавающей на индекс (прогнозная кривая).

    ``compounding``: 'compounded' — сложный процент по дневному индексу (OIS),
    'simple_average' — простое среднее (типично для ключевой ставки в РФ).
    """
    fixed_periods: list[tuple[date, date, float]] = field(default_factory=list)   # (start, pay, tau)
    float_periods: list[tuple[date, date, float]] = field(default_factory=list)   # (start, end, tau)
    forecast: str = SELF
    discount: str = SELF
    compounding: str = "compounded"
    spread: float = 0.0

    def _arrays(self, ref: date):
        c = getattr(self, "_arr", None)
        if c is None or c[0] != ref:
            s = np.array([(a - ref).days / 365.0 for a, _, _ in self.float_periods])
            e = np.array([(b - ref).days / 365.0 for _, b, _ in self.float_periods])
            tau = np.array([x for _, _, x in self.float_periods])
            pt = np.array([(p - ref).days / 365.0 for _, p, _ in self.fixed_periods])
            ft = np.array([x for _, _, x in self.fixed_periods])
            c = (ref, s, e, tau, pt, ft)
            object.__setattr__(self, "_arr", c)
        return c[1:]

    def model(self, curve, others):
        fc = self._get(curve, others, self.forecast)
        dc = self._get(curve, others, self.discount)
        s, e, tau, pt, ft = self._arrays(fc.ref_date)
        if self.compounding == "simple_average":
            fwd = fc.fwd_average(s, e) * (e - s) / tau
        else:
            fwd = (fc.df(s) / fc.df(e) - 1.0) / tau
        flt = float(np.sum((fwd + self.spread) * tau * dc.df(e)))
        ann = float(np.sum(ft * dc.df(pt)))
        return flt / ann


@dataclass
class BasisSwapInstrument(CurveInstrument):
    """Индекс A + спред против индекса B; котировка — спред на ноге A."""
    periods: list[tuple[date, date, float]] = field(default_factory=list)
    leg_a: str = SELF
    leg_b: str = ""
    discount: str = ""
    comp_a: str = "compounded"
    comp_b: str = "compounded"

    def _leg(self, c: YieldCurve, dc: YieldCurve, comp: str):
        ar = getattr(self, "_arr", None)
        if ar is None or ar[0] != c.ref_date:
            ar = (c.ref_date, np.array([c.time(a) for a, _, _ in self.periods]),
                  np.array([c.time(b) for _, b, _ in self.periods]), np.array([x for _, _, x in self.periods]))
            object.__setattr__(self, "_arr", ar)
        _, s, e, tau = ar
        if comp == "simple_average":
            fwd = c.fwd_average(s, e) * (e - s) / tau
        else:
            fwd = (c.df(s) / c.df(e) - 1.0) / tau
        dfs = dc.df(e)
        return float(np.sum(fwd * tau * dfs)), float(np.sum(tau * dfs))

    def model(self, curve, others):
        a = self._get(curve, others, self.leg_a)
        b = self._get(curve, others, self.leg_b)
        dc = self._get(curve, others, self.discount or self.leg_b)
        pa, ann = self._leg(a, dc, self.comp_a)
        pb, _ = self._leg(b, dc, self.comp_b)
        return (pb - pa) / ann


@dataclass
class FXOutrightInstrument(CurveInstrument):
    """Аутрайт-форвард для вывода имплицированной иностранной кривой.

    F = S · [DFf(T)/DFf(Ts)] / [DFd(T)/DFd(Ts)]; подбирается кривая DFf.
    """
    spot: float = 0.0
    spot_date: date = None
    domestic: str = ""

    def model(self, curve, others):
        dc = others[self.domestic]
        ts, tt = curve.time(self.spot_date), curve.time(self.maturity)
        return float(self.spot * (curve.df(tt) / curve.df(ts)) / (dc.df(tt) / dc.df(ts)))


@dataclass
class ZeroRateInstrument(CurveInstrument):
    """Непрерывная нулевая ставка (например, точка КБД)."""

    def model(self, curve, others):
        return float(curve.zero(curve.time(self.maturity)))


# ---------------------------------------------------------------------------
# Генераторы инструментов по конвенциям
# ---------------------------------------------------------------------------

def swap_from_tenor(name: str, quote_id: str, rate: float, ref: date, start_lag: int, tenor: str,
                    cal: BusinessCalendar, fixed_freq: str = "1Y", float_freq: str = "3M",
                    fixed_dc: DayCount = DayCount.ACT_365F, float_dc: DayCount = DayCount.ACT_365F,
                    forecast: str = SELF, discount: str = SELF, compounding: str = "compounded",
                    bdc: BDC = BDC.MODIFIED_FOLLOWING) -> SwapInstrument:
    start = cal.advance_business_days(ref, start_lag) if start_lag else ref
    end = add_tenor(start, tenor, cal, bdc)
    # для коротких свопов (до года) — одна выплата в конце (как OIS/ROISfix)
    from ..core.dates import Tenor
    tn = Tenor.parse(tenor)
    short = tn.approx_years <= 1.0 + 1e-9
    fx = [start, end] if short else roll_dates(start, end, fixed_freq)
    fl = [start, end] if short else roll_dates(start, end, float_freq)
    fxa = [cal.adjust(d, bdc) for d in fx]
    fla = [cal.adjust(d, bdc) for d in fl]
    fixed = [(a, b, fixed_dc.year_fraction(a, b)) for a, b in zip(fxa[:-1], fxa[1:])]
    flt = [(a, b, float_dc.year_fraction(a, b)) for a, b in zip(fla[:-1], fla[1:])]
    return SwapInstrument(name, quote_id, rate, fxa[-1], fixed, flt, forecast, discount, compounding)


def deposit_from_tenor(name: str, quote_id: str, rate: float, ref: date, start_lag: int, tenor: str,
                       cal: BusinessCalendar, dc: DayCount = DayCount.ACT_365F) -> DepositInstrument:
    start = cal.advance_business_days(ref, start_lag) if start_lag else ref
    end = add_tenor(start, tenor, cal, BDC.MODIFIED_FOLLOWING) if tenor.upper() not in ("ON", "TN") \
        else cal.advance_business_days(start, 1)
    return DepositInstrument(name, quote_id, rate, end, start, dc)


# ---------------------------------------------------------------------------
# Глобальный подбор
# ---------------------------------------------------------------------------

@dataclass
class FitResult:
    curve: YieldCurve
    records: list[CalibrationRecord]
    max_error_bp: float
    success: bool
    message: str


def fit_curve(
    cid: str,
    ref: date,
    instruments: Sequence[CurveInstrument],
    *,
    others: dict[str, YieldCurve] | None = None,
    interpolation: str = "log_linear",
    step_nodes: Sequence[date] = (),
    currency: str = "RUB",
    method: str = "",
    smooth_weight: float = 0.005,
    curve_factory: Callable[..., YieldCurve] | None = None,
    inputs=None,
    x0: np.ndarray | None = None,
) -> FitResult:
    """Подбор кривой под набор инструментов.

    ``step_nodes`` — даты вступления в силу решений ЦБ: форвард кусочно
    постоянен между ними (ступенчатый короткий конец).
    """
    others = others or {}
    instruments = sorted(instruments, key=lambda i: i.maturity)
    step_nodes = sorted(d for d in set(step_nodes) if d > ref)
    step_end = None
    nodes: list[date] = []
    if step_nodes:
        step_nodes = [d for d in step_nodes if d <= instruments[-1].maturity] or step_nodes[:1]
        step_end = step_nodes[-1]
        nodes = list(step_nodes)
        nodes += [i.maturity for i in instruments if i.maturity > step_end]
    else:
        nodes = [i.maturity for i in instruments]
    nodes = sorted(set(d for d in nodes if d > ref))
    times = np.array([(d - ref).days / 365.0 for d in nodes])
    dt = np.diff(np.concatenate([[0.0], times]))
    n_step = 0
    meta = {}
    interp = interpolation
    if step_end is not None:
        n_step = sum(1 for d in nodes if d <= step_end)
        meta["step_end"] = (step_end - ref).days / 365.0
        meta["meeting_nodes"] = [d.isoformat() for d in step_nodes]
        interp = interpolation if interpolation.startswith("step+") else f"step+{interpolation}"

    def build(f: np.ndarray) -> YieldCurve:
        logdf = -np.cumsum(f * dt)
        return YieldCurve(cid, ref, times, logdf, interp, currency, method, float(times[-1]), meta=dict(meta))

    def resid(f: np.ndarray) -> np.ndarray:
        c = build(f)
        r = [(ins.model(c, others) - ins.market) * 1e4 for ins in instruments]
        if n_step > 1:
            # штраф на изменение форвардов между заседаниями (в б.п.)
            r += list(smooth_weight * np.diff(f[:n_step]) * 1e4)
        return np.array(r)

    if x0 is None or len(x0) != len(times):
        x0 = np.full(len(times), float(np.mean([i.market for i in instruments if abs(i.market) < 1.0] or [0.05])))
    sol = least_squares(resid, x0, method="trf", x_scale=0.01, xtol=1e-15, ftol=1e-15, gtol=1e-15, max_nfev=4000)
    curve = build(sol.x)
    recs = []
    errs = []
    for ins in instruments:
        m = ins.model(curve, others)
        if isinstance(ins, FXOutrightInstrument):
            tau = max((ins.maturity - ins.spot_date).days / 365.0, 1e-6)
            recs.append(CalibrationRecord(ins.name, ins.quote_id, ins.market, m, unit="price"))
            errs.append(abs(m / ins.market - 1.0) / tau * 1e4)  # ошибка в имплицированной ставке, б.п.
        else:
            recs.append(CalibrationRecord(ins.name, ins.quote_id, ins.market, m))
            errs.append(abs(m - ins.market) * 1e4)
    curve.calibration = recs
    curve.meta["fit_params"] = sol.x.copy()
    if inputs:
        curve.inputs = list(inputs)
    return FitResult(curve, recs, max(errs, default=0.0), bool(sol.success), str(sol.message))
