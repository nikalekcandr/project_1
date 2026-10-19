"""PDE-солвер 1D: Кранк-Николсон со стартом Раннахера.

x = ln S; ∂V/∂t + ½σ²(t,S)V_xx + (μ(t) − ½σ²)V_x − r(t)V = 0, где
μ(t) = d ln F(t)/dt (снос из форвардной кривой), r(t) — мгновенная ставка
дисконтирования. Локальная волатильность σ(t, S) = LV(t, ln(S/F(t))).

Барьеры: узел сетки совмещается с барьером; при непрерывном наблюдении —
условие Дирихле (ребейт) на каждом шаге внутри окна, при дискретном — в
даты наблюдения. Американское исполнение — проекция max(V, внутренняя).
Используется как независимая проверка аналитики и VV.
"""
from __future__ import annotations

from typing import Callable

import numpy as np
from scipy.linalg.lapack import dgtsv


def solve_pde(payoff: Callable[[np.ndarray], np.ndarray], S0: float, T: float, *,
              fwd: Callable[[float], float], rate: Callable[[float], float], vol: Callable[[float, np.ndarray], np.ndarray],
              lower: float | None = None, upper: float | None = None, rebate: float = 0.0,
              window: tuple[float, float] | None = None, monitor_times: list[float] | None = None,
              american: bool = False, n_x: int = 401, n_t: int = 300, width_sd: float = 6.0, sd_vol: float = 0.2,
              rannacher: int = 4) -> dict:
    """Цена в момент 0 (за единицу), плюс сетки для дельты/гаммы."""
    sd = sd_vol * np.sqrt(max(T, 1e-6))
    x0 = np.log(S0)
    xlo = x0 - width_sd * sd
    xhi = x0 + width_sd * sd
    cont = monitor_times is None
    if lower is not None:
        xlo = np.log(lower) if cont else min(xlo, np.log(lower) - 2 * sd)
    if upper is not None:
        xhi = np.log(upper) if cont else max(xhi, np.log(upper) + 2 * sd)
    x = np.linspace(xlo, xhi, n_x)
    if not cont and (lower is not None or upper is not None):
        # совместить узел сетки с барьером (дискретное наблюдение)
        anchor = np.log(upper if upper is not None else lower)
        dxx = x[1] - x[0]
        shift = anchor - (xlo + np.round((anchor - xlo) / dxx) * dxx)
        x = x + shift
    # совместить S0 с узлом не требуется (интерполяция), барьеры — на краях сетки при непрерывном наблюдении
    dx = x[1] - x[0]
    S = np.exp(x)
    V = payoff(S).astype(float)
    ts = np.linspace(0.0, T, n_t + 1)
    mon_steps = set()
    if monitor_times is not None:
        for mt in monitor_times:
            mon_steps.add(int(np.argmin(np.abs(ts - mt))))
    w0, w1 = window if window is not None else (0.0, T)

    def apply_barrier(Vv, t):
        if not (w0 - 1e-12 <= t <= w1 + 1e-12):
            return Vv
        if lower is not None:
            Vv = np.where(S <= lower * (1 + 1e-12), rebate, Vv)
        if upper is not None:
            Vv = np.where(S >= upper * (1 - 1e-12), rebate, Vv)
        return Vv

    intrinsic = payoff(S)
    if cont:
        V = apply_barrier(V, T)
    for n in range(n_t, 0, -1):
        t1, t0 = ts[n], ts[n - 1]
        dt = t1 - t0
        tm = 0.5 * (t0 + t1)
        sig = vol(tm, x)
        mu = (np.log(fwd(t1)) - np.log(fwd(t0))) / dt
        r = rate(tm)
        A = (0.5 * sig * sig / dx ** 2 - (mu - 0.5 * sig * sig) / (2 * dx))[1:-1]
        B = (-sig * sig / dx ** 2 - r)[1:-1]
        C = (0.5 * sig * sig / dx ** 2 + (mu - 0.5 * sig * sig) / (2 * dx))[1:-1]
        lo_dir = cont and lower is not None and w0 <= t0 + 1e-12
        hi_dir = cont and upper is not None and w0 <= t0 + 1e-12
        # исключение граничных узлов: Дирихле (ребейт) либо V_xx = 0
        A, B, C = A.copy(), B.copy(), C.copy()
        bl = br = 0.0
        if lo_dir:
            bl = A[0] * rebate
            A[0] = 0.0
        else:
            B[0] += 2 * A[0]
            C[0] -= A[0]
            A[0] = 0.0
        if hi_dir:
            br = C[-1] * rebate
            C[-1] = 0.0
        else:
            B[-1] += 2 * C[-1]
            A[-1] -= C[-1]
            C[-1] = 0.0
        theta = 1.0 if (n_t - n) < rannacher else 0.5
        Vi = V[1:-1]
        LV = B * Vi
        LV[1:] += A[1:] * Vi[:-1]
        LV[:-1] += C[:-1] * Vi[1:]
        LV[0] += bl
        LV[-1] += br
        rhs = Vi + (1 - theta) * dt * LV
        rhs[0] += theta * dt * bl
        rhs[-1] += theta * dt * br
        # трёхдиагональная система: LAPACK dgtsv напрямую (без накладных расходов обёртки на каждом шаге)
        *_, Vi, info = dgtsv(-theta * dt * A[1:], 1 - theta * dt * B, -theta * dt * C[:-1], rhs)
        if info != 0:  # pragma: no cover
            raise FloatingPointError(f"PDE: вырожденная трёхдиагональная система (info={info})")
        V = np.empty_like(V)
        V[1:-1] = Vi
        V[0] = rebate if lo_dir else 2 * Vi[0] - Vi[1]
        V[-1] = rebate if hi_dir else 2 * Vi[-1] - Vi[-2]
        if not cont and (n - 1) in mon_steps:
            V = apply_barrier(V, t0)
        if cont and window is not None:
            V = apply_barrier(V, t0)
        if american:
            V = np.maximum(V, intrinsic)
    price = float(np.interp(x0, x, V))
    i = int(np.searchsorted(x, x0))
    i = min(max(i, 1), len(x) - 2)
    dVdx = (V[i + 1] - V[i - 1]) / (2 * dx)
    d2 = (V[i + 1] - 2 * V[i] + V[i - 1]) / dx ** 2
    delta = dVdx / S0
    gamma = (d2 - dVdx) / S0 ** 2
    return {"price": price, "delta": float(delta), "gamma": float(gamma), "grid_S": S, "grid_V": V}


