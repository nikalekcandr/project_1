"""Raw SVI (Gatheral): w(k) = a + b·(ρ(k−m) + √((k−m)² + σ²)).

k = ln(K/F), w — общая дисперсия σ²T. Подгонка с ограничениями и штрафом
за бабочковый арбитраж (функция g(k) Гатерала должна быть ≥ 0).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares


@dataclass(frozen=True)
class SVI:
    a: float
    b: float
    rho: float
    m: float
    sigma: float

    def w(self, k):
        k = np.asarray(k, dtype=float)
        x = k - self.m
        return self.a + self.b * (self.rho * x + np.sqrt(x * x + self.sigma ** 2))

    def dw(self, k):
        x = np.asarray(k, dtype=float) - self.m
        return self.b * (self.rho + x / np.sqrt(x * x + self.sigma ** 2))

    def d2w(self, k):
        x = np.asarray(k, dtype=float) - self.m
        s2 = self.sigma ** 2
        return self.b * s2 / (x * x + s2) ** 1.5

    def g(self, k):
        """Плотность ≥ 0 ⇔ g(k) ≥ 0 (условие отсутствия бабочкового арбитража)."""
        k = np.asarray(k, dtype=float)
        w = np.maximum(self.w(k), 1e-12)
        w1, w2 = self.dw(k), self.d2w(k)
        return (1 - k * w1 / (2 * w)) ** 2 - w1 * w1 / 4 * (1 / w + 0.25) + w2 / 2

    def params(self) -> dict:
        return {"a": self.a, "b": self.b, "rho": self.rho, "m": self.m, "sigma": self.sigma}


def _qe_inner(k, w, wt, m, sig):
    """Квази-явная SVI (Zeliade): при фиксированных (m, σ) — линейный МНК по (a, d, c)."""
    y = (k - m) / sig
    X = np.column_stack([np.ones_like(y), y, np.sqrt(y * y + 1)])
    W = np.sqrt(wt)
    coef, *_ = np.linalg.lstsq(X * W[:, None], w * W, rcond=None)
    a, d, c = coef
    c = float(np.clip(c, 1e-8, 4 * sig))
    d = float(np.clip(d, -c * 0.999, c * 0.999))
    a = float(np.clip(a, -c * sig * np.sqrt(max(1 - (d / c) ** 2, 0)) + 1e-10, max(w.max(), 1e-8)))
    resid = (a + d * y + c * np.sqrt(y * y + 1) - w) * W
    return (a, d, c), float(resid @ resid)


def fit_svi(k: np.ndarray, w: np.ndarray, weights: np.ndarray | None = None, arb_penalty: float = 50.0) -> tuple[SVI, float]:
    """Подгонка SVI: квази-явный метод + проверка бабочкового арбитража (при нарушении — штрафная доводка).

    Возвращает (параметры, RMSE по волатильности при T=1).
    """
    from scipy.optimize import minimize
    k = np.asarray(k, float)
    w = np.asarray(w, float)
    wt = np.ones_like(w) if weights is None else np.asarray(weights, float)
    span = max(float(k.max() - k.min()), 0.05)
    best = None
    for m0 in (0.0, float(k[np.argmin(w)])):
        for s0 in (0.1 * span, 0.4 * span):
            def obj(x):
                m, ls = x
                return _qe_inner(k, w, wt, m, np.exp(ls))[1]
            r = minimize(obj, np.array([m0, np.log(max(s0, 1e-3))]), method="Nelder-Mead",
                         options={"xatol": 1e-7, "fatol": 1e-14, "maxiter": 600})
            if best is None or r.fun < best[0]:
                best = (r.fun, r.x)
    m, ls = best[1]
    sig = float(np.exp(ls))
    (a, d, c), _ = _qe_inner(k, w, wt, m, sig)
    svi = SVI(a, c / sig, d / c, m, sig)
    kg = np.linspace(min(k.min(), -1.0) * 1.5, max(k.max(), 1.0) * 1.5, 241)
    if svi.g(kg).min() < -1e-8:
        svi = _constrained(k, w, wt, kg, svi)
    rmse = float(np.sqrt(np.mean((np.sqrt(np.maximum(svi.w(k), 0)) - np.sqrt(w)) ** 2)))
    return svi, rmse


def _constrained(k, w, wt, kg, qe: SVI) -> SVI:
    """Подгонка SVI с ограничением отсутствия бабочкового арбитража g(k) ≥ 0 (SLSQP, несколько стартов).

    Точная интерполяция пяти столпов часто даёт арбитражную форму; здесь
    ищется ближайшая по точкам безарбитражная параметризация.
    """
    from scipy.optimize import minimize
    T_w = float(np.interp(0.0, k, w)) if k.min() <= 0 <= k.max() else float(w.min())
    slope = float(np.polyfit(k, w, 1)[0])
    starts = [np.array([qe.a, qe.b, qe.rho, qe.m, qe.sigma])]
    for rho0 in (np.sign(slope) * 0.5, 0.0):
        for s0 in (0.15, 0.4):
            starts.append(np.array([T_w * 0.5, max(abs(slope), 0.05) * 1.5, rho0, 0.0, s0]))
    bounds = [(-1.0, max(w.max(), 1e-6)), (1e-6, 4.0), (-0.999, 0.999), (-1.0, 1.0), (1e-3, 2.0)]

    def mk(x):
        return SVI(x[0], x[1], x[2], x[3], x[4])

    def obj(x):
        s_ = mk(x)
        return float(np.sum(wt * (s_.w(k) - w) ** 2)) * 1e6

    cons = [{"type": "ineq", "fun": lambda x: mk(x).g(kg)},
            {"type": "ineq", "fun": lambda x: x[0] + x[1] * x[4] * np.sqrt(1 - x[2] ** 2)}]
    best = None
    for x0 in starts:
        x0 = np.clip(x0, [b[0] for b in bounds], [b[1] for b in bounds])
        try:
            r = minimize(obj, x0, method="SLSQP", bounds=bounds, constraints=cons, options={"maxiter": 500, "ftol": 1e-14})
        except Exception:  # pragma: no cover
            continue
        s_ = mk(r.x)
        gmin = float(s_.g(kg).min())
        key = (gmin < -1e-7, r.fun)
        if best is None or key < best[0]:
            best = (key, s_)
    return best[1] if best is not None else qe


def _penalized(k, w, wt, start: SVI, kg, arb_penalty) -> SVI:
    def unpack(x):
        a, lb, r, m, ls = x
        return SVI(a, np.exp(lb), np.tanh(r), m, np.exp(ls))

    def res(x):
        s = unpack(x)
        r1 = wt * (np.sqrt(np.maximum(s.w(k), 1e-12)) - np.sqrt(w)) * 100.0
        r2 = arb_penalty * np.minimum(s.g(kg), 0.0)
        r3 = arb_penalty * np.minimum(s.a + s.b * s.sigma * np.sqrt(1 - s.rho ** 2), 0.0) * 100
        return np.concatenate([r1, r2, [r3]])
    x0 = np.array([start.a, np.log(max(start.b, 1e-6)), np.arctanh(np.clip(start.rho, -0.99, 0.99)), start.m,
                   np.log(max(start.sigma, 1e-4))])
    sol = least_squares(res, x0, method="trf", max_nfev=400)
    return unpack(sol.x)
