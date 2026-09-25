"""Калибровка параметров σ, A, k по свечам.

σ — стандартное отклонение приращений цены закрытия соседних баров внутри
одной сессии (переходы через ночь/клиринг исключаются), в руб./√с.

A, k — по «экскурсиям» цены: для бара i котировка выставляется от цены
закрытия предыдущего бара ref = close_{i−1}; расстояния up = high_i − ref и
down = ref − low_i показывают, на какую глубину δ цена «достала» за бар. Если
события «цена дошла до глубины δ» — пуассоновский поток с интенсивностью λ(δ),
то P(дошла за Δt) = 1 − exp(−λ(δ)Δt), откуда λ(δ) = −ln(1 − P̂(δ))/Δt.
Далее МНК по ln λ(δ) = ln A − kδ. Это тот же критерий исполнения, что и в
свечной модели исполнения симулятора, поэтому калибровка с ней согласована.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass
class ModelParams:
    sigma: float  # руб./√с
    A: float  # 1/с
    k: float  # 1/руб.
    n_obs: int = 0
    r2: float = float("nan")

    def sigma_over(self, seconds: float) -> float:
        return self.sigma * np.sqrt(seconds)

    def to_dict(self) -> dict:
        return asdict(self)

    def describe(self, price: float | None = None, session_seconds: float = 31_200) -> str:
        s = (
            f"σ = {self.sigma:.5g} руб./√с (за сессию {self.sigma_over(session_seconds):.3f} руб."
            + (f", {100 * self.sigma_over(session_seconds) / price:.2f}%" if price else "")
            + f"); A = {self.A:.4g} 1/с; k = {self.k:.4g} 1/руб. (1/k = {1 / self.k:.4f} руб.)"
        )
        if np.isfinite(self.r2):
            s += f"; R² = {self.r2:.3f}; наблюдений {self.n_obs}"
        return s


def _within_session_prev_close(bars: pd.DataFrame, session_id: np.ndarray | None) -> tuple[np.ndarray, np.ndarray]:
    close = bars["close"].to_numpy(float)
    prev = np.r_[np.nan, close[:-1]]
    valid = np.ones(len(bars), dtype=bool)
    valid[0] = False
    if session_id is not None:
        sid = np.asarray(session_id)
        valid &= np.r_[False, sid[1:] == sid[:-1]] & (sid >= 0)
    else:
        days = pd.DatetimeIndex(bars.index).normalize().to_numpy()
        valid &= np.r_[False, days[1:] == days[:-1]]
    return prev, valid


def estimate_sigma(bars: pd.DataFrame, bar_seconds: float, session_id=None) -> float:
    prev, valid = _within_session_prev_close(bars, session_id)
    d = bars["close"].to_numpy(float)[valid] - prev[valid]
    if len(d) < 2:
        return float("nan")
    return float(np.sqrt(np.mean(d**2) / bar_seconds))


def intensity_table(
    bars: pd.DataFrame, bar_seconds: float, tick: float, session_id=None, max_points: int = 40
) -> pd.DataFrame:
    """Эмпирическая λ(δ) по экскурсиям цены (обе стороны усреднены)."""
    prev, valid = _within_session_prev_close(bars, session_id)
    up = (bars["high"].to_numpy(float) - prev)[valid]
    down = (prev - bars["low"].to_numpy(float))[valid]
    if len(up) == 0:
        return pd.DataFrame(columns=["delta", "p_hit", "lambda", "n"])
    exc = np.concatenate([up, down])
    hi = np.quantile(exc, 0.995)
    step = max(tick, np.ceil(hi / tick / max_points) * tick)
    deltas = np.arange(1, int(hi / step) + 1) * step
    p = np.array([(exc >= d - 1e-9).mean() for d in deltas])
    with np.errstate(divide="ignore"):
        lam = -np.log1p(-np.clip(p, 0.0, 1.0 - 1e-12)) / bar_seconds
    return pd.DataFrame({"delta": deltas, "p_hit": p, "lambda": lam, "n": len(exc)})


def fit_intensity(table: pd.DataFrame, p_min: float = 0.01, p_max: float = 0.99) -> tuple[float, float, float]:
    """МНК ln λ = ln A − kδ по точкам с p_min ≤ P̂ ≤ p_max. Возвращает (A, k, R²)."""
    t = table[(table["p_hit"] >= p_min) & (table["p_hit"] <= p_max)]
    if len(t) < 3:
        raise ValueError("Недостаточно точек для оценки A и k: увеличьте окно калибровки")
    x, y = t["delta"].to_numpy(), np.log(t["lambda"].to_numpy())
    slope, intercept = np.polyfit(x, y, 1)
    pred = intercept + slope * x
    ss_res, ss_tot = float(((y - pred) ** 2).sum()), float(((y - y.mean()) ** 2).sum())
    k = -slope
    if not k > 0:
        raise ValueError(f"Оценка k = {k:.4g} ≤ 0: данные не согласуются с λ(δ) = A·exp(−kδ)")
    return float(np.exp(intercept)), float(k), 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")


def calibrate(bars: pd.DataFrame, bar_seconds: float, tick: float, session_id=None) -> ModelParams:
    sigma = estimate_sigma(bars, bar_seconds, session_id)
    table = intensity_table(bars, bar_seconds, tick, session_id)
    A, k, r2 = fit_intensity(table)
    return ModelParams(sigma=sigma, A=A, k=k, n_obs=int(table["n"].iloc[0]) if len(table) else 0, r2=r2)
