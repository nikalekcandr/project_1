"""Клиент информационно-статистического сервера Московской биржи (MOEX ISS).

Используются бесплатные публичные эндпоинты (без авторизации):

* ``/engines/{engine}/markets/{market}/boards/{board}/securities/{secid}.json`` —
  параметры инструмента (лот, шаг цены, стоимость шага для фьючерсов);
* ``.../securities/{secid}/candles.json`` — исторические свечи (1, 10, 60 минут, день);
* ``.../securities/{secid}/trades.json`` — лента сделок текущей торговой сессии
  с признаком инициатора (BUYSELL).

Документация ISS: https://iss.moex.com/iss/reference/ . Ответы кэшируются на диск
по дням; кэшируются только завершённые дни.
"""

from __future__ import annotations

import time as _time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

from mmsim.data.market import MarketData, normalize_candles, trades_to_candles
from mmsim.instruments import Instrument

ISS_URL = "https://iss.moex.com/iss"
CANDLE_INTERVALS = {1: 60, 10: 600, 60: 3600, 24: 86400}


class MoexUnavailable(RuntimeError):
    """ISS недоступен (нет сети, блокировка, ошибка сервера)."""


class MoexISS:
    def __init__(
        self,
        cache_dir: str | Path | None = "data/cache",
        session: requests.Session | None = None,
        base_url: str = ISS_URL,
        timeout: float = 30.0,
        retries: int = 3,
        backoff: float = 1.0,
    ) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "mmsim/0.1 (market-making simulator)")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff

    # ------------------------------------------------------------------ HTTP
    def get_json(self, path: str, params: dict[str, Any] | None = None) -> dict:
        url = f"{self.base_url}/{path.lstrip('/')}"
        query = {"iss.meta": "off", **(params or {})}
        last_err: Exception | None = None
        for attempt in range(self.retries):
            try:
                resp = self.session.get(url, params=query, timeout=self.timeout)
                resp.raise_for_status()
                return resp.json()
            except (requests.RequestException, ValueError) as err:
                last_err = err
                if attempt + 1 < self.retries:
                    _time.sleep(self.backoff * 2**attempt)
        raise MoexUnavailable(
            f"Не удалось получить {url}: {last_err}. Проверьте доступ к iss.moex.com "
            "или используйте источник данных 'csv' / 'synthetic'."
        )

    @staticmethod
    def block(payload: dict, name: str) -> pd.DataFrame:
        """Преобразует блок ISS {columns: [...], data: [[...]]} в DataFrame."""
        blk = payload.get(name)
        if not blk:
            return pd.DataFrame()
        return pd.DataFrame(blk.get("data", []), columns=blk.get("columns", []))

    def paged(self, path: str, params: dict[str, Any], name: str, max_pages: int = 10_000) -> pd.DataFrame:
        """Постраничная выгрузка через параметр ``start``."""
        frames = []
        start = 0
        for _ in range(max_pages):
            payload = self.get_json(path, {**params, "start": start})
            df = self.block(payload, name)
            if df.empty:
                break
            frames.append(df)
            start += len(df)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    # ------------------------------------------------------------ instrument
    @staticmethod
    def _sec_path(secid: str, engine: str, market: str, board: str) -> str:
        return f"engines/{engine}/markets/{market}/boards/{board}/securities/{secid}"

    def security(self, secid: str, engine="stock", market="shares", board="TQBR") -> dict[str, Any]:
        payload = self.get_json(self._sec_path(secid, engine, market, board) + ".json")
        sec = self.block(payload, "securities")
        if sec.empty:
            raise ValueError(f"Инструмент {secid} не найден в режиме {board} ({engine}/{market})")
        row = sec.iloc[0].to_dict()
        md = self.block(payload, "marketdata")
        if not md.empty:
            row["marketdata"] = md.iloc[0].to_dict()
        return row

    def instrument(self, secid: str, engine="stock", market="shares", board="TQBR") -> Instrument:
        info = self.security(secid, engine, market, board)
        return instrument_from_iss(info, secid, engine, market, board)

    # ---------------------------------------------------------------- candles
    def _cache_file(self, kind: str, secid: str, engine: str, market: str, board: str, day: date) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / f"{engine}_{market}_{board}_{secid}_{kind}" / f"{day:%Y-%m-%d}.csv"

    def candles_day(self, secid: str, day: date, interval=1, engine="stock", market="shares", board="TQBR") -> pd.DataFrame:
        cache = self._cache_file(f"c{interval}", secid, engine, market, board, day)
        if cache is not None and cache.exists():
            df = pd.read_csv(cache)
        else:
            path = self._sec_path(secid, engine, market, board) + "/candles.json"
            params = {"from": f"{day:%Y-%m-%d}", "till": f"{day:%Y-%m-%d}", "interval": interval}
            df = self.paged(path, params, "candles")
            if cache is not None and day < _moscow_today():
                cache.parent.mkdir(parents=True, exist_ok=True)
                df.to_csv(cache, index=False)
        return parse_candles(df)

    def candles(
        self, secid: str, start, end, interval=1, engine="stock", market="shares", board="TQBR", progress=None
    ) -> pd.DataFrame:
        if interval not in CANDLE_INTERVALS:
            raise ValueError(f"Интервал свечей {interval} не поддерживается: {list(CANDLE_INTERVALS)}")
        d0, d1 = pd.Timestamp(start).date(), pd.Timestamp(end).date()
        frames = []
        day = d0
        while day <= d1:
            df = self.candles_day(secid, day, interval, engine, market, board)
            if progress:
                progress(day, len(df))
            if not df.empty:
                frames.append(df)
            day += timedelta(days=1)
        if not frames:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "value"])
        return pd.concat(frames).sort_index()

    # ----------------------------------------------------------------- trades
    def trades(self, secid: str, engine="stock", market="shares", board="TQBR", lot_size: int | None = None) -> pd.DataFrame:
        """Лента сделок текущей (или последней) торговой сессии."""
        path = self._sec_path(secid, engine, market, board) + "/trades.json"
        raw = self.paged(path, {}, "trades")
        return parse_trades(raw, lot_size=lot_size if engine == "stock" else None)

    # ------------------------------------------------------------------ load
    def load(
        self,
        secid: str,
        start,
        end,
        interval: int = 1,
        engine: str = "stock",
        market: str = "shares",
        board: str = "TQBR",
        with_trades: bool = False,
        instrument: Instrument | None = None,
        progress=None,
    ) -> MarketData:
        inst = instrument or self.instrument(secid, engine, market, board)
        if with_trades:
            trades = self.trades(secid, engine, market, board, lot_size=inst.lot_size)
            candles = trades_to_candles(trades, CANDLE_INTERVALS[interval], inst.lot_size)
        else:
            trades = None
            candles = self.candles(secid, start, end, interval, engine, market, board, progress)
            if engine == "stock":
                candles = fix_volume_units(candles, inst.lot_size)
        if candles.empty:
            raise ValueError(f"MOEX ISS не вернул данных по {secid} за {start} … {end}")
        return MarketData(
            inst, candles, trades, CANDLE_INTERVALS[interval], source=f"MOEX ISS {engine}/{market}/{board}"
        )


