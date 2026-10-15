"""Кривая дисконтирования / прогнозная кривая и интерполяции.

Время — ACT/365F от даты кривой. По умолчанию интерполяция log-linear по
дисконт-факторам (кусочно-постоянная мгновенная форвардная ставка).
Переключаемые альтернативы: monotone convex (Hagan-West) по форвардам и
натуральный кубический сплайн по нулевым ставкам. Экстраполяция за последний
калибровочный узел — плоская форвардная ставка, с обязательным флагом.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Sequence

import numpy as np

from ..core.provenance import DataKind, InputTracker, Provenance, UsedInput, worst_kind

INTERPOLATIONS = ("log_linear", "monotone_convex", "cubic_zero")


def _as_arr(t) -> tuple[np.ndarray, bool]:
    a = np.asarray(t, dtype=float)
    return np.atleast_1d(a), a.ndim == 0


class _LogLinear:
    def __init__(self, times: np.ndarray, logdf: np.ndarray):
        self.t, self.y = times, logdf
        dt = np.diff(times)
        self.f = -np.diff(logdf) / dt  # форвард на каждом сегменте

    def logdf(self, t: np.ndarray) -> np.ndarray:
        return np.interp(t, self.t, self.y)

    def fwd(self, t: np.ndarray) -> np.ndarray:
        i = np.clip(np.searchsorted(self.t, t, side="right") - 1, 0, len(self.f) - 1)
        return self.f[i]


class _CubicZero:
    """Натуральный кубический сплайн по нулевым ставкам z(t) (непрерывное начисление)."""

    def __init__(self, times: np.ndarray, logdf: np.ndarray):
        self.t = times
        z = np.empty_like(logdf)
        z[1:] = -logdf[1:] / times[1:]
        z[0] = z[1]
        self.z = z
        n = len(times)
        h = np.diff(times)
        a = np.zeros((n, n))
        rhs = np.zeros(n)
        a[0, 0] = a[-1, -1] = 1.0
        for i in range(1, n - 1):
            a[i, i - 1] = h[i - 1]
            a[i, i] = 2 * (h[i - 1] + h[i])
            a[i, i + 1] = h[i]
            rhs[i] = 6 * ((z[i + 1] - z[i]) / h[i] - (z[i] - z[i - 1]) / h[i - 1])
        self.m = np.linalg.solve(a, rhs) if n > 2 else np.zeros(n)
        self.h = h

    def zero(self, t: np.ndarray) -> np.ndarray:
        tt = np.clip(t, self.t[0], self.t[-1])
        i = np.clip(np.searchsorted(self.t, tt, side="right") - 1, 0, len(self.h) - 1)
        h = self.h[i]
        x0 = tt - self.t[i]
        x1 = self.t[i + 1] - tt
        m0, m1 = self.m[i], self.m[i + 1]
        z0, z1 = self.z[i], self.z[i + 1]
        return (m0 * x1 ** 3 + m1 * x0 ** 3) / (6 * h) + (z0 / h - m0 * h / 6) * x1 + (z1 / h - m1 * h / 6) * x0

    def logdf(self, t: np.ndarray) -> np.ndarray:
        return -self.zero(t) * t

    def fwd(self, t: np.ndarray) -> np.ndarray:
        eps = 1e-5
        return -(self.logdf(t + eps) - self.logdf(np.maximum(t - eps, 0.0))) / (t + eps - np.maximum(t - eps, 0.0))


class _MonotoneConvex:
    """Monotone convex (Hagan & West, 2006) по дискретным форвардам."""

    def __init__(self, times: np.ndarray, logdf: np.ndarray):
        self.t = times
        dt = np.diff(times)
        fd = -np.diff(logdf) / dt
        n = len(fd)
        f = np.empty(n + 1)
        for i in range(1, n):
            f[i] = (dt[i - 1] * fd[i] + dt[i] * fd[i - 1]) / (dt[i - 1] + dt[i])
        if n >= 2:
            f[0] = fd[0] - 0.5 * (f[1] - fd[0])
            f[n] = fd[n - 1] - 0.5 * (f[n - 1] - fd[n - 1])
        else:
            f[0] = f[1] = fd[0]
        self.fd, self.fn, self.dt, self.y = fd, f, dt, logdf

    @staticmethod
    def _g_and_int(x, g0, g1):
        """Возвращает (g(x), ∫_0^x g)."""
        x = np.asarray(x, dtype=float)
        g = np.zeros_like(x)
        ig = np.zeros_like(x)
        if abs(g0) < 1e-15 and abs(g1) < 1e-15:
            return g, ig
        if (g0 < 0 and -0.5 * g0 <= g1 <= -2 * g0) or (g0 > 0 and -0.5 * g0 >= g1 >= -2 * g0):
            g = g0 * (1 - 4 * x + 3 * x * x) + g1 * (-2 * x + 3 * x * x)
            ig = g0 * (x - 2 * x * x + x ** 3) + g1 * (-x * x + x ** 3)
        elif (g0 < 0 and g1 > -2 * g0) or (g0 > 0 and g1 < -2 * g0):
            eta = (g1 + 2 * g0) / (g1 - g0)
            r = np.clip((x - eta) / (1 - eta), 0, None)
            g = np.where(x <= eta, g0, g0 + (g1 - g0) * r * r)
            ig = g0 * x + np.where(x > eta, (g1 - g0) * (x - eta) ** 3 / (3 * (1 - eta) ** 2), 0.0)
        elif (g0 > 0 and 0 > g1 > -0.5 * g0) or (g0 < 0 and 0 < g1 < -0.5 * g0):
            eta = 3 * g1 / (g1 - g0)
            r = np.clip((eta - x) / eta, 0, None)
            g = np.where(x < eta, g1 + (g0 - g1) * r * r, g1)
            ig = g1 * x + np.where(x < eta, (g0 - g1) * (eta ** 3 - (eta - x) ** 3) / (3 * eta * eta),
                                   (g0 - g1) * eta / 3)
        else:
            eta = g1 / (g1 + g0)
            a = -g0 * g1 / (g0 + g1)
            if eta <= 0:
                eta = 1e-12
            if eta >= 1:
                eta = 1 - 1e-12
            r0 = np.clip((eta - x) / eta, 0, None)
            r1 = np.clip((x - eta) / (1 - eta), 0, None)
            g = np.where(x <= eta, a + (g0 - a) * r0 * r0, a + (g1 - a) * r1 * r1)
            ig = np.where(x <= eta, a * x + (g0 - a) * (eta ** 3 - (eta - x) ** 3) / (3 * eta * eta),
                          a * x + (g0 - a) * eta / 3 + (g1 - a) * (x - eta) ** 3 / (3 * (1 - eta) ** 2))
        return g, ig

    def _eval(self, t: np.ndarray):
        i = np.clip(np.searchsorted(self.t, t, side="right") - 1, 0, len(self.fd) - 1)
        f = np.empty_like(t)
        ly = np.empty_like(t)
        for seg in np.unique(i):
            m = i == seg
            x = (t[m] - self.t[seg]) / self.dt[seg]
            g, ig = self._g_and_int(x, self.fn[seg] - self.fd[seg], self.fn[seg + 1] - self.fd[seg])
            f[m] = self.fd[seg] + g
            ly[m] = self.y[seg] - self.dt[seg] * (self.fd[seg] * x + ig)
        return ly, f

    def logdf(self, t):
        return self._eval(t)[0]

    def fwd(self, t):
        return self._eval(t)[1]


class _Hybrid:
    """Ступенчатый короткий конец (кусочно-постоянный форвард до ``split``)
    и выбранная интерполяция дальше."""

    def __init__(self, times: np.ndarray, logdf: np.ndarray, split: float, tail: str):
        k = int(np.searchsorted(times, split + 1e-12))  # узлы [0..k-1] <= split
        self.split = times[k - 1]
        self.head = _LogLinear(times[:k], logdf[:k]) if k >= 2 else None
        if k < len(times):
            tt = times[k - 1:] - times[k - 1]
            self.tail = _INTERP[tail](tt, logdf[k - 1:] - logdf[k - 1])
            self.y0 = logdf[k - 1]
        else:
            self.tail = None

    def logdf(self, t):
        out = np.empty_like(t)
        m = t <= self.split
        if self.head is not None:
            out[m] = self.head.logdf(t[m])
        else:
            out[m] = 0.0
        if self.tail is not None and np.any(~m):
            out[~m] = self.y0 + self.tail.logdf(t[~m] - self.split)
        return out

    def fwd(self, t):
        out = np.empty_like(t)
        m = t < self.split
        if self.head is not None:
            out[m] = self.head.fwd(t[m])
        if self.tail is not None and np.any(~m):
            out[~m] = self.tail.fwd(t[~m] - self.split)
        elif np.any(~m):
            out[~m] = self.head.fwd(np.full((~m).sum(), self.split - 1e-12))
        return out


_INTERP = {"log_linear": _LogLinear, "step": _LogLinear, "monotone_convex": _MonotoneConvex, "cubic_zero": _CubicZero}


def make_interpolator(name: str, times: np.ndarray, logdf: np.ndarray, meta: dict | None = None):
    if name.startswith("step+"):
        split = float((meta or {}).get("step_end", 0.0))
        tail = name.split("+", 1)[1]
        if split <= 0:
            return _INTERP[tail](times, logdf)
        return _Hybrid(times, logdf, split, tail)
    return _INTERP[name](times, logdf)


@dataclass
class CalibrationRecord:
    instrument: str
    quote_id: str
    market: float
    model: float
    unit: str = "rate"

    @property
    def error_bp(self) -> float:
        return (self.model - self.market) * 1e4

    def to_dict(self) -> dict[str, Any]:
        return {"instrument": self.instrument, "quote_id": self.quote_id, "market": self.market,
                "model": self.model, "error_bp": self.error_bp}


@dataclass
class YieldCurve:
    """Кривая дисконт-факторов. Узлы в годах ACT/365F от ``ref_date``."""
    id: str
    ref_date: date
    times: np.ndarray
    logdf: np.ndarray
    interpolation: str = "log_linear"
    currency: str = "RUB"
    method: str = ""
    extrap_start: float | None = None
    calibration: list[CalibrationRecord] = field(default_factory=list)
    inputs: list[UsedInput] = field(default_factory=list)
    zero_shift: float = 0.0          # параллельный сдвиг нулевой ставки (сценарии)
    shift_fn: Any = None             # непараллельный сдвиг: t -> Δz(t)
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.times = np.asarray(self.times, dtype=float)
        self.logdf = np.asarray(self.logdf, dtype=float)
        if self.times[0] != 0.0:
            self.times = np.concatenate([[0.0], self.times])
            self.logdf = np.concatenate([[0.0], self.logdf])
        if self.extrap_start is None:
            self.extrap_start = float(self.times[-1])
        self._impl = make_interpolator(self.interpolation, self.times, self.logdf, self.meta)
        self._last_f = float(self._impl.fwd(np.array([self.times[-1] - 1e-9]))[0])

    # ----------------------------------------------------------- time
    def time(self, d: date | Sequence[date]) -> np.ndarray | float:
        if isinstance(d, date):
            return (d - self.ref_date).days / 365.0
        return np.array([(x - self.ref_date).days / 365.0 for x in d])

    # ----------------------------------------------------------- core
    def _logdf_raw(self, t: np.ndarray) -> np.ndarray:
        tmax = self.times[-1]
        inside = np.minimum(t, tmax)
        out = self._impl.logdf(inside)
        ext = t > tmax
        if np.any(ext):
            out = np.where(ext, self.logdf[-1] - self._last_f * (t - tmax), out)
        return out

    def logdf_t(self, t) -> np.ndarray:
        a, scalar = _as_arr(t)
        a = np.maximum(a, 0.0)
        out = self._logdf_raw(a)
        if self.zero_shift:
            out = out - self.zero_shift * a
        if self.shift_fn is not None:
            out = out - self.shift_fn(a) * a
        return out[0] if scalar else out

    def df(self, t) -> np.ndarray | float:
        return np.exp(self.logdf_t(t))

    def df_date(self, d: date) -> float:
        return float(self.df(self.time(d)))

    def zero(self, t) -> np.ndarray | float:
        a, scalar = _as_arr(t)
        a = np.maximum(a, 1e-8)
        z = -self.logdf_t(a) / a
        return z[0] if scalar else z

    def inst_fwd(self, t) -> np.ndarray | float:
        a, scalar = _as_arr(t)
        tmax = self.times[-1]
        f = np.where(a > tmax, self._last_f, self._impl.fwd(np.clip(a, 0, tmax)))
        f = f + self.zero_shift
        if self.shift_fn is not None:
            eps = 1e-5
            f = f + (self.shift_fn(a + eps) * (a + eps) - self.shift_fn(a) * a) / eps
        return f[0] if scalar else f

    def fwd_simple(self, t1, t2) -> np.ndarray | float:
        """Простая форвардная ставка ACT/365F между t1 и t2."""
        t1 = np.asarray(t1, dtype=float)
        t2 = np.asarray(t2, dtype=float)
        tau = np.maximum(t2 - t1, 1e-10)
        return (np.exp(self.logdf_t(t1) - self.logdf_t(t2)) - 1.0) / tau

    def fwd_average(self, t1, t2) -> np.ndarray | float:
        """Среднее (арифметическое по времени) мгновенной форвардной ставки на [t1, t2]."""
        t1 = np.asarray(t1, dtype=float)
        t2 = np.asarray(t2, dtype=float)
        tau = np.maximum(t2 - t1, 1e-10)
        return (self.logdf_t(t1) - self.logdf_t(t2)) / tau

    # ----------------------------------------------------------- flags
    def flags_for(self, t: float) -> tuple[str, ...]:
        return ("extrapolated",) if t > self.extrap_start + 1e-9 else ()

    @property
    def kind(self) -> DataKind:
        return worst_kind([u.kind for u in self.inputs]) if self.inputs else DataKind.DERIVED

    def register(self, tracker: InputTracker | None, t_max: float, role: str = "") -> None:
        if tracker is None:
            return
        flags = self.flags_for(t_max)
        prov = Provenance(f"кривая {self.id}: {self.method}", None,
                          DataKind.DERIVED if self.kind in (DataKind.MARKET, DataKind.DERIVED) else self.kind,
                          note=f"интерполяция {self.interpolation}; узлов {len(self.times) - 1}",
                          derived_from=tuple(u.id for u in self.inputs))
        tracker.record(UsedInput(f"curve:{self.id}", f"t≤{t_max:.2f}", prov, role, flags))
        if flags:
            tracker.warn(f"Кривая {self.id}: срок {t_max:.2f} г. за последним калибровочным узлом "
                         f"({self.extrap_start:.2f} г.) — плоская форвардная экстраполяция")
        for u in self.inputs:
            tracker.record(u)

    # ----------------------------------------------------------- transforms
    def shifted(self, dz: float = 0.0, fn=None, suffix: str = "") -> "YieldCurve":
        c = YieldCurve(self.id + suffix, self.ref_date, self.times.copy(), self.logdf.copy(), self.interpolation,
                       self.currency, self.method, self.extrap_start, self.calibration, self.inputs,
                       self.zero_shift + dz, fn if fn is not None else self.shift_fn, dict(self.meta))
        return c

    def rolled(self, new_ref: date) -> "YieldCurve":
        """Кривая с новой датой (для теты): DF_new(t) = DF(t+d)/DF(d)."""
        d = (new_ref - self.ref_date).days / 365.0
        ts = self.times[self.times > d] - d
        base = self.logdf_t(d)
        ly = self.logdf_t(ts + d) - base
        meta = dict(self.meta)
        if "step_end" in meta:
            meta["step_end"] = max(meta["step_end"] - d, 0.0)
        return YieldCurve(self.id, new_ref, ts, ly, self.interpolation, self.currency, self.method,
                          max(self.extrap_start - d, 0.0), self.calibration, self.inputs, 0.0, None, meta)

    def node_table(self) -> list[dict[str, float]]:
        out = []
        for t, ly in zip(self.times[1:], self.logdf[1:]):
            out.append({"t": float(t), "df": float(np.exp(ly)), "zero": float(-ly / t),
                        "fwd": float(self.inst_fwd(t - 1e-6))})
        return out


def flat_curve(cid: str, ref: date, rate: float, ccy: str = "RUB", horizon: float = 50.0,
               inputs: list[UsedInput] | None = None, method: str = "плоская ставка") -> YieldCurve:
    """Плоская кривая (непрерывное начисление)."""
    ts = np.array([horizon])
    return YieldCurve(cid, ref, ts, -rate * ts, "log_linear", ccy, method, horizon, [], inputs or [])
