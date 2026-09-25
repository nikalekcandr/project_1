import numpy as np
import pandas as pd
import pytest

from mmsim.data.market import MarketData
from mmsim.engine import CalibrationConfig, ExecutionConfig, run_backtest
from mmsim.execution import CandleFill, TradesFill, build_grid
from mmsim.instruments import Instrument
from mmsim.sessions import resolve_sessions
from mmsim.strategies import AvellanedaStoikov, FixedSpread, GLFT, GLFTExact

CAL = CalibrationConfig(window_days=1, min_bars=50)


@pytest.mark.parametrize("fill_model", ["candle", "trades", "intensity"])
@pytest.mark.parametrize("strategy", [
    AvellanedaStoikov(gamma=0.01),
    AvellanedaStoikov(gamma=0.05, horizon="rolling", horizon_seconds=600),
    AvellanedaStoikov(gamma=0.05, horizon="infinite"),
    GLFT(gamma=0.05),
    GLFTExact(gamma=0.05),
    FixedSpread(8, skew_ticks_per_unit=1),
], ids=lambda s: getattr(s, "name", s))
def test_invariants(synth, strategy, fill_model):
    ex = ExecutionConfig(fill_model=fill_model, max_inventory=5, requote_seconds=30)
    res = run_backtest(synth, strategy, ex, CAL)
    st, f = res.steps, res.fills
    inst = synth.instrument
    # лимит позиции
    assert st["inventory"].abs().max() <= ex.max_inventory
    # позиция закрыта к концу каждой сессии
    last = st.groupby("session_id").tail(1)
    assert (last["inventory"] == 0).all()
    # деньги сходятся с журналом сделок
    cash = -(f["side"] * f["price"] * f["lots"]).sum() * inst.multiplier - f["fee"].sum()
    assert st["cash"].iloc[-1] == pytest.approx(cash)
    assert st["equity"].iloc[-1] == pytest.approx(cash)
    # котировки на сетке цены, bid < ask, не пересекают рынок
    q = st[st["quoting"]]
    both = q.dropna(subset=["bid", "ask"])
    assert (both["bid"] < both["ask"]).all()
    assert (q["bid"].dropna() < q.loc[q["bid"].notna(), "mid"]).all()
    assert (q["ask"].dropna() > q.loc[q["ask"].notna(), "mid"]).all()
    ticks = q["bid"].dropna() / inst.tick_size
    assert np.allclose(ticks, np.round(ticks), atol=1e-6)
    # первая сессия — разогрев калибровки, в ней не торгуем
    first = st["session_id"] == st["session_id"].iloc[0]
    assert not st.loc[first, "quoting"].any()
    m = res.metrics
    assert m["pnl_total"] == pytest.approx(m["pnl_spread"] + m["pnl_inventory"] + m["pnl_liquidation"] - m["fees"])
    assert m["days"] == len(synth.days) - 1


def test_no_lookahead(synth):
    """Изменение будущих баров не меняет котировки и исполнения в прошлом."""
    strat = AvellanedaStoikov(gamma=0.01)
    base = run_backtest(synth, strat, ExecutionConfig(), CAL)
    cut = synth.candles.index[int(len(synth.candles) * 0.7)]
    c = synth.candles.copy()
    future = c.index > cut
    c.loc[future, ["open", "high", "low", "close"]] *= 1.05
    alt = run_backtest(MarketData(synth.instrument, c, None, 60, "alt"), strat, ExecutionConfig(), CAL)
    past = base.steps.index <= cut
    cols = ["bid", "ask", "inventory", "cash"]
    pd.testing.assert_frame_equal(base.steps.loc[past, cols], alt.steps.loc[past, cols])


def test_inventory_skew_reduces_inventory(synth):
    ex = ExecutionConfig(max_inventory=20)
    skew = run_backtest(synth, AvellanedaStoikov(gamma=0.02), ex, CAL).metrics
    sym = run_backtest(synth, AvellanedaStoikov(gamma=0.02, inventory_skew=False), ex, CAL).metrics
    assert skew["inventory_mean_abs"] < sym["inventory_mean_abs"]


def _bars(rows, start="2025-09-01 10:00"):
    idx = pd.date_range(start, periods=len(rows), freq="60s")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)
    df["value"] = df["close"] * df["volume"]
    return df


def test_candle_fill_rules():
    inst = Instrument("TEST", lot_size=1, tick_size=0.01)
    bars = _bars([
        [100, 100.0, 100.0, 100.0, 1000],
        [100, 100.2, 99.9, 100.0, 1000],   # bid 99.95 проторгован насквозь, ask 100.2 — касание
        [100, 100.3, 99.95, 100.0, 1000],  # bid 99.95 — касание, ask 100.2 — насквозь
        [100, 100.05, 99.97, 100.0, 5],    # ничего; малый объём
    ])
    md = MarketData(inst, bars, None, 60)
    grid = build_grid(md, resolve_sessions(["main"]))
    fm = CandleFill(touch_fill_prob=0.0, max_participation=1.0)
    fm.prepare(grid, md)
    rng = np.random.default_rng(0)
    fb, fa = fm.match(1, 99.95, 100.2, 3, 3, None, rng)
    assert (fb.lots, fa.lots) == (3, 0)
    fb, fa = fm.match(2, 99.95, 100.2, 3, 3, None, rng)
    assert (fb.lots, fa.lots) == (0, 3)
    fm.touch_fill_prob = 1.0
    fb, fa = fm.match(1, 99.95, 100.2, 3, 3, None, rng)
    assert (fb.lots, fa.lots) == (3, 3)
    fm.max_participation = 0.5
    fb, _ = fm.match(3, 99.98, None, 5, 0, None, rng)
    assert fb.lots == 2  # 0.5 × 5 штук = 2 лота


def test_trades_fill_uses_aggressor_side():
    inst = Instrument("TEST", lot_size=1, tick_size=0.01)
    t0 = pd.Timestamp("2025-09-01 10:00:00")
    times = [t0 + pd.Timedelta(seconds=s) for s in (1, 12, 13, 14, 15)]
    trades = pd.DataFrame({
        "price": [100.00, 100.10, 99.90, 99.95, 100.02],
        "qty": [1, 4, 2, 5, 3],
        "side": [1, 1, 1, -1, 1],  # покупка по 99.90 не исполняет наш bid — инициатор покупатель
    }, index=pd.DatetimeIndex(times))
    candles = _bars([[100, 100, 100, 100, 1]])
    md = MarketData(inst, candles, trades, 60)
    grid = build_grid(md, resolve_sessions(["main"]), step_seconds=10, use_trades=True)
    fm = TradesFill(touch_fill_prob=0.0)
    fm.prepare(grid, md)
    fb, fa = fm.match(1, 99.96, 100.05, 10, 10, None, np.random.default_rng(0))
    assert fb.lots == 5 and fb.time == times[3]
    assert fa.lots == 4 and fa.time == times[1]


def test_fees_and_rebates(synth):
    base = run_backtest(synth, FixedSpread(6), ExecutionConfig(maker_fee_bps=0.0, taker_fee_bps=0.0), CAL).metrics
    rebate = run_backtest(synth, FixedSpread(6), ExecutionConfig(maker_fee_bps=-0.5, taker_fee_bps=0.0), CAL).metrics
    assert base["fees"] == 0
    assert rebate["fees"] < 0
    assert rebate["pnl_total"] == pytest.approx(base["pnl_total"] - rebate["fees"])
