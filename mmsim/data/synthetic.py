"""Синтетическая лента сделок «в стиле» ликвидной акции Мосбиржи.

Нужна для офлайн-демо, тестов и проверки модели в условиях, где известна
«истинная» структура рынка. Это НЕ реальные данные: параметры по умолчанию лишь
приближённо похожи на SBER в основной сессии (цена ~300 руб., шаг 0,01,
лот 10, годовая волатильность ~28%, несколько сделок в секунду, U-образная
внутридневная активность).

Модель:
    mid_{t+1} = mid_t + σ·√u(t)·Z_t + impact·(нетто-поток лотов в секунду t) + скачки,
    сделки — пуассоновский поток с интенсивностью ∝ u(t), сторона — марковская
    цепь (дробление заявок), цена сделки = mid ± (полуспред + Exp(k)), округлённая
    к шагу цены. Экспоненциальная «глубина проникновения» сделок согласуется с
    предпосылкой Авельянеды–Стойкова λ(δ) = A·exp(−kδ).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from mmsim.data.market import MarketData, trades_to_candles
from mmsim.instruments import preset


@dataclass
class SyntheticConfig:
    secid: str = "SBER"
    start_date: str = "2025-09-01"
    days: int = 10
    start_price: float = 300.0
    annual_vol: float = 0.28
    tick_size: float = 0.01
    lot_size: int = 10
    session: tuple[str, str] = ("10:00", "18:40")
    trades_per_second: float = 3.0
    depth_k: float = 40.0  # 1/руб.: средняя глубина проникновения сверх полуспреда = 1/k
    half_spread_ticks: float = 0.5
    mean_trade_lots: float = 8.0
    side_persistence: float = 0.3  # 0 — стороны независимы, →1 — длинные серии
    impact: float = 0.0003  # руб. сдвига mid на 1 лот нетто-потока
    jumps_per_day: float = 1.0
    jump_std: float = 0.003  # доля цены
    overnight_vol: float = 0.008
    intraday_u: float = 0.6  # U-образность активности, 0 — равномерно
    bar_seconds: int = 60
    seed: int = 7


def _hms(t: str) -> int:
    h, m = t.split(":")[:2]
    return int(h) * 3600 + int(m) * 60


def _u_shape(n: int, amp: float) -> np.ndarray:
    x = (np.arange(n) + 0.5) / n
    return 1.0 + amp * (3.0 * (2.0 * x - 1.0) ** 2 - 1.0)


def generate(cfg: SyntheticConfig | None = None, **overrides) -> MarketData:
    cfg = cfg or SyntheticConfig()
    for k, v in overrides.items():
        setattr(cfg, k, v)
    rng = np.random.default_rng(cfg.seed)
    s0, s1 = _hms(cfg.session[0]), _hms(cfg.session[1])
    n_sec = s1 - s0
    shape = _u_shape(n_sec, cfg.intraday_u)
    days = pd.bdate_range(cfg.start_date, periods=cfg.days)
    daily_vol = cfg.annual_vol / np.sqrt(252.0)
    tick = cfg.tick_size
    p_same = 0.5 + 0.5 * cfg.side_persistence

    all_t, all_p, all_q, all_s = [], [], [], []
    price = cfg.start_price
    for day in days:
        price *= float(np.exp(rng.normal(0.0, cfg.overnight_vol)))
        sigma_sec = price * daily_vol / np.sqrt(n_sec)

        counts = rng.poisson(cfg.trades_per_second * shape)
        n = int(counts.sum())
        sec_of_trade = np.repeat(np.arange(n_sec), counts)
        flips = np.where(rng.random(n) < p_same, 1, -1)
        flips[0] = 1 if rng.random() < 0.5 else -1
        side = np.cumprod(flips)
        lots = rng.geometric(1.0 / cfg.mean_trade_lots, size=n)
        net = np.bincount(sec_of_trade, weights=side * lots, minlength=n_sec)

        incr = sigma_sec * np.sqrt(shape) * rng.standard_normal(n_sec)
        incr[1:] += cfg.impact * net[:-1]
        n_jumps = rng.poisson(cfg.jumps_per_day)
        if n_jumps:
            incr[rng.integers(1, n_sec, n_jumps)] += rng.normal(0.0, cfg.jump_std * price, n_jumps)
        mid = price + np.concatenate([[0.0], np.cumsum(incr[1:])])
        mid = np.maximum(mid, 10 * tick)

        depth = cfg.half_spread_ticks * tick + rng.exponential(1.0 / cfg.depth_k, size=n)
        raw = mid[sec_of_trade] + side * depth
        px = np.where(side > 0, np.ceil(raw / tick - 1e-9), np.floor(raw / tick + 1e-9)) * tick
        px = np.round(px, 8)

        t = sec_of_trade + rng.random(n)
        order = np.argsort(t, kind="stable")
        stamps = day + pd.to_timedelta(s0, unit="s") + pd.to_timedelta(t[order], unit="s")
        all_t.append(stamps)
        all_p.append(px[order])
        all_q.append(lots[order].astype(float))
        all_s.append(side[order])
        price = float(mid[-1])

    trades = pd.DataFrame(
        {"price": np.concatenate(all_p), "qty": np.concatenate(all_q), "side": np.concatenate(all_s)},
        index=pd.DatetimeIndex(np.concatenate([s.to_numpy() for s in all_t]), name="time"),
    )
    inst = preset(cfg.secid, lot_size=cfg.lot_size, tick_size=cfg.tick_size)
    candles = trades_to_candles(trades, cfg.bar_seconds, cfg.lot_size)
    return MarketData(
        inst, candles, trades, cfg.bar_seconds, source="synthetic",
        meta={"synthetic": cfg.__dict__.copy()},
    )
