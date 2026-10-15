"""Локальная волатильность по Дюпиру из поверхности implied vol.

Формула в терминах общей дисперсии w(k, T), k = ln(K/F(T)):

    σ²_loc = ∂_T w / [1 − (k/w)∂_k w + ¼(−¼ − 1/w + k²/w²)(∂_k w)² + ½ ∂²_k w]

Производные — конечными разностями по гладкой (SVI) поверхности. Сетка
кусочно-постоянна по времени между узлами; знаменатель и числитель
ограничиваются снизу (проблемные зоны помечаются в диагностике).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .surface import VolSurface


@dataclass
class LocalVolGrid:
    times: np.ndarray        # концы временных интервалов
    ks: np.ndarray           # сетка ln(S/F(t))
    lv: np.ndarray           # [len(times), len(ks)]
    clipped: int = 0
    diagnostics: dict = field(default_factory=dict)

    def __call__(self, t: float, k: np.ndarray) -> np.ndarray:
        i = min(int(np.searchsorted(self.times, t, side="left")), len(self.times) - 1)
        return np.interp(k, self.ks, self.lv[i])


def dupire_grid(surf: VolSurface, t_max: float, n_t: int = 48, k_width: float = 5.0, n_k: int = 161,
                lv_floor: float = 0.01, lv_cap: float = 3.0) -> LocalVolGrid:
    atm_T = max(t_max, surf.slices[0].T)
    sd = surf.atm_vol(atm_T) * np.sqrt(atm_T)
    kmax = max(k_width * sd, 0.25)
    ks = np.linspace(-kmax, kmax, n_k)
    nodes = sorted(set([s.T for s in surf.slices if s.T < t_max] + list(np.linspace(t_max / n_t, t_max, n_t))))
    times = np.array(nodes)
    lv = np.empty((len(times), len(ks)))
    clipped = 0
    dk = ks[1] - ks[0]
    prev_t = 0.0
    for i, t in enumerate(times):
        tm = 0.5 * (prev_t + t)
        dt = max(min(1e-3, tm * 0.5), 1e-5)
        w = surf.total_variance(ks, tm)
        w_up = surf.total_variance(ks, tm + dt)
        w_dn = surf.total_variance(ks, max(tm - dt, 1e-6))
        dwdt = (w_up - w_dn) / ((tm + dt) - max(tm - dt, 1e-6))
        wk = np.gradient(w, dk)
        wkk = np.gradient(wk, dk)
        w = np.maximum(w, 1e-10)
        den = 1 - ks / w * wk + 0.25 * (-0.25 - 1 / w + ks * ks / (w * w)) * wk * wk + 0.5 * wkk
        bad = (den <= 1e-4) | (dwdt <= 0)
        clipped += int(bad.sum())
        var = np.where(bad, w / tm, dwdt / np.maximum(den, 1e-4))
        lv[i] = np.clip(np.sqrt(np.maximum(var, 0.0)), lv_floor, lv_cap)
        prev_t = t
    return LocalVolGrid(times, ks, lv, clipped, {"k_range": [float(ks[0]), float(ks[-1])], "clipped_points": clipped})
