"""Vanna-volga — рыночный стандарт оценки FX-экзотики на развивающихся рынках.

Цена = BS(σ_ATM) + p · Σ x_i·[C_mkt(K_i) − C_BS(K_i; σ_ATM)], где веса x_i
подбираются так, чтобы портфель из 25Δ-пута, ATM и 25Δ-колла воспроизводил
вегу, ванну и волгу экзотики при σ_ATM (Castagna & Mercurio, 2007).
Для барьеров поправка взвешивается вероятностью выживания p (no-touch),
как принято в дилерской практике; KI считается как ваниль минус KO, что
сохраняет паритет.
"""
from __future__ import annotations

from typing import Callable

import numpy as np

from .black import black


def _bs_greeks_fd(price_fn: Callable[[float, float], float], S: float, sigma: float, hs: float = 1e-3, hv: float = 1e-3):
    """Вега, ванна, волга конечными разностями функции price(S, σ)."""
    dS = S * hs
    p = price_fn
    vega = (p(S, sigma + hv) - p(S, sigma - hv)) / (2 * hv)
    volga = (p(S, sigma + hv) - 2 * p(S, sigma) + p(S, sigma - hv)) / (hv * hv)
    vanna = (p(S + dS, sigma + hv) - p(S + dS, sigma - hv) - p(S - dS, sigma + hv) + p(S - dS, sigma - hv)) / (4 * dS * hv)
    return np.array([vega, vanna, volga])


def vv_weights(S: float, T: float, rd: float, rf: float, sigma_atm: float, strikes: tuple[float, float, float]):
    """Матрица греков столпов (25P, ATM, 25C) при σ_ATM."""
    def vanilla(K, cp):
        return lambda s, v: float(black(s * np.exp((rd - rf) * T), K, T, v, np.exp(-rd * T), cp))
    k1, k2, k3 = strikes
    cols = [_bs_greeks_fd(vanilla(k1, -1), S, sigma_atm), _bs_greeks_fd(vanilla(k2, 1), S, sigma_atm),
            _bs_greeks_fd(vanilla(k3, 1), S, sigma_atm)]
    return np.column_stack(cols)


def vanna_volga_price(price_fn: Callable[[float, float], float], S: float, T: float, rd: float, rf: float,
                      sigma_atm: float, pillar_strikes: tuple[float, float, float],
                      pillar_vols: tuple[float, float, float], survival: float = 1.0) -> dict:
    """VV-цена для произвольной выплаты, заданной функцией BS-цены price_fn(S, σ)."""
    A = vv_weights(S, T, rd, rf, sigma_atm, pillar_strikes)
    g = _bs_greeks_fd(price_fn, S, sigma_atm)
    try:
        x = np.linalg.solve(A, g)
    except np.linalg.LinAlgError:  # pragma: no cover
        x = np.linalg.lstsq(A, g, rcond=None)[0]
    F = S * np.exp((rd - rf) * T)
    df = np.exp(-rd * T)
    cps = (-1, 1, 1)
    costs = np.array([float(black(F, K, T, v, df, cp)) - float(black(F, K, T, sigma_atm, df, cp))
                      for K, v, cp in zip(pillar_strikes, pillar_vols, cps)])
    corr = float(x @ costs)
    bs = price_fn(S, sigma_atm)
    return {"price": bs + survival * corr, "bs_atm": bs, "correction": corr, "survival_weight": survival,
            "weights": x.tolist(), "pillar_costs": costs.tolist()}
