"""SABR (Hagan et al., 2002): логнормальная (со сдвигом) и нормальная волатильность."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares


@dataclass(frozen=True)
class SABR:
    alpha: float
    beta: float
    rho: float
    nu: float
    shift: float = 0.0

    def lognormal_vol(self, F, K, T):
        F = np.asarray(F, float) + self.shift
        K = np.asarray(K, float) + self.shift
        a, b, r, n = self.alpha, self.beta, self.rho, self.nu
        fk = F * K
        lfk = np.log(F / K)
        omb = 1 - b
        fkb = fk ** (omb / 2)
        z = n / a * fkb * lfk
        with np.errstate(divide="ignore", invalid="ignore"):
            xz = np.log((np.sqrt(1 - 2 * r * z + z * z) + z - r) / (1 - r))
            zx = np.where(np.abs(z) < 1e-7, 1 - 0.5 * r * z, z / xz)
        den = fkb * (1 + omb ** 2 / 24 * lfk ** 2 + omb ** 4 / 1920 * lfk ** 4)
        corr = 1 + (omb ** 2 / 24 * a * a / fk ** omb + 0.25 * r * b * n * a / fkb + (2 - 3 * r * r) / 24 * n * n) * T
        return a / den * zx * corr

    def normal_vol(self, F, K, T):
        """Нормальная (Башелье) волатильность SABR — аппроксимация Хагана."""
        F = np.asarray(F, float) + self.shift
        K = np.asarray(K, float) + self.shift
        a, b, r, n = self.alpha, self.beta, self.rho, self.nu
        F, K = np.broadcast_arrays(F, K)
        fm = np.sqrt(F * K)
        omb = 1.0 - b
        near = np.abs(F - K) < 1e-10 * np.maximum(np.abs(F), 1e-10)
        with np.errstate(divide="ignore", invalid="ignore"):
            if abs(omb) < 1e-12:          # β = 1
                ratio = np.where(near, F, (F - K) / np.log(F / K))
                zeta = n / a * np.log(F / K)
            elif abs(b) < 1e-12:          # β = 0
                ratio = np.ones_like(F)
                zeta = n / a * (F - K)
            else:
                ratio = np.where(near, fm ** b, (F - K) * omb / (F ** omb - K ** omb))
                zeta = n / a * (F ** omb - K ** omb) / omb
            xz = np.log((np.sqrt(1 - 2 * r * zeta + zeta * zeta) + zeta - r) / (1 - r))
            zx = np.where(np.abs(zeta) < 1e-7, 1 - 0.5 * r * zeta, zeta / xz)
        corr = 1 + (-b * (2 - b) * a * a / (24 * fm ** (2 - 2 * b)) + 0.25 * r * a * b * n / fm ** omb
                    + (2 - 3 * r * r) / 24 * n * n) * T
        return a * ratio * zx * corr


def fit_sabr(F: float, T: float, strikes, vols, beta: float = 1.0, shift: float = 0.0, normal: bool = False) -> tuple[SABR, float]:
    strikes = np.asarray(strikes, float)
    vols = np.asarray(vols, float)
    atm = float(np.interp(F, strikes, vols)) if strikes.min() <= F <= strikes.max() else float(vols[len(vols) // 2])

    def mk(x):
        return SABR(np.exp(x[0]), beta, np.tanh(x[1]), np.exp(x[2]), shift)

    def res(x):
        s = mk(x)
        mv = s.normal_vol(F, strikes, T) if normal else s.lognormal_vol(F, strikes, T)
        return (mv - vols) * 1e4

    a0 = atm * (F + shift) ** (1 - beta) if not normal else atm / (F + shift) ** beta
    best = None
    for r0 in (-0.3, 0.0, 0.3):
        x0 = np.array([np.log(max(a0, 1e-6)), np.arctanh(r0), np.log(0.5)])
        sol = least_squares(res, x0, method="lm", max_nfev=2000)
        c = float(np.sum(sol.fun ** 2))
        if best is None or c < best[0]:
            best = (c, sol.x)
    s = mk(best[1])
    rmse = float(np.sqrt(np.mean(((s.normal_vol(F, strikes, T) if normal else s.lognormal_vol(F, strikes, T)) - vols) ** 2)))
    return s, rmse
