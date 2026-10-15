"""Кривая бескупонной доходности ОФЗ (КБД Мосбиржи).

Формула Мосбиржи (параметры B1=β0, B2=β1, B3=β2, T1=τ, G1..G9 — в б.п.):

    G(t) = β0 + (β1+β2)·τ/t·(1−e^{−t/τ}) − β2·e^{−t/τ} + Σ g_i·exp(−(t−a_i)²/b_i²)

a1=0, a2=0.6, a_{i+1}=a_i+a2·k^{i−1}; b1=a2, b_{i+1}=b_i·k; k=1.6.
G — непрерывно начисляемая доходность в б.п.; годовая доходность КБД
Y(t) = exp(G/10⁴) − 1.
"""
from __future__ import annotations

from datetime import date

import numpy as np

from ..core.provenance import UsedInput
from .base import YieldCurve

_K = 1.6


def _ab():
    a = [0.0, 0.6]
    for i in range(2, 9):
        a.append(a[-1] + 0.6 * _K ** (i - 1))
    b = [0.6]
    for _ in range(8):
        b.append(b[-1] * _K)
    return np.array(a), np.array(b)


A_I, B_I = _ab()


def kbd_g(t, p: dict) -> np.ndarray:
    t = np.maximum(np.asarray(t, dtype=float), 1e-6)
    b0, b1, b2, tau = p["B1"], p["B2"], p["B3"], p["T1"]
    x = t / tau
    g = b0 + (b1 + b2) * (1 - np.exp(-x)) / x - b2 * np.exp(-x)
    for i in range(9):
        gi = p.get(f"G{i + 1}", 0.0)
        if gi:
            g = g + gi * np.exp(-((t - A_I[i]) ** 2) / B_I[i] ** 2)
    return g


def kbd_yield(t, p: dict) -> np.ndarray:
    """Годовая эффективная доходность КБД (доли)."""
    return np.expm1(kbd_g(t, p) / 1e4)


def kbd_curve(ref: date, params: dict, inputs: list[UsedInput] | None = None, cid: str = "RUB.OFZ",
              max_t: float = 30.0) -> YieldCurve:
    ts = np.concatenate([np.linspace(0.05, 2.0, 40), np.linspace(2.25, max_t, 56)])
    z = kbd_g(ts, params) / 1e4
    return YieldCurve(cid, ref, ts, -z * ts, "monotone_convex", "RUB", "КБД Мосбиржи (NSS + G-поправки)",
                      extrap_start=max_t, inputs=inputs or [], meta={"params": dict(params)})
