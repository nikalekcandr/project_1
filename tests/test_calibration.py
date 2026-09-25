import numpy as np
import pandas as pd
import pytest

from mmsim.models.calibration import calibrate, estimate_sigma, fit_intensity, intensity_table


def test_sigma_on_brownian_bars():
    rng = np.random.default_rng(0)
    sigma = 0.03
    n = 5000
    idx = pd.date_range("2025-09-01 10:00", periods=n, freq="60s")
    close = 300 + np.cumsum(sigma * np.sqrt(60) * rng.standard_normal(n))
    bars = pd.DataFrame({"open": close, "high": close, "low": close, "close": close}, index=idx)
    assert estimate_sigma(bars, 60, np.zeros(n, dtype=int)) == pytest.approx(sigma, rel=0.05)


def test_intensity_recovers_poisson_depth_process():
    """Бары, где до глубины δ доходят пуассоновские события с интенсивностью A·exp(−kδ)."""
    rng = np.random.default_rng(5)
    A_true, k_true, dt, n = 0.5, 30.0, 10.0, 40_000
    mid = 100.0

    def side_extreme():
        counts = rng.poisson(A_true * dt, n)
        ext = np.zeros(n)
        has = counts > 0
        # максимум из m экспонент: F(x) = (1 − e^{−kx})^m → обратное преобразование
        u = rng.random(has.sum())
        ext[has] = -np.log1p(-u ** (1.0 / counts[has])) / k_true
        return ext

    idx = pd.date_range("2025-09-01 10:00", periods=n, freq="10s")
    bars = pd.DataFrame({"open": mid, "high": mid + side_extreme(), "low": mid - side_extreme(), "close": mid}, index=idx)
    table = intensity_table(bars, dt, 0.001, np.zeros(n, dtype=int))
    A, k, r2 = fit_intensity(table)
    assert k == pytest.approx(k_true, rel=0.05)
    assert A == pytest.approx(A_true, rel=0.1)
    assert r2 > 0.99


def test_calibrate_on_synthetic(synth):
    p = calibrate(synth.candles, 60, synth.instrument.tick_size)
    daily = p.sigma_over(31_200) / synth.candles["close"].mean()
    assert 0.01 < daily < 0.03  # годовая волатильность 28% → ~1.8% в день
    assert p.A > 0 and p.k > 0
