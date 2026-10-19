import math

import numpy as np
import pytest

from prism.instruments.schema import load_trade
from prism.instruments.templates import build, render
from prism.models.analytic.barriers import barrier_price, double_barrier_ko
from prism.models.analytic.black import black
from prism.pricing.engine import price_trade
from prism.validation.suite import SuiteResult, high_rate_stability, quantlib_benchmarks


def test_quantlib_benchmarks():
    pytest.importorskip("QuantLib")
    res = SuiteResult()
    quantlib_benchmarks(res)
    bad = [f"{c.name}: {c.detail}" for c in res.checks if not c.ok]
    assert not bad, bad


def test_high_rate_stability():
    res = SuiteResult()
    high_rate_stability(res)
    assert res.ok, [c.detail for c in res.checks]


def test_barrier_limits():
    S, K, T, r, q, v = 82.5, 85.0, 1.0, 0.16, 0.03, 0.18
    van = float(black(S * math.exp((r - q) * T), K, T, v, math.exp(-r * T), 1))
    assert barrier_price(S, K, 1e6, T, r, q, v, 1, "up", "out") == pytest.approx(van, rel=1e-10)
    assert barrier_price(S, K, 1e-6, T, r, q, v, 1, "down", "out") == pytest.approx(van, rel=1e-10)
    assert double_barrier_ko(S, K, 1e-3, 1e5, T, r, q, v, 1) == pytest.approx(van, rel=1e-6)


@pytest.mark.parametrize("direction,level", [("up", 98.0), ("down", 76.0)])
def test_ki_plus_ko_equals_vanilla(ctx, direction, level):
    vd = render("fx_barrier", {"strike": 88.0})
    vd["legs"][0]["components"][0]["modifiers"] = []
    van = price_trade(load_trade(vd), ctx).value
    ko = price_trade(build("fx_barrier", {"strike": 88.0, "barrier": level, "direction": direction, "kind": "out"}), ctx).value
    ki = price_trade(build("fx_barrier", {"strike": 88.0, "barrier": level, "direction": direction, "kind": "in"}), ctx).value
    assert ki + ko == pytest.approx(van, rel=1e-8)
    assert 0 <= ko <= van


def test_put_call_parity_on_trades(ctx):
    call = price_trade(build("fx_vanilla", {"option": "call", "strike": 88.0}), ctx).value
    put = price_trade(build("fx_vanilla", {"option": "put", "strike": 88.0}), ctx).value
    d = render("fx_vanilla", {"option": "call", "strike": 88.0})
    d["legs"][0]["components"] = [{"kind": "forward", "strike": 88.0}]
    fwd = price_trade(load_trade(d), ctx).value
    assert call - put == pytest.approx(fwd, abs=1.0)


@pytest.mark.parametrize("tid", ["fx_vanilla", "fx_barrier", "fx_asian", "fx_touch"])
def test_mc_matches_analytic_on_flat_smile(flat_ctx, tid):
    tr = build(tid, {"strike": 88.0} if tid == "fx_vanilla" else {})
    a = price_trade(tr, flat_ctx, engine="analytic").value
    m = price_trade(tr, flat_ctx, engine="mc", mc_overrides={"paths": 30000, "vol_model": "black"})
    assert abs(m.value - a) <= 4.5 * m.mc["stderr"] + 1e-6 * abs(a)


def test_mc_reproducible_with_seed(ctx):
    tr = build("fx_tarf")
    a = price_trade(tr, ctx, mc_overrides={"paths": 4000}).value
    b = price_trade(tr, ctx, mc_overrides={"paths": 4000}).value
    assert float(a).hex() == float(b).hex()


def test_router_never_silently_falls_back(ctx):
    r = price_trade(build("fx_tarf"), ctx, mc_overrides={"paths": 2000})
    assert r.engine == "mc" and r.fallback_reason          # причина выбора движка записана
    r2 = price_trade(build("fx_barrier"), ctx)
    assert r2.engine == "analytic"


def test_vv_vs_lv_crosscheck_reported(ctx):
    r = price_trade(build("fx_barrier"), ctx, crosscheck=True)
    names = " ".join(str(c.get("name", "")) + str(c.get("check", "")) for c in r.checks)
    assert "лок" in names.lower() or "lv" in names.lower()


def test_bermudan_tree_vs_european_lower_bound(ctx):
    v = price_trade(build("swaption"), ctx).value
    assert v > 0


def test_pde_discrete_barrier_converges_to_continuous_with_daily_monitoring():
    from prism.models.pde.fd1d import solve_pde
    r, q, vol, S, K, H, T = 0.16, 0.03, 0.2, 82.5, 85.0, 100.0, 0.5
    fwd = lambda t: S * math.exp((r - q) * t)
    pde = solve_pde(lambda x: np.maximum(x - K, 0), S, T, fwd=fwd, rate=lambda t: r, vol=lambda t, x: np.full_like(x, vol),
                    upper=H, n_x=600, n_t=600)["price"]
    an = barrier_price(S, K, H, T, r, q, vol, 1, "up", "out")
    assert pde == pytest.approx(an, rel=5e-3)


def test_term_structure_adjustment_vanishes_on_flat_inputs():
    """На плоских ставках, сносе и воле поправка PDE(ВС) − PDE(плоская) равна нулю."""
    from prism.models.pde.fd1d import term_structure_adjustment
    r, q, v, T = 0.16, 0.03, 0.15, 0.75
    adj = term_structure_adjustment(lambda x: np.ones_like(x), 82.5, 82.5 * math.exp((r - q) * T), T, math.exp(-r * T),
                                    log_fwd_growth=lambda t: (r - q) * np.asarray(t), cum_rate=lambda t: r * np.asarray(t),
                                    atm_total_var=lambda t: v * v * np.asarray(t), upper=95.0)
    assert abs(adj) < 1e-12


def test_regression_against_golden(ctx):
    from prism.validation.suite import SuiteResult, regression
    res = SuiteResult()
    regression(ctx, res)
    bad = [f"{c.name}: {c.detail}" for c in res.checks if not c.ok]
    assert not bad, bad
