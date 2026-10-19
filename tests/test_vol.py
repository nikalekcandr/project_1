import numpy as np
import pytest

from prism.marketdata.context import Shock
from prism.models.analytic.black import bachelier, black, lognormal_to_normal, normal_to_lognormal
from prism.vol.ir import strip_caplets


@pytest.mark.parametrize("pair", ["USDRUB", "CNYRUB"])
def test_fx_surface_arbitrage_free_and_reprices_pillars(ctx, pair):
    s = ctx.fx_vol(pair)
    assert all(c["ok"] for c in s.check_arbitrage())
    for sl in s.slices[:-1]:
        for p in sl.pillars:
            assert float(s.vol(p.strike, sl.T)) == pytest.approx(p.vol, abs=7.5e-4)   # SVI с ограничениями no-arb: ≤0.075 п.п.


def test_sticky_strike_vs_sticky_delta(ctx):
    base = ctx.fx_vol("USDRUB")
    K, T = 90.0, 0.5
    bumped = ctx.with_shocks([Shock("fx", "USDRUB", 0.05, "relative")])
    v_delta = float(bumped.fx_vol("USDRUB").vol(K, T))
    v_strike = float(bumped.with_sticky("strike").fx_vol("USDRUB").vol(K, T))
    assert v_strike == pytest.approx(float(base.vol(K, T)), abs=1e-12)
    assert abs(v_delta - v_strike) > 1e-4


def test_normal_lognormal_roundtrip():
    F, K, T = 0.15, 0.17, 2.0
    ln = normal_to_lognormal(F, K, T, 0.02)
    assert lognormal_to_normal(F, K, T, ln) == pytest.approx(0.02, abs=1e-10)


def test_caplet_stripping_roundtrip():
    T = [(0.25 * i, 0.25) for i in range(1, 12)]
    F = [0.15 - 0.002 * i for i in range(11)]
    D = [np.exp(-0.15 * (t + 0.25)) for t, _ in T]
    true = np.array([0.02 + 0.001 * i for i in range(11)])
    mats = [1.0, 2.0, 3.0]
    flats = []
    from scipy.optimize import brentq
    for m in mats:
        idx = [i for i, (t, _) in enumerate(T) if t < m]
        price = sum(float(bachelier(F[i], 0.15, T[i][0], true[i], D[i] * 0.25, 1)) for i in idx)
        flats.append(brentq(lambda v: sum(float(bachelier(F[i], 0.15, T[i][0], v, D[i] * 0.25, 1)) for i in idx) - price, 1e-4, 0.2))
    st = strip_caplets(mats, flats, T, F, D, 0.15)
    for m, fv in zip(mats, flats):
        idx = [i for i, (t, _) in enumerate(T) if t < m]
        a = sum(float(bachelier(F[i], 0.15, T[i][0], st[i], D[i] * 0.25, 1)) for i in idx)
        b = sum(float(bachelier(F[i], 0.15, T[i][0], fv, D[i] * 0.25, 1)) for i in idx)
        assert a == pytest.approx(b, rel=1e-8)


def test_local_vol_reprices_vanilla_with_pde(ctx):
    from prism.models.pde.fd1d import solve_pde
    fx = ctx.fx("USDRUB")
    s = ctx.fx_vol("USDRUB")
    T = 0.5
    lv = ctx.local_vol("USDRUB", T)
    off = (fx.spot_date - fx.ref_date).days / 365
    fwd = lambda t: float(fx.forward_t(t + off)[0])
    disc = ctx.discount_curve("RUB")
    F = fwd(T)
    for K in (0.95 * F, F, 1.08 * F):
        pde = solve_pde(lambda S, K=K: np.maximum(S - K, 0), fx.spot_today(), T, fwd=fwd, rate=lambda t: float(disc.inst_fwd(t)),
                        vol=lambda t, x: lv(t, x - np.log(fwd(t))), n_x=401, n_t=300)["price"]
        ref = float(black(F, K, T, s.vol(K, T), float(disc.df(T)), 1))
        assert pde == pytest.approx(ref, rel=0.03)
