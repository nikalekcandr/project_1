"""Событийный движок бэктеста маркет-мейкера.

Шаг i (длина — бар или интервал перекотировки):
    1. в начале сессии — калибровка σ, A, k по данным строго до начала сессии;
    2. стратегия считает котировки по mid = цена закрытия предыдущего бара;
    3. округление к шагу цены, post-only (не пересекаем рынок), лимит позиции;
    4. модель исполнения определяет исполнения внутри бара;
    5. учёт денег, позиции и комиссий, переоценка по цене закрытия бара;
    6. в конце сессии — принудительное закрытие позиции по рынку (опционально).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from mmsim.data.market import MarketData
from mmsim.execution import Grid, build_grid, make_fill_model
from mmsim.models.calibration import ModelParams, calibrate
from mmsim.sessions import resolve_sessions
from mmsim.strategies import MarketState, Strategy


@dataclass
class ExecutionConfig:
    fill_model: str = "candle"  # candle | trades | intensity
    touch_fill_prob: float = 0.3  # вероятность исполнения при касании цены (очередь)
    max_participation: float = 0.2  # доля объёма бара, доступная нам (candle)
    requote_seconds: int = 10  # шаг перекотировки для модели trades
    maker_fee_bps: float = 1.0  # комиссия за пассивные сделки, б.п. (отрицательная — ребейт)
    taker_fee_bps: float = 3.0  # комиссия за агрессивные сделки, б.п.
    max_inventory: int = 10  # жёсткий лимит |позиции|, лоты
    post_only: bool = True  # не выставлять заявки, пересекающие рынок
    market_half_spread_ticks: float = 0.5  # полуспред рынка вокруг последней цены, тики
    min_spread_ticks: int = 1  # минимальная ширина нашей котировки, тики
    liquidation_slippage_ticks: float = 1.0  # проскальзывание при закрытии позиции, тики
    flatten_at_session_end: bool = True
    seed: int = 42


@dataclass
class CalibrationConfig:
    mode: str = "walk_forward"  # walk_forward | full_sample | fixed
    window_days: int = 5  # окно walk-forward, торговых дней
    min_bars: int = 100  # минимум баров для калибровки
    sigma_ewma_halflife: float = 0.0  # полупериод EWMA-оценки σ внутри дня, баров (0 — выкл)
    sigma: float | None = None  # фиксированные значения / переопределения
    A: float | None = None
    k: float | None = None


@dataclass
class BacktestResult:
    steps: pd.DataFrame
    fills: pd.DataFrame
    params: pd.DataFrame
    strategy: str
    instrument: object
    execution: ExecutionConfig
    calibration: CalibrationConfig
    meta: dict = field(default_factory=dict)
    _metrics: dict | None = None

    @property
    def metrics(self) -> dict:
        if self._metrics is None:
            from mmsim.metrics import compute_metrics

            self._metrics = compute_metrics(self)
        return self._metrics

    @property
    def daily(self) -> pd.DataFrame:
        from mmsim.metrics import daily_table

        return daily_table(self)


class Calibrator:
    """Параметры модели по сессиям (без заглядывания в будущее для walk_forward)."""

    def __init__(self, cfg: CalibrationConfig, grid: Grid, tick: float):
        self.cfg = cfg
        self.grid = grid
        self.tick = tick
        self._full: ModelParams | None = None
        self.days = pd.DatetimeIndex(grid.time).normalize()

    def _override(self, p: ModelParams) -> ModelParams:
        c = self.cfg
        return ModelParams(
            sigma=c.sigma if c.sigma is not None else p.sigma,
            A=c.A if c.A is not None else p.A,
            k=c.k if c.k is not None else p.k,
            n_obs=p.n_obs,
            r2=p.r2,
        )

    def _fit(self, mask: np.ndarray) -> ModelParams | None:
        if mask.sum() < self.cfg.min_bars:
            return None
        bars = self.grid.bars[mask]
        try:
            return calibrate(bars, self.grid.step_seconds, self.tick, bars["session_id"].to_numpy())
        except ValueError:
            return None

    def for_session(self, first_step: int) -> ModelParams | None:
        c = self.cfg
        if c.mode == "fixed":
            if None in (c.sigma, c.A, c.k):
                raise ValueError("Для mode='fixed' задайте sigma, A и k в [calibration]")
            return ModelParams(float(c.sigma), float(c.A), float(c.k))
        if c.mode == "full_sample":
            if self._full is None:
                self._full = self._fit(np.ones(len(self.grid), dtype=bool))
                if self._full is None:
                    raise ValueError("Недостаточно данных для калибровки")
            return self._override(self._full)
        if c.mode != "walk_forward":
            raise ValueError("calibration.mode: walk_forward | full_sample | fixed")
        day = self.days[first_step]
        prior_days = self.days[:first_step].unique()
        prior_days = prior_days[prior_days < day]
        window_start = prior_days[-c.window_days] if len(prior_days) >= c.window_days else (
            prior_days[0] if len(prior_days) else day
        )
        idx = np.arange(len(self.grid))
        mask = (idx < first_step) & (self.days >= window_start)
        p = self._fit(np.asarray(mask))
        return self._override(p) if p is not None else None


def run_backtest(
    data: MarketData,
    strategy: Strategy,
    execution: ExecutionConfig | None = None,
    calibration: CalibrationConfig | None = None,
    sessions: list[str] | None = None,
    custom_sessions: dict | None = None,
    trade_start=None,
    trade_end=None,
) -> BacktestResult:
    ex = execution or ExecutionConfig()
    cal = calibration or CalibrationConfig()
    inst = data.instrument
    tick, mult = inst.tick_size, inst.multiplier
    sess = resolve_sessions(sessions or ["main"], custom_sessions)
    grid = build_grid(data, sess, ex.requote_seconds, use_trades=ex.fill_model == "trades")
    fill_model = make_fill_model(ex.fill_model, ex.touch_fill_prob, ex.max_participation)
    fill_model.prepare(grid, data)
    calibrator = Calibrator(cal, grid, tick)
    rng = np.random.default_rng(ex.seed)

    n = len(grid)
    t_start = pd.Timestamp(trade_start) if trade_start is not None else None
    t_end = pd.Timestamp(trade_end) + pd.Timedelta(days=1) if trade_end is not None else None
    active_day = np.ones(n, dtype=bool)
    if t_start is not None:
        active_day &= grid.time >= t_start
    if t_end is not None:
        active_day &= grid.time < t_end

    rec = {k: np.full(n, np.nan) for k in (
        "bid", "ask", "reservation", "inventory", "cash", "equity", "fees",
        "bid_fill", "ask_fill", "sigma", "A", "k",
    )}
    quoting = np.zeros(n, dtype=bool)
    traded = np.zeros(n, dtype=bool)  # шаг в периоде бэктеста и параметры откалиброваны
    fills: list[dict] = []
    param_rows: list[dict] = []

    inv = 0
    cash = 0.0
    fees = 0.0
    params: ModelParams | None = None
    sigma_live = math.nan
    alpha = 1.0 - 0.5 ** (1.0 / cal.sigma_ewma_halflife) if cal.sigma_ewma_halflife > 0 else 0.0
    mhs = ex.market_half_spread_ticks * tick
    maker_fee = ex.maker_fee_bps * 1e-4
    taker_fee = ex.taker_fee_bps * 1e-4

    def book(i, side, price, lots, t, liquidity, mid):
        nonlocal inv, cash, fees
        notional = price * lots * mult
        fee = notional * (maker_fee if liquidity == "maker" else taker_fee)
        inv += side * lots
        cash -= side * notional + fee
        fees += fee
        fills.append({
            "time": t, "step": i, "side": side, "price": price, "lots": lots,
            "mid": mid, "fee": fee, "liquidity": liquidity, "session_id": int(grid.session_id[i]),
            "notional": notional,
        })

    prev_sid = None
    for i in range(n):
        sid = grid.session_id[i]
        if sid != prev_sid:
            strategy.reset()
            params = calibrator.for_session(i) if active_day[i] else None
            sigma_live = params.sigma if params else math.nan
            if params is not None:
                param_rows.append({"session_id": int(sid), "start": grid.time[i], **params.to_dict()})
            prev_sid = sid
        mid = grid.ref[i]
        traded[i] = params is not None and active_day[i]

        if params is not None and active_day[i] and np.isfinite(mid):
            state = MarketState(
                time=grid.time[i], mid=mid, tau=float(grid.tau[i]), inventory=inv,
                sigma=sigma_live, A=params.A, k=params.k, tick=tick,
                step_seconds=grid.step_seconds, max_inventory=ex.max_inventory,
            )
            q = strategy.quote(state)
            bid, ask = _prepare_quotes(q.bid, q.ask, mid, tick, mhs, ex, inst)
            size = strategy.order_size
            bid_lots = min(q.bid_size or size, ex.max_inventory - inv) if bid is not None else 0
            ask_lots = min(q.ask_size or size, ex.max_inventory + inv) if ask is not None else 0
            bid = bid if bid_lots > 0 else None
            ask = ask if ask_lots > 0 else None
            quoting[i] = bid is not None or ask is not None
            rec["bid"][i] = bid if bid is not None else np.nan
            rec["ask"][i] = ask if ask is not None else np.nan
            rec["reservation"][i] = q.reservation
            fb, fa = fill_model.match(i, bid, ask, bid_lots, ask_lots, params, rng)
            if fb.lots > 0:
                book(i, +1, bid, fb.lots, fb.time, "maker", mid)
            if fa.lots > 0:
                book(i, -1, ask, fa.lots, fa.time, "maker", mid)
            rec["bid_fill"][i] = fb.lots
            rec["ask_fill"][i] = fa.lots

        mark = grid.mark[i]
        if grid.last_in_session[i] and ex.flatten_at_session_end and inv != 0:
            side = -int(np.sign(inv))
            px = mark + side * (mhs + ex.liquidation_slippage_ticks * tick)
            px = inst.round_ask(px) if side > 0 else inst.round_bid(px)  # округление не в нашу пользу
            book(i, side, px, abs(inv), grid.time[i] + pd.Timedelta(seconds=grid.step_seconds), "taker", mark)

        if params is not None:
            rec["sigma"][i], rec["A"][i], rec["k"][i] = sigma_live, params.A, params.k
            if alpha > 0 and np.isfinite(mid) and np.isfinite(mark):
                sigma_live = math.sqrt((1 - alpha) * sigma_live**2 + alpha * (mark - mid) ** 2 / grid.step_seconds)
        rec["inventory"][i] = inv
        rec["cash"][i] = cash
        rec["fees"][i] = fees
        rec["equity"][i] = cash + inv * mark * mult

    steps = pd.DataFrame(rec, index=grid.time)
    steps.insert(0, "mid", grid.ref)
    steps.insert(1, "mark", grid.mark)
    steps["high"], steps["low"] = grid.high, grid.low
    steps["session_id"] = grid.session_id
    steps["tau"] = grid.tau
    steps["quoting"] = quoting
    steps["active"] = traded
    steps.index.name = "time"
    fills_df = pd.DataFrame(fills, columns=[
        "time", "step", "side", "price", "lots", "mid", "fee", "liquidity", "session_id", "notional",
    ])
    return BacktestResult(
        steps=steps,
        fills=fills_df,
        params=pd.DataFrame(param_rows),
        strategy=strategy.label(),
        instrument=inst,
        execution=ex,
        calibration=cal,
        meta={"source": data.source, "step_seconds": grid.step_seconds, "strategy_params": strategy.params()},
    )


def _prepare_quotes(bid, ask, mid, tick, mhs, ex: ExecutionConfig, inst):
    """Округление к шагу цены, post-only и минимальная ширина котировки."""
    bid = inst.round_bid(bid) if bid is not None and np.isfinite(bid) else None
    ask = inst.round_ask(ask) if ask is not None and np.isfinite(ask) else None
    if ex.post_only:
        best_bid_allowed = inst.round_bid(mid - mhs)
        best_ask_allowed = inst.round_ask(mid + mhs)
        if best_bid_allowed >= best_ask_allowed:  # цена на шаге: сдвигаем на тик
            best_bid_allowed = inst.round_bid(best_ask_allowed - tick)
        if bid is not None:
            bid = min(bid, best_bid_allowed)
        if ask is not None:
            ask = max(ask, best_ask_allowed)
    if bid is not None and ask is not None and ask - bid < ex.min_spread_ticks * tick - 1e-9:
        # сохраняем центр котировки, раздвигая до минимальной ширины
        center = (bid + ask) / 2.0
        half = ex.min_spread_ticks * tick / 2.0
        bid, ask = inst.round_bid(center - half), inst.round_ask(center + half)
    if bid is not None and bid <= 0:
        bid = None
    return bid, ask