# ---------------------------------------------------------------- парсеры
def _moscow_today() -> date:
    return (datetime.now(timezone.utc) + timedelta(hours=3)).date()


def instrument_from_iss(info: dict, secid: str, engine: str, market: str, board: str) -> Instrument:
    tick = float(info.get("MINSTEP") or 0.01)
    name = str(info.get("SHORTNAME") or info.get("SECNAME") or secid)
    if engine == "futures":
        step_price = info.get("STEPPRICE")
        return Instrument(
            secid, board, engine, market, lot_size=1, tick_size=tick,
            step_price=float(step_price) if step_price else None, name=name,
        )
    lot = int(info.get("LOTSIZE") or 1)
    currency = str(info.get("CURRENCYID") or "RUB").replace("SUR", "RUB")
    return Instrument(secid, board, engine, market, lot_size=lot, tick_size=tick, currency=currency, name=name)


def parse_candles(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "value"])
    out = df.copy()
    out.index = pd.to_datetime(out.pop("begin"))
    out = out.drop(columns=[c for c in ("end",) if c in out])
    return normalize_candles(out)


def fix_volume_units(candles: pd.DataFrame, lot_size: int) -> pd.DataFrame:
    """Приводит объём свечей к штукам.

    Проверка по обороту: value ≈ volume × price, если объём в штуках, и
    value ≈ volume × price × lot_size, если объём в лотах.
    """
    if candles.empty or lot_size <= 1:
        return candles
    denom = float((candles["volume"] * candles["close"]).sum())
    if denom <= 0:
        return candles
    ratio = float(candles["value"].sum()) / denom
    if abs(ratio - lot_size) / lot_size < 0.2:
        candles = candles.copy()
        candles["volume"] = candles["volume"] * lot_size
    return candles


def parse_trades(raw: pd.DataFrame, lot_size: int | None = None) -> pd.DataFrame:
    """Лента ISS → колонки price, qty (лоты), side (+1/−1)."""
    if raw.empty:
        return pd.DataFrame(columns=["price", "qty", "side"], index=pd.DatetimeIndex([], name="time"))
    cols = set(raw.columns)
    if "TRADEDATE" in cols:
        day = raw["TRADEDATE"].astype(str)
    elif "SYSTIME" in cols:
        day = raw["SYSTIME"].astype(str).str.slice(0, 10)
    else:
        day = pd.Series([f"{_moscow_today():%Y-%m-%d}"] * len(raw))
    ts = pd.to_datetime(day + " " + raw["TRADETIME"].astype(str))
    price = raw["PRICE"].astype(float).to_numpy()
    if lot_size and "VALUE" in cols:
        # QUANTITY в ISS для акций — в лотах; пересчёт через оборот не зависит от единиц
        qty = np.round(raw["VALUE"].astype(float).to_numpy() / price / lot_size, 6)
    else:
        qty = raw["QUANTITY"].astype(float).to_numpy()
    side = np.zeros(len(raw), dtype=int)
    if "BUYSELL" in cols:
        bs = raw["BUYSELL"].astype(str).str.upper().to_numpy()
        side = np.where(bs == "B", 1, np.where(bs == "S", -1, 0))
    out = pd.DataFrame({"price": price, "qty": qty, "side": side}, index=pd.DatetimeIndex(ts, name="time"))
    if "TRADENO" in cols:
        out = out.iloc[np.argsort(raw["TRADENO"].to_numpy(), kind="stable")]
    return out.sort_index(kind="stable")
