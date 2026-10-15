"""Азиатские опционы: аппроксимация моментов (Turnbull-Wakeman / Levy).

Произвольное расписание и веса фиксингов, форвард и волатильность на каждую
дату (сезонные товарные кривые, временная структура). Уже зафиксированная
часть среднего учитывается через сдвиг страйка.
"""
from __future__ import annotations

import numpy as np

from .black import black


def arithmetic_asian(fwds, times, weights, total_var, K: float, T_pay_df: float, cp: int = 1,
                     known_avg_part: float = 0.0, known_weight: float = 0.0) -> dict:
    """Средняя A = known_avg_part + Σ w_i X_i (w_i — веса будущих фиксингов).

    total_var(t) — общая дисперсия σ²t логарифма базиса до t (детерминированная
    структура; для товаров — вола соответствующего контракта).
    """
    F = np.asarray(fwds, float)
    t = np.asarray(times, float)
    w = np.asarray(weights, float)
    if len(F) == 0:
        A = known_avg_part
        return {"price": T_pay_df * max(cp * (A - K), 0.0), "M1": A, "sigma_eff": 0.0}
    v = np.array([total_var(x) for x in t])
    m1 = float(np.sum(w * F))
    vmin = np.minimum.outer(v, v)
    m2 = float(np.sum(np.outer(w * F, w * F) * np.exp(vmin)))
    Te = float(t.max())
    sig2T = max(np.log(m2 / (m1 * m1)), 1e-14)
    Keff = K - known_avg_part
    if Keff <= 0:
        # опцион гарантированно в деньгах (для колла): линейная выплата
        price = T_pay_df * cp * (m1 - Keff) if cp == 1 else 0.0
        return {"price": float(max(price, 0.0)), "M1": m1 + known_avg_part, "sigma_eff": float(np.sqrt(sig2T / Te)),
                "note": "фиксированная часть среднего уже выше страйка"}
    price = float(black(m1, Keff, Te, np.sqrt(sig2T / Te), T_pay_df, cp))
    return {"price": price, "M1": m1 + known_avg_part, "sigma_eff": float(np.sqrt(sig2T / Te))}


def geometric_asian(fwds, times, weights, total_var, K: float, df: float, cp: int = 1) -> float:
    """Геометрическое среднее — точная формула (логнормальное распределение)."""
    F = np.asarray(fwds, float)
    t = np.asarray(times, float)
    w = np.asarray(weights, float)
    w = w / w.sum()
    v = np.array([total_var(x) for x in t])
    vmin = np.minimum.outer(v, v)
    mean_log = float(np.sum(w * (np.log(F) - 0.5 * v)))
    var_log = float(np.sum(np.outer(w, w) * vmin))
    G = np.exp(mean_log + 0.5 * var_log)
    Te = float(t.max())
    return float(black(G, K, Te, np.sqrt(var_log / Te), df, cp))
