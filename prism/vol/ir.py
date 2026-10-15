"""Процентная волатильность.

* нормальная (Башелье) и сдвинутая логнормальная нормировки с корректной
  конвертацией через равенство цен; при ставках 16–21% нормальная
  волатильность численно устойчивее;
* caplet stripping из котировок плоской волатильности капов;
* куб свопционов expiry × tenor × strike с SABR по узлам;
* исторический фоллбэк по рядам свопов на КС — помечается как модельный.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Sequence

import numpy as np
from scipy.optimize import brentq

from ..core.provenance import DataKind, InputTracker, Provenance, UsedInput
from ..models.analytic.black import bachelier, black, lognormal_to_normal, normal_to_lognormal
from .sabr import SABR


@dataclass
class RateVol:
    """Волатильность ставки как функция (expiry, tenor, strike).

    ``normal`` — нормальная волатильность (доли/год, 0.02 = 200 б.п.).
    ``smile`` — опционально SABR (нормальный) по узлам expiry.
    """
    id: str
    ref_date: date
    expiries: np.ndarray
    tenors: np.ndarray
    normal: np.ndarray                     # [len(expiries), len(tenors)] ATM нормальная вола
    kind: DataKind = DataKind.MARKET
    method: str = ""
    smile: dict[int, SABR] = field(default_factory=dict)  # индекс expiry -> SABR (нормальный)
    inputs: list[UsedInput] = field(default_factory=list)
    shift_bp: float = 0.0                  # параллельный сдвиг нормальной волы, б.п.
    bucket_shifts: dict[tuple[int, int], float] = field(default_factory=dict)
    halfspread_bp: float = 0.0

    def atm_normal(self, T: float, tenor: float = 0.25) -> float:
        T = max(T, 1e-6)
        e, t = self.expiries, self.tenors
        grid = self.normal.copy()
        for (i, j), dv in self.bucket_shifts.items():
            grid[i, j] += dv
        if len(t) == 1:
            row = grid[:, 0]
        else:
            jt = np.clip(tenor, t[0], t[-1])
            row = np.array([np.interp(jt, t, grid[i]) for i in range(len(e))])
        # интерполяция по общей дисперсии в нормальных терминах
        var = row ** 2 * e
        if T <= e[0]:
            v = row[0]
        elif T >= e[-1]:
            v = row[-1]
        else:
            v = np.sqrt(np.interp(T, e, var) / T)
        return float(v + self.shift_bp * 1e-4)

    def normal_vol(self, F: float, K: float, T: float, tenor: float = 0.25) -> float:
        atm = self.atm_normal(T, tenor)
        if not self.smile:
            return atm
        i = int(np.argmin(np.abs(self.expiries - T)))
        s = self.smile.get(i)
        if s is None:
            return atm
        base = float(s.normal_vol(F, F, T))
        return float(s.normal_vol(F, K, T)) - base + atm

    def flags_for(self, T: float) -> tuple[str, ...]:
        return ("extrapolated",) if T > self.expiries[-1] + 1e-9 else ()

    def register(self, tracker: InputTracker | None, T: float, role: str = "") -> None:
        if tracker is None:
            return
        prov = Provenance(f"процентная волатильность {self.id}: {self.method}", None, self.kind)
        tracker.record(UsedInput(f"irvol:{self.id}", round(self.atm_normal(T) * 1e4, 2), prov,
                                 role or "нормальная волатильность ставки, б.п.", self.flags_for(T)))
        if self.kind.is_model_based:
            tracker.warn(f"Процентная волатильность {self.id} — {self.kind.label_ru}: {self.method}")
        for u in self.inputs:
            tracker.record(u)

    def shifted(self, dbp: float) -> "RateVol":
        return RateVol(self.id, self.ref_date, self.expiries, self.tenors, self.normal, self.kind, self.method,
                       self.smile, self.inputs, self.shift_bp + dbp, dict(self.bucket_shifts), self.halfspread_bp)

    def bucket_shifted(self, i: int, j: int, dv: float) -> "RateVol":
        b = dict(self.bucket_shifts)
        b[(i, j)] = b.get((i, j), 0.0) + dv
        return RateVol(self.id, self.ref_date, self.expiries, self.tenors, self.normal, self.kind, self.method,
                       self.smile, self.inputs, self.shift_bp, b, self.halfspread_bp)

    def describe(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind.value, "method": self.method,
                "expiries": self.expiries.tolist(), "tenors": self.tenors.tolist(),
                "normal_bp": (self.normal * 1e4).round(1).tolist()}


def historical_normal_vol(series: dict[str, Sequence[float]], horizon_days: int = 250,
                          ewma_lambda: float | None = 0.97) -> dict[str, float]:
    """Нормальная волатильность по историческим рядам ставок (дневные изменения).

    ``series[tenor] = [ставки по дням]``. EWMA по умолчанию (λ = 0.97).
    """
    out = {}
    for tenor, xs in series.items():
        x = np.asarray(xs, float)[-horizon_days - 1:]
        d = np.diff(x)
        if len(d) < 20:
            continue
        if ewma_lambda:
            w = ewma_lambda ** np.arange(len(d))[::-1]
            var = float(np.sum(w * d * d) / np.sum(w))
        else:
            var = float(np.var(d, ddof=1))
        out[tenor] = float(np.sqrt(var * 252))
    return out


def strip_caplets(cap_maturities: Sequence[float], flat_vols: Sequence[float], caplet_periods: Sequence[tuple[float, float]],
                  forwards: Sequence[float], dfs: Sequence[float], strike: float, normal: bool = True) -> np.ndarray:
    """Caplet stripping: кусочно-постоянные волатильности каплетов по плоским волатильностям капов.

    ``caplet_periods`` — (fixing T, tau), ``forwards`` — форварды каплетов,
    ``dfs`` — дисконт-факторы на даты платежей. Возвращает волатильность
    каждого каплета.
    """
    price = bachelier if normal else black
    T = np.array([p[0] for p in caplet_periods])
    tau = np.array([p[1] for p in caplet_periods])
    F = np.asarray(forwards, float)
    D = np.asarray(dfs, float)
    out = np.zeros(len(T))
    done = 0
    for mat, fv in zip(cap_maturities, flat_vols):
        idx = np.where(T < mat - 1e-9)[0]
        if len(idx) == 0:
            continue
        cap = float(np.sum(price(F[idx], strike, T[idx], fv, D[idx] * tau[idx], 1)))
        new = idx[idx >= done]
        if len(new) == 0:
            continue
        known = float(np.sum(price(F[idx[idx < done]], strike, T[idx[idx < done]], out[idx[idx < done]],
                                   D[idx[idx < done]] * tau[idx[idx < done]], 1))) if done else 0.0

        def f(v):
            return known + float(np.sum(price(F[new], strike, T[new], v, D[new] * tau[new], 1))) - cap
        try:
            out[new] = brentq(f, 1e-6, 5.0 if not normal else 0.5)
        except ValueError:
            out[new] = fv
        done = int(new[-1]) + 1
    out[done:] = out[done - 1] if done else flat_vols[-1]
    return out


__all__ = ["RateVol", "historical_normal_vol", "strip_caplets", "normal_to_lognormal", "lognormal_to_normal"]
