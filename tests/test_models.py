import numpy as np
import pytest

from mmsim.models import avellaneda_stoikov as AS
from mmsim.models import glft


def test_reservation_price_skews_against_inventory():
    r_long = AS.reservation_price(100.0, 3, 0.1, 2.0, 0.5)
    r_flat = AS.reservation_price(100.0, 0, 0.1, 2.0, 0.5)
    r_short = AS.reservation_price(100.0, -3, 0.1, 2.0, 0.5)
    assert r_long < r_flat == 100.0 < r_short
    assert r_flat - r_long == pytest.approx(3 * 0.1 * 4 * 0.5)


def test_optimal_spread_formula():
    gamma, sigma, tau, k = 0.1, 2.0, 1.0, 1.5
    expected = gamma * sigma**2 * tau + 2 / gamma * np.log(1 + gamma / k)
    assert AS.optimal_spread(gamma, sigma, tau, k) == pytest.approx(expected)
    # при γ → 0 спред стремится к 2/k (риск-нейтральный маркет-мейкер)
    assert AS.optimal_spread(1e-8, sigma, tau, k) == pytest.approx(2 / k, rel=1e-4)


def test_quotes_are_symmetric_around_reservation():
    bid, ask, r, spread = AS.quotes(100.0, 2, 0.1, 2.0, 0.3, 1.5)
    assert (bid + ask) / 2 == pytest.approx(r)
    assert ask - bid == pytest.approx(spread)


def test_infinite_horizon_blocks_side_at_limit():
    # на границе запаса ln(·) → −∞: bid уходит «в бесконечность» (численно — очень далеко)
    bid, ask, _, _ = AS.infinite_horizon_quotes(100.0, 5, 0.1, 2.0, 1.5, q_max=5)
    assert (not np.isfinite(bid) or bid < 0) and np.isfinite(ask)
    bid0, ask0, r0, _ = AS.infinite_horizon_quotes(100.0, 0, 0.1, 2.0, 1.5, q_max=5)
    assert bid0 < 100.0 < ask0
    assert r0 == pytest.approx(100.0, abs=0.01)  # ln(1+x)+ln(1−x) < 0: r чуть ниже s


def test_glft_exact_converges_to_asymptotic():
    gamma, sigma, A, k = 0.05, 0.03, 0.06, 8.0
    solver = glft.GLFTSolver(gamma, sigma, A, k, q_max=20)
    for q in (-3, 0, 3):
        db, da = solver.depths(1e7, q)
        adb, ada = glft.asymptotic_depths(q, gamma, sigma, A, k)
        assert db == pytest.approx(float(adb), rel=0.02)
        assert da == pytest.approx(float(ada), rel=0.02)


def test_glft_exact_short_horizon_and_bounds():
    solver = glft.GLFTSolver(0.05, 0.03, 0.06, 8.0, q_max=4)
    db, da = solver.depths(0.0, 2)  # без штрафа в конце — чистая ликвидностная компонента
    assert db == pytest.approx(solver.c1) and da == pytest.approx(solver.c1)
    db, da = solver.depths(600.0, 4)
    assert db == np.inf and np.isfinite(da)
    db, da = solver.depths(600.0, 2)
    assert db > da  # длинная позиция: покупаем дальше от mid, продаём ближе


def test_glft_asymptotic_symmetry():
    db, da = glft.asymptotic_depths(0, 0.05, 0.03, 0.06, 8.0)
    assert db == pytest.approx(da)
    db2, da2 = glft.asymptotic_depths(2, 0.05, 0.03, 0.06, 8.0)
    assert db2 > db and da2 < da
