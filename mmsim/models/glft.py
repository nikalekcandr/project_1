"""Модель Геана–Лелаля–Фернандес-Тапиа (GLFT) — развитие Авельянеды–Стойкова.

Guéant, Lehalle, Fernandez-Tapia (2013), «Dealing with the inventory risk:
a solution to the market making problem», Mathematics and Financial Economics 7.

Та же постановка (CARA-полезность, λ(δ) = A·exp(−kδ)), но с жёстким ограничением
запаса q ∈ [−Q, Q]. Задача сводится к линейной системе ОДУ, решение — матричная
экспонента; при τ → ∞ котировки выходят на стационар, для которого есть
замкнутая асимптотическая формула. Единицы — как в ``avellaneda_stoikov``.
"""

from __future__ import annotations

import numpy as np

from mmsim.models.avellaneda_stoikov import liquidity_half_spread


def _c2(gamma, sigma, A, k):
    return np.sqrt(gamma / (2.0 * A * k) * (1.0 + gamma / k) ** (1.0 + k / gamma)) * sigma


def asymptotic_depths(q, gamma, sigma, A, k):
    """Асимптотические (τ → ∞) расстояния котировок от mid.

    δᵇ ≈ (1/γ)ln(1 + γ/k) + (2q + 1)/2 · σ·√(γ/(2kA)·(1 + γ/k)^(1 + k/γ)),
    δᵃ ≈ (1/γ)ln(1 + γ/k) − (2q − 1)/2 · σ·√(…).
    Возвращает (delta_bid, delta_ask).
    """
    c1 = liquidity_half_spread(gamma, k)
    c2 = _c2(gamma, sigma, A, k)
    q = np.asarray(q, dtype=float)
    return c1 + (2.0 * q + 1.0) / 2.0 * c2, c1 - (2.0 * q - 1.0) / 2.0 * c2


def asymptotic_quotes(mid, q, gamma, sigma, A, k):
    """Котировки GLFT-асимптотики: (bid, ask, reservation, spread)."""
    db, da = asymptotic_depths(q, gamma, sigma, A, k)
    bid, ask = mid - db, mid + da
    return bid, ask, (bid + ask) / 2.0, db + da


class GLFTSolver:
    """Точное решение конечного горизонта с ограничением запаса |q| ≤ Q.

    v(t) = exp(−M·(T − t))·v(T), M — трёхдиагональная (2Q+1)×(2Q+1):
        M[q, q] = α q², M[q, q±1] = −η, α = (k/2)·γ·σ², η = A·(1 + γ/k)^−(1 + k/γ);
    v_q(T) = exp(−k·b·q²) (b — штраф за остаток запаса в конце горизонта, 0 — нет).
    Котировки: δᵇ(t, q) = (1/k)·ln(v_q / v_{q+1}) + (1/γ)ln(1 + γ/k),
               δᵃ(t, q) = (1/k)·ln(v_q / v_{q−1}) + (1/γ)ln(1 + γ/k).
    Матрица симметрична, поэтому экспонента считается через спектральное
    разложение; общий множитель exp(−λ_min τ) сокращается в отношениях, что
    устраняет переполнение при больших τ.
    """

    def __init__(self, gamma: float, sigma: float, A: float, k: float, q_max: int, terminal_penalty: float = 0.0):
        if q_max < 1:
            raise ValueError("q_max должен быть ≥ 1")
        self.gamma, self.sigma, self.A, self.k, self.Q = gamma, sigma, A, k, int(q_max)
        self.qs = np.arange(-self.Q, self.Q + 1)
        alpha = 0.5 * k * gamma * sigma**2
        eta = A * (1.0 + gamma / k) ** (-(1.0 + k / gamma))
        n = len(self.qs)
        M = np.diag(alpha * self.qs.astype(float) ** 2)
        off = -eta * np.ones(n - 1)
        M += np.diag(off, 1) + np.diag(off, -1)
        self.eigval, self.eigvec = np.linalg.eigh(M)
        vT = np.exp(-k * terminal_penalty * self.qs.astype(float) ** 2)
        self._proj = self.eigvec.T @ vT
        self.c1 = float(liquidity_half_spread(gamma, k))

    def value_vector(self, tau: float) -> np.ndarray:
        lam = self.eigval - self.eigval.min()
        return self.eigvec @ (np.exp(-lam * max(tau, 0.0)) * self._proj)

    def depths(self, tau: float, q: int) -> tuple[float, float]:
        """(δᵇ, δᵃ); на границе запаса соответствующая сторона = +inf."""
        q = int(np.clip(q, -self.Q, self.Q))
        v = np.maximum(self.value_vector(tau), 1e-300)
        i = q + self.Q
        db = np.inf if q >= self.Q else float(np.log(v[i] / v[i + 1]) / self.k + self.c1)
        da = np.inf if q <= -self.Q else float(np.log(v[i] / v[i - 1]) / self.k + self.c1)
        return db, da

    def quotes(self, mid: float, q: int, tau: float):
        db, da = self.depths(tau, q)
        bid = mid - db if np.isfinite(db) else np.nan
        ask = mid + da if np.isfinite(da) else np.nan
        if np.isfinite(db) and np.isfinite(da):
            return bid, ask, (bid + ask) / 2.0, db + da
        return bid, ask, np.nan, np.nan
