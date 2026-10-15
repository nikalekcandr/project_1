"""Спред-опционы: аппроксимация Кирка, Маргрейб (K = 0).

Блэк на спред неприменим: спред бывает отрицательным. Кирк работает для
K > −F2; иначе — Монте-Карло.
"""
from __future__ import annotations

import numpy as np

from .black import black


def kirk(F1: float, F2: float, K: float, T: float, s1: float, s2: float, rho: float, df: float, cp: int = 1,
         a: float = 1.0, b: float = 1.0) -> float:
    """Опцион на a·F1 − b·F2 − K."""
    F1, F2 = a * F1, b * F2
    if F2 + K <= 0:
        raise ValueError("Кирк неприменим при F2 + K ≤ 0 — используйте Монте-Карло")
    w = F2 / (F2 + K)
    sig = np.sqrt(s1 * s1 - 2 * rho * s1 * s2 * w + (s2 * w) ** 2)
    call = (F2 + K) * float(black(F1 / (F2 + K), 1.0, T, sig, df, 1))
    if cp == 1:
        return call
    return call - df * (F1 - F2 - K)


def margrabe(F1: float, F2: float, T: float, s1: float, s2: float, rho: float, df: float) -> float:
    sig = np.sqrt(s1 * s1 + s2 * s2 - 2 * rho * s1 * s2)
    return float(black(F1, F2, T, sig, df, 1))
