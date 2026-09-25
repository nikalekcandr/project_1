"""Единый контейнер рыночных данных."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from mmsim.instruments import Instrument

CANDLE_COLUMNS = ["open", "high", "low", "close", "volume", "value"]
TRADE_COLUMNS = ["price", "qty", "side"]


@dataclass
class MarketData:
    """Рыночные данные одного инструмента.

    candles: индекс — начало бара (московское время, naive), колонки
        open/high/low/close, volume (штук для акций, контрактов для фьючерсов),
        value (руб.).
    trades: необязательная лента сделок, индекс — время сделки, колонки
        price, qty (лоты), side (+1 — инициатор покупатель, −1 — продавец, 0 — неизвестно).
    """

    instrument: Instrument
    candles: pd.DataFrame
    trades: pd.DataFrame | None = None
    bar_seconds: int = 60
    source: str = ""
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.candles = normalize_candles(self.candles)
        if self.trades is not None:
            self.trades = normalize_trades(self.trades)

    @property
    def days(self) -> list[pd.Timestamp]:
        return sorted(pd.DatetimeIndex(self.candles.index).normalize().unique())

    def slice(self, start=None, end=None) -> "MarketData":
        """Срез по датам включительно: ``end`` — последний торговый день."""
        c = self.candles
        t = self.trades
        if start is not None:
            s = pd.Timestamp(start)
            c = c[c.index >= s]
            t = t[t.index >= s] if t is not None else None
        if end is not None:
            e = pd.Timestamp(end) + pd.Timedelta(days=1)
            c = c[c.index < e]
            t = t[t.index < e] if t is not None else None
        return MarketData(self.instrument, c, t, self.bar_seconds, self.source, dict(self.meta))

    def summary(self) -> str:
        c = self.candles
        lines = [
            f"Инструмент: {self.instrument.secid} ({self.instrument.board}), "
            f"лот {self.instrument.lot_size}, шаг цены {self.instrument.tick_size}",
            f"Источник: {self.source or '—'}",
            f"Бары: {len(c)} × {self.bar_seconds} с, дней: {len(self.days)}"
            + (f" ({c.index[0]:%Y-%m-%d} … {c.index[-1]:%Y-%m-%d})" if len(c) else ""),
        ]
        if len(c):
            lines.append(
                f"Цена: {c['close'].iloc[0]:.{self.instrument.decimals}f} → "
                f"{c['close'].iloc[-1]:.{self.instrument.decimals}f}, "
                f"оборот {c['value'].sum() / 1e9:.2f} млрд руб."
            )
        if self.trades is not None:
            lines.append(f"Сделок в ленте: {len(self.trades)}")
        return "\n".join(lines)


def normalize_candles(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index)
    out.index.name = "time"
    for col in ("open", "high", "low", "close"):
        if col not in out:
            raise ValueError(f"В свечах нет колонки '{col}'")
        out[col] = out[col].astype(float)
    if "volume" not in out:
        out["volume"] = np.nan
    if "value" not in out:
        out["value"] = out["close"] * out["volume"]
    out = out[CANDLE_COLUMNS].astype(float)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


def normalize_trades(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index)
    out.index.name = "time"
    if "side" not in out:
        out["side"] = 0
    out = out[TRADE_COLUMNS]
    out["price"] = out["price"].astype(float)
    out["qty"] = out["qty"].astype(float)
    out["side"] = out["side"].fillna(0).astype(int)
    out = out.sort_index(kind="stable")
    if (out["side"] == 0).any():
        out["side"] = infer_sides_tick_rule(out["price"].to_numpy(), out["side"].to_numpy())
    return out


def infer_sides_tick_rule(price: np.ndarray, side: np.ndarray) -> np.ndarray:
    """Tick rule: неизвестная сторона = знак последнего ненулевого изменения цены."""
    side = side.astype(int).copy()
    if len(price) == 0:
        return side
    tick = np.sign(np.diff(price, prepend=price[0]))
    tick = pd.Series(np.where(tick == 0, np.nan, tick)).ffill().fillna(1.0).to_numpy()
    unknown = side == 0
    side[unknown] = tick[unknown].astype(int)
    return side


def trades_to_candles(trades: pd.DataFrame, bar_seconds: int, lot_size: int) -> pd.DataFrame:
    """Агрегирует ленту сделок в бары (пустые интервалы пропускаются, как в ISS)."""
    t = trades
    grp = t.index.floor(f"{bar_seconds}s")
    shares = t["qty"] * lot_size
    g = pd.DataFrame(
        {"price": t["price"].to_numpy(), "shares": shares.to_numpy(), "val": (t["price"] * shares).to_numpy()},
        index=grp,
    ).groupby(level=0)
    out = pd.DataFrame(
        {
            "open": g["price"].first(),
            "high": g["price"].max(),
            "low": g["price"].min(),
            "close": g["price"].last(),
            "volume": g["shares"].sum(),
            "value": g["val"].sum(),
        }
    )
    out.index.name = "time"
    return out
