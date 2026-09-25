"""Воспроизведение численного эксперимента из статьи Авельянеды–Стойкова (2008).

Постановка раздела 4 статьи: s₀ = 100, T = 1, σ = 2, dt = 0.005, q₀ = 0,
A = 140, k = 1.5; mid за шаг меняется на ±σ√dt с вероятностью ½; заявка на
расстоянии δ исполняется за шаг с вероятностью λ(δ)·dt = A·e^{−kδ}·dt.
Сравниваются inventory-стратегия (котировки вокруг резервационной цены) и
симметричная стратегия с тем же средним спредом вокруг mid.

Симуляция векторизована по траекториям.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from mmsim.models import avellaneda_stoikov as AS


@dataclass
class PaperSetup:
    s0: float = 100.0
    T: float = 1.0
    sigma: float = 2.0
    dt: float = 0.005
    A: float = 140.0
    k: float = 1.5
    n_paths: int = 1000
    seed: int = 1


def average_spread(gamma: float, p: PaperSetup) -> float:
    taus = p.T - np.arange(int(round(p.T / p.dt))) * p.dt
    return float(np.mean(AS.optimal_spread(gamma, p.sigma, taus, p.k)))


def simulate(gamma: float, strategy: str = "inventory", setup: PaperSetup | None = None, keep_path: bool = False):
    """Возвращает (profit, final_q[, path]) по n_paths траекториям."""
    p = setup or PaperSetup()
    rng = np.random.default_rng(p.seed)  # одинаковые шоки для обеих стратегий
    n_steps = int(round(p.T / p.dt))
    s = np.full(p.n_paths, p.s0)
    q = np.zeros(p.n_paths)
    x = np.zeros(p.n_paths)
    half_sym = average_spread(gamma, p) / 2.0
    path = []
    for step in range(n_steps):
        tau = p.T - step * p.dt
        if strategy == "inventory":
            bid, ask, r, _ = AS.quotes(s, q, gamma, p.sigma, tau, p.k)
        elif strategy == "symmetric":
            bid, ask, r = s - half_sym, s + half_sym, s
        else:
            raise ValueError("strategy: inventory | symmetric")
        pb = np.minimum(AS.fill_intensity(s - bid, p.A, p.k) * p.dt, 1.0)
        pa = np.minimum(AS.fill_intensity(ask - s, p.A, p.k) * p.dt, 1.0)
        u_b, u_a, u_s = rng.random((3, p.n_paths))
        fb, fa = u_b < pb, u_a < pa
        q += fb.astype(float) - fa.astype(float)
        x += np.where(fa, ask, 0.0) - np.where(fb, bid, 0.0)
        if keep_path:
            path.append((step * p.dt, s[0], np.broadcast_to(r, s.shape)[0], bid[0] if np.ndim(bid) else bid,
                         ask[0] if np.ndim(ask) else ask, q[0]))
        s = s + np.where(u_s < 0.5, 1.0, -1.0) * p.sigma * np.sqrt(p.dt)
    profit = x + q * s
    if keep_path:
        cols = ["t", "mid", "reservation", "bid", "ask", "inventory"]
        return profit, q, pd.DataFrame(path, columns=cols)
    return profit, q


def table(gammas=(0.1, 0.01, 0.5), setup: PaperSetup | None = None) -> pd.DataFrame:
    """Таблица в формате статьи: спред, средняя прибыль, ст. откл. прибыли, итоговый запас."""
    p = setup or PaperSetup()
    rows = []
    for g in gammas:
        for strat in ("inventory", "symmetric"):
            profit, q = simulate(g, strat, p)
            rows.append({
                "gamma": g,
                "strategy": strat,
                "avg_spread": average_spread(g, p),
                "profit_mean": profit.mean(),
                "profit_std": profit.std(ddof=1),
                "final_q_mean": q.mean(),
                "final_q_std": q.std(ddof=1),
            })
    return pd.DataFrame(rows)
