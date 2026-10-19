"""Структуры из examples/trades собраны только конфигурацией (без нового кода движка) — приёмка фазы 4."""
from pathlib import Path

import pytest

from prism.instruments.schema import load_trade
from prism.pricing.engine import price_trade

EXAMPLES = sorted((Path(__file__).resolve().parents[1] / "examples" / "trades").glob("*.yaml"))


@pytest.mark.parametrize("path", EXAMPLES, ids=[p.stem for p in EXAMPLES])
def test_example_trade_prices(ctx, path):
    tr = load_trade(str(path))
    r = price_trade(tr, ctx, mc_overrides={"paths": 4000})
    assert r.value == r.value and r.inputs
    assert not any("WEEKENDS" in w for w in r.warnings)


def test_termsheet_example_keeps_references():
    tr = load_trade(str(EXAMPLES[0]))
    assert len(tr.termsheet_refs) >= 6
    assert tr.linked_trades and tr.linked_trades[0].relation == "condition_precedent"
    assert tr.identification.uti


def test_quanto_and_composite_are_different_prices(ctx):
    q = price_trade(load_trade(str(EXAMPLES[1])), ctx).value
    c = price_trade(load_trade(str(EXAMPLES[2])), ctx, mc_overrides={"paths": 8000}).value
    assert abs(q - c) / abs(q) > 0.03


def test_lookback_floating_strike_dominates_atm_call(ctx):
    from prism.instruments.schema import load_trade as lt
    d = lt(str(EXAMPLES[3])).model_dump(mode="json")
    lb = price_trade(lt(d), ctx, mc_overrides={"paths": 8000}).value
    spot = ctx.fx("CNYRUB").spot_today()
    d["legs"][0]["components"] = [{"kind": "call", "strike": spot}]
    van = price_trade(lt(d), ctx, mc_overrides={"paths": 8000}).value
    assert lb > van > 0


def test_mtm_ccs_analytic_matches_mc(ctx):
    tr = load_trade(str(next(p for p in EXAMPLES if "mtm_ccs" in p.name)))
    a = price_trade(tr, ctx, engine="analytic").value
    m = price_trade(tr, ctx, engine="mc", mc_overrides={"paths": 20000})
    assert abs(m.value - a) <= 4 * m.mc["stderr"] + 1e-9 * abs(a)


def test_notional_reset_requires_pair():
    d = load_trade(str(next(p for p in EXAMPLES if "mtm_ccs" in p.name))).model_dump(mode="json")
    d["legs"][1]["reset_pair"] = None
    with pytest.raises(Exception, match="reset_pair"):
        load_trade(d)
