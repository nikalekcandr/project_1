"""Загрузка свечей и тиков из CSV.

Поддерживаются:

* экспорт Финама (заголовки ``<TICKER>,<PER>,<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>``
  и тики ``<DATE>,<TIME>,<LAST>,<VOL>,<ID>,<OPER>``);
* формат MOEX ISS (``begin,open,close,high,low,value,volume``);
* произвольный CSV с колонками ``time|datetime|begin, open, high, low, close, volume[, value]``
  или ``time, price, qty[, side]`` для сделок.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from mmsim.data.market import normalize_candles, normalize_trades


def _read(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=None, engine="python")
    df.columns = [str(c).strip().strip("<>").lower() for c in df.columns]
    return df


def _finam_datetime(df: pd.DataFrame) -> pd.DatetimeIndex:
    d = df["date"].astype(str).str.strip()
    t = df["time"].astype(str).str.strip().str.replace(":", "", regex=False).str.zfill(6)
    if d.str.contains("/").any():
        return pd.DatetimeIndex(pd.to_datetime(d + " " + t, format="%d/%m/%y %H%M%S"))
    if d.str.contains(r"\.").any():
        return pd.DatetimeIndex(pd.to_datetime(d + " " + t, format="%d.%m.%Y %H%M%S"))
    return pd.DatetimeIndex(pd.to_datetime(d.str.zfill(8) + " " + t, format="%Y%m%d %H%M%S"))


def _time_index(df: pd.DataFrame) -> pd.DatetimeIndex:
    if "date" in df and "time" in df:
        return _finam_datetime(df)
    for col in ("time", "datetime", "begin", "timestamp", "date"):
        if col in df:
            return pd.DatetimeIndex(pd.to_datetime(df[col]))
    raise ValueError("Не найдена колонка времени (time/datetime/begin или date+time)")


def load_candles_csv(path: str | Path, volume_in_lots: bool = False, lot_size: int = 1) -> pd.DataFrame:
    df = _read(path)
    idx = _time_index(df)
    rename = {"vol": "volume", "last": "close"}
    df = df.rename(columns=rename)
    out = pd.DataFrame(
        {c: df[c].to_numpy() for c in ("open", "high", "low", "close", "volume", "value") if c in df},
        index=idx,
    )
    if volume_in_lots and "volume" in out:
        out["volume"] = out["volume"] * lot_size
    return normalize_candles(out)


def load_trades_csv(path: str | Path, qty_in_shares: bool = False, lot_size: int = 1) -> pd.DataFrame:
    """Сделки: price, qty (лоты), side. Для Финама колонка ``OPER`` (B/S) задаёт инициатора."""
    df = _read(path)
    idx = _time_index(df)
    price_col = next((c for c in ("price", "last", "close") if c in df), None)
    qty_col = next((c for c in ("qty", "quantity", "vol", "volume") if c in df), None)
    if price_col is None or qty_col is None:
        raise ValueError("В ленте сделок нужны колонки цены (price/last) и объёма (qty/vol)")
    qty = df[qty_col].astype(float).to_numpy()
    if qty_in_shares:
        qty = qty / lot_size
    side = np.zeros(len(df), dtype=int)
    side_col = next((c for c in ("side", "oper", "buysell") if c in df), None)
    if side_col is not None:
        raw = df[side_col].astype(str).str.strip().str.upper()
        side = np.select([raw.isin(["B", "BUY", "1", "+1"]), raw.isin(["S", "SELL", "-1"])], [1, -1], 0)
    out = pd.DataFrame({"price": df[price_col].astype(float).to_numpy(), "qty": qty, "side": side}, index=idx)
    return normalize_trades(out)