def term_structure_adjustment(payoff: Callable[[np.ndarray], np.ndarray], S0: float, F: float, T: float, df: float, *,
                              log_fwd_growth: Callable[[np.ndarray], np.ndarray], cum_rate: Callable[[np.ndarray], np.ndarray],
                              atm_total_var: Callable[[np.ndarray], np.ndarray], lower: float | None = None,
                              upper: float | None = None, rebate: float = 0.0, n_x: int = 241, n_t: int = 160) -> float:
    """Поправка закрытой формулы с плоскими r, q, σ на временную структуру.

    Формулы барьеров (Reiner-Rubinstein, Ikeda-Kunitomo, Hui) предполагают
    постоянные ставки и волатильность до экспирации. На рублёвом рынке кривая
    ступенчатая (решения ЦБ), снос r_d − r_f сосредоточен в начале срока, и
    вероятность касания барьера заметно отличается от плоской (до нескольких
    процентов цены). Поправка = PDE(временная структура) − PDE(плоские
    параметры) на одной сетке: ошибки дискретизации взаимно гасятся, концы
    сохранены — форвард F в T, дисконт df и полная дисперсия σ_ATM(T)²·T.
    """
    if T <= 1.0 / 365:
        return 0.0
    ts = np.linspace(0.0, T, 201)
    LT = float(np.log(F / S0))
    g = np.asarray(log_fwd_growth(ts), float)
    g = g - g[0]
    lnF = np.log(S0) + (LT * g / g[-1] if abs(g[-1]) > 1e-10 else LT * ts / T)
    R = np.asarray(cum_rate(ts), float)
    R = R - R[0]
    Rtot = -float(np.log(df))
    Rs = Rtot * R / R[-1] if abs(R[-1]) > 1e-12 else Rtot * ts / T
    tv = np.linspace(0.0, T, 41)
    W = np.concatenate([[0.0], np.asarray(atm_total_var(tv[1:]), float)])
    W = np.maximum.accumulate(W)
    sig_T = float(np.sqrt(max(W[-1], 1e-12) / T))
    tm, rate_seg = 0.5 * (ts[1:] + ts[:-1]), np.diff(Rs) / np.diff(ts)
    tvm, sig_seg = 0.5 * (tv[1:] + tv[:-1]), np.sqrt(np.maximum(np.diff(W) / np.diff(tv), 1e-8))

    def run(fwd, rate, sig):
        return solve_pde(payoff, S0, T, fwd=fwd, rate=rate, vol=lambda t, x: np.full_like(x, sig(t)), lower=lower, upper=upper,
                         rebate=rebate, n_x=n_x, n_t=n_t, sd_vol=sig_T)["price"]

    p_ts = run(lambda t: float(np.exp(np.interp(t, ts, lnF))), lambda t: float(np.interp(t, tm, rate_seg)),
               lambda t: float(np.interp(t, tvm, sig_seg)))
    p_flat = run(lambda t: S0 * float(np.exp(LT * t / T)), lambda t: Rtot / T, lambda t: sig_T)
    return p_ts - p_flat
