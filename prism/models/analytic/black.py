"""Black-76 / Garman-Kohlhagen / Башелье: цены, греки, implied vol.

Всё в форвардных терминах: F — форвард на дату поставки, df — дисконт-фактор
валюты выплаты до даты платежа. Для FX: F = S·DFf/DFd (Garman-Kohlhagen).
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import brentq
from scipy.special import ndtr, ndtri

SQ2PI = np.sqrt(2.0 * np.pi)


def npdf(x):
    return np.exp(-0.5 * np.asarray(x) ** 2) / SQ2PI


def ncdf(x):
    return ndtr(x)


def _d12(F, K, T, sigma):
    sT = sigma * np.sqrt(T)
    d1 = (np.log(F / K) + 0.5 * sT * sT) / sT
    return d1, d1 - sT


def black(F, K, T, sigma, df=1.0, cp=1):
    """Цена европейского опциона (cp=+1 колл, −1 пут)."""
    F, K, T, sigma, cp = map(np.asarray, (F, K, T, sigma, cp))
    intrinsic = np.maximum(cp * (F - K), 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        d1, d2 = _d12(F, K, np.maximum(T, 1e-16), np.maximum(sigma, 1e-16))
        v = cp * (F * ncdf(cp * d1) - K * ncdf(cp * d2))
    v = np.where((T <= 0) | (sigma <= 0), intrinsic, v)
    return df * v


def black_digital(F, K, T, sigma, df=1.0, cp=1):
    """Cash-or-nothing: платит 1, если cp·(F_T − K) > 0 (без поправки на улыбку)."""
    F, K, T, sigma = map(np.asarray, (F, K, T, sigma))
    with np.errstate(divide="ignore", invalid="ignore"):
        _, d2 = _d12(F, K, np.maximum(T, 1e-16), np.maximum(sigma, 1e-16))
        v = ncdf(cp * d2)
    v = np.where((T <= 0) | (sigma <= 0), (cp * (F - K) > 0).astype(float), v)
    return df * v


def black_asset_digital(F, K, T, sigma, df=1.0, cp=1):
    F, K, T, sigma = map(np.asarray, (F, K, T, sigma))
    d1, _ = _d12(F, K, np.maximum(T, 1e-16), np.maximum(sigma, 1e-16))
    return df * F * ncdf(cp * d1)


def black_greeks(F, K, T, sigma, df=1.0, cp=1):
    """Греки по форварду: dV/dF, d²V/dF², dV/dσ, vanna (d²V/dFdσ), volga (d²V/dσ²)."""
    F, K, T, sigma = (np.asarray(x, dtype=float) for x in (F, K, T, sigma))
    sqT = np.sqrt(T)
    d1, d2 = _d12(F, K, T, sigma)
    pdf = npdf(d1)
    delta = df * cp * ncdf(cp * d1)
    gamma = df * pdf / (F * sigma * sqT)
    vega = df * F * pdf * sqT
    vanna = -df * pdf * d2 / sigma
    volga = vega * d1 * d2 / sigma
    return {"delta_fwd": delta, "gamma_fwd": gamma, "vega": vega, "vanna": vanna, "volga": volga, "d1": d1, "d2": d2}


def black_iv(price, F, K, T, df=1.0, cp=1, lo=1e-6, hi=6.0):
    """Implied vol Блэка (Brent). Возвращает nan вне арбитражных границ."""
    p = price / df
    intrinsic = max(cp * (F - K), 0.0)
    upper = F if cp == 1 else K
    if p <= intrinsic + 1e-14 or p >= upper:
        return np.nan
    f = lambda s: float(black(F, K, T, s, 1.0, cp)) - p
    try:
        return brentq(f, lo, hi, xtol=1e-14, maxiter=200)
    except ValueError:
        return np.nan


# --------------------------------------------------------------- Башелье
def bachelier(F, K, T, sigma_n, df=1.0, cp=1):
    F, K, T, s = map(np.asarray, (F, K, T, sigma_n))
    sT = np.maximum(s * np.sqrt(np.maximum(T, 0.0)), 1e-16)
    d = cp * (F - K) / sT
    v = cp * (F - K) * ncdf(d) + sT * npdf(d)
    v = np.where(s * np.sqrt(np.maximum(T, 0.0)) <= 1e-15, np.maximum(cp * (F - K), 0.0), v)
    return df * v


def bachelier_digital(F, K, T, sigma_n, df=1.0, cp=1):
    sT = np.maximum(sigma_n * np.sqrt(np.maximum(T, 0.0)), 1e-16)
    return df * ncdf(cp * (np.asarray(F) - K) / sT)


def bachelier_greeks(F, K, T, sigma_n, df=1.0, cp=1):
    sT = sigma_n * np.sqrt(T)
    d = (F - K) / sT
    return {"delta_fwd": df * cp * ncdf(cp * d), "gamma_fwd": df * npdf(d) / sT, "vega": df * np.sqrt(T) * npdf(d)}


def bachelier_iv(price, F, K, T, df=1.0, cp=1):
    p = price / df
    intrinsic = max(cp * (F - K), 0.0)
    if p <= intrinsic + 1e-16:
        return np.nan
    f = lambda s: float(bachelier(F, K, T, s, 1.0, cp)) - p
    try:
        return brentq(f, 1e-9, 5.0, xtol=1e-15, maxiter=200)
    except ValueError:
        return np.nan


def normal_to_lognormal(F, K, T, sigma_n, shift=0.0):
    """Конвертация нормальной волатильности в (сдвинутую) логнормальную через равенство цен."""
    cp = 1 if K >= F else -1
    p = float(bachelier(F, K, T, sigma_n, 1.0, cp))
    return black_iv(p, F + shift, K + shift, T, 1.0, cp)


def lognormal_to_normal(F, K, T, sigma_ln, shift=0.0):
    cp = 1 if K >= F else -1
    p = float(black(F + shift, K + shift, T, sigma_ln, 1.0, cp))
    return bachelier_iv(p, F, K, T, 1.0, cp)


# --------------------------------------------------------------- FX дельты
def strike_from_delta(delta, F, T, sigma, cp=1, delta_type="forward", premium_adjusted=False, df_f=1.0):
    """Страйк по дельте. ``delta`` — со знаком (пут отрицательный) либо модуль.

    spot-дельта = DFf · форвард-дельта. Премиально скорректированная дельта
    (premium in base currency): Δ_pa = cp·(K/F)·N(cp·d2) — решается численно,
    берётся ветвь справа от максимума для колла.
    """
    d = abs(delta)
    if delta_type == "spot":
        d = d / df_f
    sT = sigma * np.sqrt(T)
    if not premium_adjusted:
        if cp == 1:
            return F * np.exp(-ndtri(d) * sT + 0.5 * sT * sT)
        return F * np.exp(ndtri(d) * sT + 0.5 * sT * sT)

    def pa(K):
        _, d2 = _d12(F, K, T, sigma)
        return (K / F) * ncdf(cp * d2)

    if cp == 1:
        # максимум Δ_pa колла — при K* где d/dK=0; ищем ветвь K > K*
        Ks = F * np.exp(np.linspace(-4, 6, 4001) * sT)
        vals = (Ks / F) * ncdf((np.log(F / Ks) - 0.5 * sT * sT) / sT)
        imax = int(np.argmax(vals))
        lo, hi = Ks[imax], Ks[-1]
        if pa(lo) < d:
            return float(lo)
        return brentq(lambda K: pa(K) - d, lo, hi, xtol=1e-12)
    lo, hi = F * np.exp(-8 * sT), F * np.exp(4 * sT)
    return brentq(lambda K: pa(K) - d, lo, hi, xtol=1e-12)


def atm_strike(F, T, sigma, atm_type="dns", premium_adjusted=False):
    if atm_type == "atmf":
        return F
    s2 = sigma * sigma * T
    return F * np.exp(-0.5 * s2) if premium_adjusted else F * np.exp(0.5 * s2)
