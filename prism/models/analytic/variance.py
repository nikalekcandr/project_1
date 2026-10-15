"""Вариансный своп — статическая репликация портфелем опционов по страйкам.

K_var = (2/T)·[∫₀^F P(K)/K² dK + ∫_F^∞ C(K)/K² dK]  (недисконтированные цены).

Репликация опирается на непрерывный набор страйков; при разреженной
поверхности возникает систематическая ошибка. Модуль выводит её оценку:
ошибку дискретизации (сумма по доступным страйкам против плотной сетки) и
ошибку усечения (за пределами крайних котируемых страйков).
"""
from __future__ import annotations

import numpy as np

from .black import black


def _integrand(F: float, T: float, vol_fn, Ks: np.ndarray) -> np.ndarray:
    out = np.empty_like(Ks)
    for i, K in enumerate(Ks):
        cp = -1 if K < F else 1
        out[i] = float(black(F, K, T, float(vol_fn(K)), 1.0, cp)) / (K * K)
    return out


def replicate_variance(F: float, T: float, vol_fn, quoted_strikes, n_dense: int = 2001, width_sd: float = 8.0) -> dict:
    sd = float(vol_fn(F)) * np.sqrt(T)
    lo, hi = F * np.exp(-width_sd * sd), F * np.exp(width_sd * sd)
    # «непрерывный» эталон — плотная сетка по гладкой поверхности
    Kd = np.exp(np.linspace(np.log(lo), np.log(hi), n_dense))
    Kd = np.union1d(Kd, [F])
    dense = float(np.trapezoid(_integrand(F, T, vol_fn, Kd), Kd)) * 2 / T
    # только котируемые страйки
    Kq = np.array(sorted(set(float(k) for k in quoted_strikes) | {F}))
    disc = float(np.trapezoid(_integrand(F, T, vol_fn, Kq), Kq)) * 2 / T if len(Kq) > 1 else float("nan")
    # плотная сетка внутри котируемого диапазона — изолирует ошибку усечения
    Ki = np.exp(np.linspace(np.log(Kq.min()), np.log(Kq.max()), n_dense))
    Ki = np.union1d(Ki, [F])
    inner = float(np.trapezoid(_integrand(F, T, vol_fn, Ki), Ki)) * 2 / T
    return {
        "fair_variance": dense,
        "fair_vol": float(np.sqrt(dense)),
        "discrete_variance": disc,
        "discretization_error": disc - inner,
        "truncation_error": inner - dense,
        "total_error": disc - dense,
        "total_error_vol_pts": (np.sqrt(max(disc, 0)) - np.sqrt(dense)) * 100,
        "strikes_used": Kq.tolist(),
    }


def vol_swap_convexity(fair_var: float, var_of_var: float) -> float:
    """E[√V] ≈ √E[V] − Var(V)/(8·E[V]^{3/2}) (Brockhaus-Long)."""
    return float(np.sqrt(fair_var) - var_of_var / (8 * fair_var ** 1.5))
