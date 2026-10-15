"""Генерация путей Монте-Карло.

* активы: S(t) = F(t)·exp(X(t)), X — логарифм отклонения от форварда; режимы
  «black» (детерминированная временная структура волатильности, точная
  дискретизация) и «local» (Дюпир, лог-Эйлер с мартингальной поправкой);
  для акций в режиме black — аффинная модель денежных дивидендов (Бюлер);
* ставки: Hull-White 1F в форме Андерсена-Питербарга
  dx = (y(t) − a·x)dt + σ(t)dW, r = f(0,t) + x;
  P(t,T) = P(0,T)/P(0,t)·exp(−G·x − ½G²y);
* корреляции через Холецкого с контролем положительной определённости
  (при нарушении — ближайшая корреляционная матрица по Хайэму, с флагом);
* антитетические переменные, фиксированный seed, детерминированный порядок
  потребления случайных чисел.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from ...vol.localvol import LocalVolGrid


@dataclass
class AssetProcess:
    name: str
    forward: Callable[[np.ndarray], np.ndarray]
    vol_mode: str = "black"                      # 'black' | 'local'
    total_var: Callable[[float], float] | None = None
    lv: LocalVolGrid | None = None
    cash_dividends: list[tuple[float, float]] | None = None   # (t, D) для модели Бюлера
    disc: Callable[[np.ndarray], np.ndarray] | None = None    # DF(t) для дивидендов


@dataclass
class HWProcess:
    name: str                  # 'rate:RUB' и т.п.
    a: float
    sigma_times: np.ndarray    # концы интервалов постоянства σ
    sigmas: np.ndarray
    logdf: Callable[[np.ndarray], np.ndarray]     # ln P(0,t) дисконтной кривой
    inst_fwd: Callable[[np.ndarray], np.ndarray]  # f(0,t)

    def sigma_at(self, t: np.ndarray) -> np.ndarray:
        i = np.clip(np.searchsorted(self.sigma_times, t, side="left"), 0, len(self.sigmas) - 1)
        return self.sigmas[i]

    def y(self, t: np.ndarray) -> np.ndarray:
        """y(t) = ∫₀ᵗ σ(u)² e^{−2a(t−u)} du (кусочно-постоянная σ)."""
        t = np.atleast_1d(np.asarray(t, float))
        out = np.zeros_like(t)
        edges = np.concatenate([[0.0], self.sigma_times])
        for k, tt in enumerate(t):
            acc = 0.0
            for j in range(len(self.sigmas)):
                u0 = edges[j]
                u1 = edges[j + 1] if j + 1 < len(edges) else np.inf
                if j == len(self.sigmas) - 1:
                    u1 = np.inf
                lo, hi = u0, min(u1, tt)
                if hi <= lo:
                    break
                s2 = self.sigmas[j] ** 2
                if self.a > 1e-10:
                    acc += s2 * (np.exp(-2 * self.a * (tt - hi)) - np.exp(-2 * self.a * (tt - lo))) / (2 * self.a)
                else:
                    acc += s2 * (hi - lo)
            out[k] = acc
        return out

    def G(self, t, T):
        if self.a < 1e-10:
            return np.asarray(T) - np.asarray(t)
        return (1 - np.exp(-self.a * (np.asarray(T) - np.asarray(t)))) / self.a

    def bond(self, t: float, T: np.ndarray | float, x: np.ndarray, y_t: float | None = None) -> np.ndarray:
        """P(t,T) по состоянию x(t) — векторно по путям."""
        y_t = float(self.y(np.array([t]))[0]) if y_t is None else y_t
        g = float(self.G(t, T))
        ratio = float(np.exp(self.logdf(np.array([T]))[0] - self.logdf(np.array([t]))[0]))
        return ratio * np.exp(-g * x - 0.5 * g * g * y_t)


@dataclass
class PathSet:
    times: np.ndarray                         # включая 0
    values: dict[str, np.ndarray]             # имя -> (n_paths, n_times)
    step_vol: dict[str, np.ndarray]           # имя -> (n_paths|1, n_times-1) — σ на шаге (для броуновского моста)
    rate_x: dict[str, np.ndarray] = field(default_factory=dict)       # HW: x(t)
    rate_intx: dict[str, np.ndarray] = field(default_factory=dict)    # HW: ∫₀ᵗ x du
    n_paths: int = 0
    seed: int = 0
    diagnostics: dict = field(default_factory=dict)

    def col(self, t: float) -> int:
        i = int(np.searchsorted(self.times, t - 1e-10))
        if i >= len(self.times) or abs(self.times[i] - t) > 1e-8:
            raise KeyError(f"время {t:.6f} отсутствует в сетке симуляции")
        return i


def nearest_correlation(C: np.ndarray, iters: int = 100) -> tuple[np.ndarray, bool]:
    """Ближайшая корреляционная матрица (Higham, 2002). Возвращает (матрица, была_ли_починка)."""
    C = (C + C.T) / 2
    w = np.linalg.eigvalsh(C)
    if w.min() > 1e-10:
        return C, False
    Y = C.copy()
    dS = np.zeros_like(C)
    for _ in range(iters):
        R = Y - dS
        w, V = np.linalg.eigh(R)
        X = V @ np.diag(np.maximum(w, 1e-8)) @ V.T
        dS = X - R
        Y = X.copy()
        np.fill_diagonal(Y, 1.0)
    return Y, True


class Simulator:
    def __init__(self, assets: list[AssetProcess], rates: list[HWProcess], corr: np.ndarray | None, grid: np.ndarray,
                 n_paths: int, seed: int, antithetic: bool = True, martingale_correction: bool = True):
        self.assets = assets
        self.rates = rates
        k = len(assets) + len(rates)
        self.corr = np.eye(k) if corr is None else np.asarray(corr, float)
        self.grid = np.asarray(sorted(set(float(x) for x in grid if x > 1e-12)))
        self.n_paths = int(n_paths) + (int(n_paths) % 2 if antithetic else 0)
        self.seed = int(seed)
        self.antithetic = antithetic
        self.martingale_correction = martingale_correction

    def run(self) -> PathSet:
        k = len(self.assets) + len(self.rates)
        C, repaired = nearest_correlation(self.corr) if k > 1 else (self.corr, False)
        L = np.linalg.cholesky(C + 1e-14 * np.eye(k)) if k > 1 else np.ones((1, 1))
        rng = np.random.Generator(np.random.PCG64(self.seed))
        times = np.concatenate([[0.0], self.grid])
        dts = np.diff(times)
        n = self.n_paths
        half = n // 2 if self.antithetic else n
        nt = len(self.grid)
        X = {a.name: np.zeros((n, nt + 1)) for a in self.assets}
        step_vol: dict[str, np.ndarray] = {}
        # детерминированные волатильности для black
        bvol = {}
        for a in self.assets:
            if a.vol_mode == "black":
                w = np.array([a.total_var(t) if t > 0 else 0.0 for t in times])
                fv = np.maximum(np.diff(w), 1e-14) / dts
                bvol[a.name] = np.sqrt(fv)
                step_vol[a.name] = np.sqrt(fv)[None, :]
            else:
                step_vol[a.name] = np.zeros((n, nt))
        hx = {r.name: np.zeros((n, nt + 1)) for r in self.rates}
        hint = {r.name: np.zeros((n, nt + 1)) for r in self.rates}
        hy = {r.name: r.y(times) for r in self.rates}
        diag = {"martingale_corrections": {}}
        for j in range(nt):
            z = rng.standard_normal((k, half))
            if self.antithetic:
                z = np.concatenate([z, -z], axis=1)
            z = L @ z
            dt = dts[j]
            sq = np.sqrt(dt)
            for i, a in enumerate(self.assets):
                xp = X[a.name][:, j]
                if a.vol_mode == "black":
                    s = bvol[a.name][j]
                    X[a.name][:, j + 1] = xp - 0.5 * s * s * dt + s * sq * z[i]
                else:
                    s = a.lv(times[j], xp)
                    step_vol[a.name][:, j] = s
                    xn = xp - 0.5 * s * s * dt + s * sq * z[i]
                    if self.martingale_correction:
                        c = np.log(np.mean(np.exp(xn)))
                        xn = xn - c
                        diag["martingale_corrections"].setdefault(a.name, []).append(float(c))
                    X[a.name][:, j + 1] = xn
            for i2, r in enumerate(self.rates):
                zi = z[len(self.assets) + i2]
                xp = hx[r.name][:, j]
                sig = float(r.sigma_at(np.array([times[j] + 0.5 * dt]))[0])
                e = np.exp(-r.a * dt)
                yv = hy[r.name]
                # точная дискретизация OU со сносом y(t) (приближение сноса на шаге)
                drift = 0.5 * (yv[j] + yv[j + 1]) * ((1 - e) / r.a if r.a > 1e-10 else dt)
                std = sig * np.sqrt((1 - e * e) / (2 * r.a)) if r.a > 1e-10 else sig * sq
                xn = xp * e + drift + std * zi
                hx[r.name][:, j + 1] = xn
                hint[r.name][:, j + 1] = hint[r.name][:, j] + 0.5 * (xp + xn) * dt
            if self.martingale_correction and self.rates:
                for r in self.rates:
                    m = np.mean(np.exp(-hint[r.name][:, j + 1]))
                    adj = np.log(m)
                    hint[r.name][:, j + 1] += adj
        values = {}
        for a in self.assets:
            F = np.asarray(a.forward(times), float)
            if a.vol_mode == "black" and a.cash_dividends:
                # Бюлер: S = (F − D)·e^X + D, D(t) — форвардная стоимость будущих дивидендов
                Dt = np.zeros_like(times)
                dfs = a.disc(times)
                for td, amt in a.cash_dividends:
                    m = times < td
                    Dt[m] += amt * float(a.disc(np.array([td]))[0]) / dfs[m]
                values[a.name] = (F - Dt)[None, :] * np.exp(X[a.name]) + Dt[None, :]
            else:
                values[a.name] = F[None, :] * np.exp(X[a.name])
        ps = PathSet(times, values, step_vol, hx, hint, n, self.seed, diag)
        ps.diagnostics["correlation_repaired"] = bool(repaired)
        ps.diagnostics["n_steps"] = nt
        return ps
