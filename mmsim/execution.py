"""Сетка шагов симуляции и модели исполнения лимитных заявок.

Публичные данные MOEX не содержат стакана, поэтому исполнение пассивных заявок
моделируется по ценам сделок. Три модели:

``candle``    — по свечам: заявка на покупку по цене b исполняется, если
                low < b (цену «проторговали насквозь»), либо с вероятностью
                ``touch_fill_prob`` при low == b (мы стоим в очереди на уровне).
                Объём исполнения ограничен долей ``max_participation`` оборота бара.
``trades``    — по ленте сделок с признаком инициатора: покупку исполняют
                продажи-инициаторы по цене < b (или = b с вероятностью очереди),
                объём ограничен объёмом этих сделок.
``intensity`` — модель статьи: исполнение за шаг с вероятностью
                1 − exp(−A·e^{−kδ}·Δt), δ — расстояние от mid; цены — из данных.

Котировки на шаге i считаются только по информации до начала шага
(цена закрытия предыдущего бара), поэтому заглядывания в будущее нет.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
import pandas as pd

from mmsim.data.market import MarketData, trades_to_candles
from mmsim.sessions import Session, assign_sessions


@dataclass
class Grid:
    """Шаги симуляции (numpy-массивы одинаковой длины)."""

    time: pd.DatetimeIndex  # начало шага
    step_seconds: float
    ref: np.ndarray  # оценка mid на начало шага (NaN — не котируем)
    mark: np.ndarray  # цена на конец шага (переоценка)
    high: np.ndarray
    low: np.ndarray
    volume: np.ndarray  # штук
    session_id: np.ndarray
    tau: np.ndarray  # секунд до конца сессии от начала шага
    last_in_session: np.ndarray
    bars: pd.DataFrame  # бары для калибровки (тот же шаг, что и сетка)

    def __len__(self) -> int:
        return len(self.ref)


def build_grid(data: MarketData, sessions: list[Session], step_seconds: int | None = None, use_trades: bool = False) -> Grid:
    if use_trades:
        if data.trades is None or data.trades.empty:
            raise ValueError("Модель исполнения 'trades' требует ленту сделок")
        step = int(step_seconds or 10)
        bars = _regular_bars(data, sessions, step)
    else:
        step = int(data.bar_seconds)
        bars = data.candles
    info = assign_sessions(bars.index, sessions, step)
    keep = info["session_id"].to_numpy() >= 0
    bars, info = bars[keep], info[keep]
    if bars.empty:
        raise ValueError("Нет баров внутри выбранных торговых сессий — проверьте [sessions] и даты")
    sid = info["session_id"].to_numpy()
    close = bars["close"].to_numpy(float)
    same_as_prev = np.r_[False, sid[1:] == sid[:-1]]
    ref = np.where(same_as_prev, np.r_[np.nan, close[:-1]], np.nan)
    last = np.r_[sid[1:] != sid[:-1], True]
    tau = (pd.DatetimeIndex(info["session_end"]) - bars.index).total_seconds().to_numpy()
    return Grid(
        time=pd.DatetimeIndex(bars.index),
        step_seconds=float(step),
        ref=ref,
        mark=close,
        high=bars["high"].to_numpy(float),
        low=bars["low"].to_numpy(float),
        volume=bars["volume"].to_numpy(float),
        session_id=sid,
        tau=np.maximum(tau, 0.0),
        last_in_session=last,
        bars=bars.assign(session_id=sid),
    )


def _regular_bars(data: MarketData, sessions: list[Session], step: int) -> pd.DataFrame:
    """Бары фиксированной длины по ленте сделок: пустые интервалы — без high/low, close протянут."""
    raw = trades_to_candles(data.trades, step, data.instrument.lot_size)
    frames = []
    for day in pd.DatetimeIndex(raw.index).normalize().unique():
        for s in sessions:
            t0 = day + pd.Timedelta(hours=s.start.hour, minutes=s.start.minute, seconds=s.start.second)
            idx = pd.date_range(t0, periods=int(s.seconds // step), freq=f"{step}s")
            part = raw.reindex(idx)
            if part["close"].notna().any():
                part["close"] = part["close"].ffill()
                part["volume"] = part["volume"].fillna(0.0)
                part["value"] = part["value"].fillna(0.0)
                frames.append(part)
    out = pd.concat(frames)
    out.index.name = "time"
    return out


@dataclass
class StepFill:
    lots: int = 0
    time: pd.Timestamp | None = None


class FillModel(ABC):
    name = "base"

    def prepare(self, grid: Grid, data: MarketData) -> None:
        self.grid = grid
        self.lot_size = data.instrument.lot_size

    @abstractmethod
    def match(self, i: int, bid: float | None, ask: float | None, bid_lots: int, ask_lots: int, params, rng) -> tuple[StepFill, StepFill]:
        ...


class CandleFill(FillModel):
    name = "candle"

    def __init__(self, touch_fill_prob: float = 0.3, max_participation: float = 0.2, eps: float = 1e-9):
        self.touch_fill_prob = touch_fill_prob
        self.max_participation = max_participation
        self.eps = eps

    def _cap(self, i: int) -> float:
        vol = self.grid.volume[i]
        if not np.isfinite(vol) or self.max_participation <= 0:
            return np.inf
        return np.floor(self.max_participation * vol / self.lot_size)

    def _hit(self, through: bool, touch: bool, rng) -> bool:
        return through or (touch and rng.random() < self.touch_fill_prob)

    def match(self, i, bid, ask, bid_lots, ask_lots, params, rng):
        g = self.grid
        t = g.time[i]
        cap = self._cap(i)
        fb, fa = StepFill(), StepFill()
        lo, hi = g.low[i], g.high[i]
        if bid is not None and bid_lots > 0 and np.isfinite(lo):
            if self._hit(lo < bid - self.eps, abs(lo - bid) <= self.eps, rng):
                fb = StepFill(int(min(bid_lots, cap)), t)
        if ask is not None and ask_lots > 0 and np.isfinite(hi):
            if self._hit(hi > ask + self.eps, abs(hi - ask) <= self.eps, rng):
                fa = StepFill(int(min(ask_lots, cap)), t)
        return fb, fa


class TradesFill(FillModel):
    name = "trades"

    def __init__(self, touch_fill_prob: float = 0.3, eps: float = 1e-9):
        self.touch_fill_prob = touch_fill_prob
        self.eps = eps

    def prepare(self, grid: Grid, data: MarketData) -> None:
        super().prepare(grid, data)
        tr = data.trades
        self.t = tr.index.to_numpy()
        self.price = tr["price"].to_numpy(float)
        self.qty = tr["qty"].to_numpy(float)
        self.side = tr["side"].to_numpy(int)
        start = grid.time.to_numpy()
        end = start + np.timedelta64(int(grid.step_seconds * 1e9), "ns")
        self.lo = np.searchsorted(self.t, start, side="left")
        self.hi = np.searchsorted(self.t, end, side="left")

    def _side_fill(self, sl, aggressor: int, through_mask_fn, level_mask_fn, lots: int, rng) -> StepFill:
        side = self.side[sl]
        px = self.price[sl]
        qty = self.qty[sl]
        mask_side = side == aggressor
        through = mask_side & through_mask_fn(px)
        level = mask_side & level_mask_fn(px)
        available = qty[through].sum()
        if level.any() and rng.random() < self.touch_fill_prob:
            available += qty[level].sum()
        else:
            level = np.zeros_like(level)
        filled = int(min(lots, np.floor(available + 1e-9)))
        if filled <= 0:
            return StepFill()
        first = np.flatnonzero(through | level)[0]
        return StepFill(filled, pd.Timestamp(self.t[sl][first]))

    def match(self, i, bid, ask, bid_lots, ask_lots, params, rng):
        sl = slice(self.lo[i], self.hi[i])
        fb, fa = StepFill(), StepFill()
        if sl.start >= sl.stop:
            return fb, fa
        e = self.eps
        if bid is not None and bid_lots > 0:
            fb = self._side_fill(sl, -1, lambda p: p < bid - e, lambda p: np.abs(p - bid) <= e, bid_lots, rng)
        if ask is not None and ask_lots > 0:
            fa = self._side_fill(sl, 1, lambda p: p > ask + e, lambda p: np.abs(p - ask) <= e, ask_lots, rng)
        return fb, fa


class IntensityFill(FillModel):
    """Исполнение по пуассоновской интенсивности λ(δ) = A·exp(−kδ) (как в статье).

    A и k берутся из откалиброванных параметров шага, либо фиксируются
    (``A``/``k`` в конструкторе) — например, для проверки устойчивости к
    неверной калибровке.
    """

    name = "intensity"

    def __init__(self, A: float | None = None, k: float | None = None):
        self.A = A
        self.k = k

    def match(self, i, bid, ask, bid_lots, ask_lots, params, rng):
        g = self.grid
        A = self.A if self.A is not None else params.A
        k = self.k if self.k is not None else params.k
        mid, dt, t = g.ref[i], g.step_seconds, g.time[i]
        fb, fa = StepFill(), StepFill()
        if bid is not None and bid_lots > 0:
            p = 1.0 - np.exp(-A * np.exp(-k * max(mid - bid, 0.0)) * dt)
            if rng.random() < p:
                fb = StepFill(bid_lots, t)
        if ask is not None and ask_lots > 0:
            p = 1.0 - np.exp(-A * np.exp(-k * max(ask - mid, 0.0)) * dt)
            if rng.random() < p:
                fa = StepFill(ask_lots, t)
        return fb, fa


def make_fill_model(name: str, touch_fill_prob: float = 0.3, max_participation: float = 0.2, A=None, k=None) -> FillModel:
    if name == "candle":
        return CandleFill(touch_fill_prob, max_participation)
    if name == "trades":
        return TradesFill(touch_fill_prob)
    if name == "intensity":
        return IntensityFill(A, k)
    raise ValueError(f"Неизвестная модель исполнения '{name}': candle | trades | intensity")
