"""Барьерные и касательные опционы под плоской волатильностью.

* одиночный барьер (Reiner & Rubinstein, 1991) — 8 типов, ребейт при касании
  (для out) или в дату экспирации;
* one-touch / no-touch с выплатой при касании или в конце;
* поправка Broadie-Glasserman-Kou для дискретного наблюдения:
  H → H·exp(±0.5826·σ·√Δt);
* двойной барьер knock-out (Ikeda & Kunitomo, 1992), double-no-touch (Hui, 1996).

Параметры в терминах GK: S — спот, r — ставка валюты выплаты, q — ставка
базовой валюты (FX) / дивидендная доходность, b = r − q.
Чистая аналитика под плоской волатильностью для FX непригодна как итоговая
цена — используется как ядро для vanna-volga и как проверка.
"""
from __future__ import annotations

import numpy as np
from scipy.special import ndtr as N

BGK_BETA = 0.5825971579390106  # −ζ(1/2)/√(2π)


def bgk_shift(H: float, S: float, sigma: float, dt: float) -> float:
    """Сдвиг барьера для дискретного наблюдения (Broadie, Glasserman, Kou 1997)."""
    up = H > S
    return H * np.exp((1 if up else -1) * BGK_BETA * sigma * np.sqrt(dt))


def _terms(S, X, H, T, r, b, sigma, phi, eta):
    sT = sigma * np.sqrt(T)
    mu = (b - 0.5 * sigma ** 2) / sigma ** 2
    lam = np.sqrt(mu ** 2 + 2 * r / sigma ** 2)
    x1 = np.log(S / X) / sT + (1 + mu) * sT
    x2 = np.log(S / H) / sT + (1 + mu) * sT
    y1 = np.log(H * H / (S * X)) / sT + (1 + mu) * sT
    y2 = np.log(H / S) / sT + (1 + mu) * sT
    z = np.log(H / S) / sT + lam * sT
    eb = np.exp((b - r) * T)
    er = np.exp(-r * T)
    hs = H / S
    A = phi * S * eb * N(phi * x1) - phi * X * er * N(phi * x1 - phi * sT)
    B = phi * S * eb * N(phi * x2) - phi * X * er * N(phi * x2 - phi * sT)
    C = phi * S * eb * hs ** (2 * (mu + 1)) * N(eta * y1) - phi * X * er * hs ** (2 * mu) * N(eta * y1 - eta * sT)
    D = phi * S * eb * hs ** (2 * (mu + 1)) * N(eta * y2) - phi * X * er * hs ** (2 * mu) * N(eta * y2 - eta * sT)
    nt = N(eta * x2 - eta * sT) - hs ** (2 * mu) * N(eta * y2 - eta * sT)     # вероятность не коснуться
    hit_pv = hs ** (mu + lam) * N(eta * z) + hs ** (mu - lam) * N(eta * z - 2 * eta * lam * sT)  # PV 1 при касании
    return A, B, C, D, nt, hit_pv, er


def barrier_price(S: float, X: float, H: float, T: float, r: float, q: float, sigma: float, cp: int,
                  direction: str, kind: str, rebate: float = 0.0, rebate_at_hit: bool = True) -> float:
    """Цена одиночного барьерного опциона (за единицу базиса, в валюте выплаты).

    Если спот уже за барьером: knock-out = ребейт, knock-in = ваниль.
    """
    b = r - q
    if T <= 0:
        intrinsic = max(cp * (S - X), 0.0)
        breached = (S <= H) if direction == "down" else (S >= H)
        if kind == "out":
            return rebate if breached else intrinsic
        return intrinsic if breached else rebate
    breached = (S <= H) if direction == "down" else (S >= H)
    if breached:
        if kind == "out":
            return float(rebate) if rebate_at_hit else float(rebate * np.exp(-r * T))
        from .black import black
        F = S * np.exp(b * T)
        return float(black(F, X, T, sigma, np.exp(-r * T), cp))
    phi = 1 if cp == 1 else -1
    eta = 1 if direction == "down" else -1
    A, B, C, D, nt, hit_pv, er = _terms(S, X, H, T, r, b, sigma, phi, eta)
    if kind == "in":
        E = rebate * er * nt
        if cp == 1 and direction == "down":
            v = C + E if X > H else A - B + D + E
        elif cp == 1 and direction == "up":
            v = A + E if X > H else B - C + D + E
        elif cp == -1 and direction == "down":
            v = B - C + D + E if X > H else A + E
        else:
            v = A - B + D + E if X > H else C + E
    else:
        F_ = rebate * hit_pv if rebate_at_hit else rebate * er * (1 - nt)
        if cp == 1 and direction == "down":
            v = A - C + F_ if X > H else B - D + F_
        elif cp == 1 and direction == "up":
            v = F_ if X > H else A - B + C - D + F_
        elif cp == -1 and direction == "down":
            v = A - B + C - D + F_ if X > H else F_
        else:
            v = B - D + F_ if X > H else A - C + F_
    return float(max(v, 0.0))


