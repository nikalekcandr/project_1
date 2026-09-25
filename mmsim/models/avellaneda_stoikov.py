"""Модель Авельянеды–Стойкова (Avellaneda & Stoikov, 2008).

«High-frequency trading in a limit order book», Quantitative Finance 8(3).

Предпосылки: mid-цена — арифметическое броуновское движение dS = σ dW;
лимитная заявка на расстоянии δ от mid исполняется с интенсивностью
λ(δ) = A·exp(−kδ); маркет-мейкер максимизирует E[−exp(−γ·(X_T + q_T·S_T))].

Единицы (важно для калибровки):
    S, δ, r — рубли (или пункты для фьючерсов);
    σ — руб./√с; τ = T − t — секунды; A — 1/с; k — 1/руб.;
    q — запас в единицах размера котировки (order_size лотов);
    γ — неприятие риска, 1/(руб.·ед. запаса).

Все функции векторизованы по numpy.
"""

from __future__ import annotations

import numpy as np


def reservation_price(mid, q, gamma, sigma, tau):
    """Резервационная (индифферентная) цена r = s − q·γ·σ²·(T − t)."""
    return mid - q * gamma * sigma**2 * tau


def optimal_spread(gamma, sigma, tau, k):
    """Оптимальный суммарный спред δᵃ + δᵇ = γσ²(T − t) + (2/γ)·ln(1 + γ/k)."""
    return gamma * sigma**2 * tau + (2.0 / gamma) * np.log1p(gamma / k)


def liquidity_half_spread(gamma, k):
    """Компонента спреда, отвечающая за интенсивность потока: (1/γ)·ln(1 + γ/k)."""
    return np.log1p(gamma / k) / gamma


def quotes(mid, q, gamma, sigma, tau, k):
    """Оптимальные котировки конечного горизонта.

    Возвращает (bid, ask, reservation, spread).
    """
    r = reservation_price(mid, q, gamma, sigma, tau)
    spread = optimal_spread(gamma, sigma, tau, k)
    return r - spread / 2.0, r + spread / 2.0, r, spread


def infinite_horizon_quotes(mid, q, gamma, sigma, k, q_max, omega=None):
    """Вариант бесконечного горизонта (раздел 2.3 статьи) с ограничением |q| ≤ q_max.

    rᵃ = s + (1/γ)·ln(1 + (1 − 2q)γ²σ² / (2ω − γ²q²σ²)),
    rᵇ = s + (1/γ)·ln(1 + (−1 − 2q)γ²σ² / (2ω − γ²q²σ²)),
    ω = ½γ²σ²(q_max + 1)², котировки: rᵇ − c, rᵃ + c, c = (1/γ)ln(1 + γ/k).
    Возвращает (bid, ask, reservation, spread).
    """
    g2s2 = gamma**2 * sigma**2
    if omega is None:
        omega = 0.5 * g2s2 * (q_max + 1) ** 2
    denom = 2.0 * omega - g2s2 * np.asarray(q, dtype=float) ** 2
    ra = mid + np.log1p((1.0 - 2.0 * q) * g2s2 / denom) / gamma
    rb = mid + np.log1p((-1.0 - 2.0 * q) * g2s2 / denom) / gamma
    c = liquidity_half_spread(gamma, k)
    bid, ask = rb - c, ra + c
    return bid, ask, (ra + rb) / 2.0, ask - bid


def fill_intensity(delta, A, k):
    """Интенсивность исполнения λ(δ) = A·exp(−kδ), δ ≥ 0 (для δ < 0 — как при δ = 0)."""
    return A * np.exp(-k * np.maximum(delta, 0.0))