def no_touch_prob(S: float, H: float, T: float, r: float, q: float, sigma: float, direction: str) -> float:
    """Риск-нейтральная (в мере валюты выплаты) вероятность не коснуться барьера до T."""
    if (direction == "down" and S <= H) or (direction == "up" and S >= H):
        return 0.0
    if T <= 0:
        return 1.0
    eta = 1 if direction == "down" else -1
    *_, nt, _, _ = _terms(S, S, H, T, r, r - q, sigma, 1, eta)
    return float(np.clip(nt, 0.0, 1.0))


def touch_price(S: float, H: float, T: float, r: float, q: float, sigma: float, direction: str, kind: str,
                payout: float = 1.0, at_hit: bool = False) -> float:
    """One-touch (kind='in') / no-touch (kind='out'): выплата ``payout`` в валюте выплаты."""
    breached = (S <= H) if direction == "down" else (S >= H)
    if breached:
        return payout if kind == "in" else 0.0
    if T <= 0:
        return 0.0 if kind == "in" else payout
    eta = 1 if direction == "down" else -1
    *_, nt, hit_pv, er = _terms(S, S, H, T, r, r - q, sigma, 1, eta)
    if kind == "out":
        return float(payout * er * nt)
    if at_hit:
        return float(payout * hit_pv)
    return float(payout * er * (1 - nt))


# ---------------------------------------------------------------------------
# Двойной барьер
# ---------------------------------------------------------------------------

def _wterm(logw: float, diff: float) -> float:
    """exp(logw)·diff без переполнения: при больших μ (низкая вола и высокий
    дифференциал ставок, типично для рубля) степени (U/L)^(nμ) выходят за double."""
    if diff == 0.0:
        return 0.0
    return float(np.sign(diff) * np.exp(logw + np.log(abs(diff))))


def double_barrier_ko(S: float, X: float, L: float, U: float, T: float, r: float, q: float, sigma: float, cp: int,
                      n_terms: int = 10) -> float:
    """Ikeda-Kunitomo: knock-out при касании L или U (плоские границы); ряд в логарифмах."""
    if S <= L or S >= U:
        return 0.0
    b = r - q
    sT = sigma * np.sqrt(T)
    mu = 2 * b / sigma ** 2 + 1
    eb = np.exp((b - r) * T)
    er = np.exp(-r * T)
    lS, lX, lL, lU = np.log(S), np.log(X), np.log(L), np.log(U)
    lE = lU if cp == 1 else lL           # граница, отсекающая выплату
    c = (b + 0.5 * sigma ** 2) * T
    s1 = s2 = 0.0
    for n in range(-n_terms, n_terms + 1):
        a = lS + 2 * n * (lU - lL)                    # ln(S·U^2n / L^2n)
        g = (2 * n + 2) * lL - lS - 2 * n * lU        # ln(L^(2n+2) / (S·U^2n))
        lr1 = n * (lU - lL)                           # ln(U^n / L^n)
        lr3 = (n + 1) * lL - n * lU - lS              # ln(L^(n+1) / (U^n·S))
        if cp == 1:
            d1, d2 = (a - lX + c) / sT, (a - lE + c) / sT
            d3, d4 = (g - lX + c) / sT, (g - lE + c) / sT
        else:
            d1, d2 = (a - lE + c) / sT, (a - lX + c) / sT
            d3, d4 = (g - lE + c) / sT, (g - lX + c) / sT
        s1 += _wterm(mu * lr1, N(d1) - N(d2)) - _wterm(mu * lr3, N(d3) - N(d4))
        s2 += _wterm((mu - 2) * lr1, N(d1 - sT) - N(d2 - sT)) - _wterm((mu - 2) * lr3, N(d3 - sT) - N(d4 - sT))
    if cp == 1:
        v = S * eb * s1 - X * er * s2
    else:
        v = X * er * s2 - S * eb * s1
    return float(max(v, 0.0))


def double_no_touch(S: float, L: float, U: float, T: float, r: float, q: float, sigma: float, payout: float = 1.0,
                    n_terms: int = 60) -> float:
    """Double-no-touch (Hui, 1996): ``payout`` в дату экспирации, если ни один барьер не задет."""
    if S <= L or S >= U:
        return 0.0
    b = r - q
    Z = np.log(U / L)
    alpha = -0.5 * (2 * b / sigma ** 2 - 1)
    beta = -0.25 * (2 * b / sigma ** 2 - 1) ** 2 - 2 * r / sigma ** 2
    tot = 0.0
    for i in range(1, n_terms + 1):
        k = i * np.pi / Z
        term = (2 * np.pi * i * payout / Z ** 2) * (((S / L) ** alpha - (-1) ** i * (S / U) ** alpha) / (alpha ** 2 + k ** 2)) \
            * np.sin(k * np.log(S / L)) * np.exp(-0.5 * (k ** 2 - beta) * sigma ** 2 * T)
        tot += term
    return float(max(tot, 0.0))


def double_no_touch_prob(S: float, L: float, U: float, T: float, r: float, q: float, sigma: float) -> float:
    """Вероятность не коснуться ни одного барьера (в мере валюты выплаты)."""
    return double_no_touch(S, L, U, T, r, q, sigma, 1.0) * np.exp(r * T)
