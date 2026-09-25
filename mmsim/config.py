"""Конфигурация симуляции (TOML) и загрузка данных по ней."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import pandas as pd

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

from mmsim.data.csv_loader import load_candles_csv, load_trades_csv
from mmsim.data.market import MarketData, trades_to_candles
from mmsim.data.moex import MoexISS
from mmsim.data.synthetic import SyntheticConfig, generate
from mmsim.engine import CalibrationConfig, ExecutionConfig
from mmsim.instruments import preset


@dataclass
class DataConfig:
    source: str = "moex"  # moex | csv | synthetic
    secid: str = "SBER"
    board: str = "TQBR"
    engine: str = "stock"
    market: str = "shares"
    start: str | None = None  # первый торговый день бэктеста
    end: str | None = None  # последний торговый день
    interval: int = 1  # минут в свече ISS: 1 | 10 | 60
    trades: bool = False  # лента сделок ISS (только текущая сессия)
    cache_dir: str = "data/cache"
    candles_csv: str | None = None
    trades_csv: str | None = None
    csv_bar_seconds: int = 60
    csv_volume_in_lots: bool = False
    synthetic_days: int = 10
    synthetic_seed: int = 7


@dataclass
class InstrumentConfig:
    lot_size: int | None = None
    tick_size: float | None = None
    step_price: float | None = None


@dataclass
class StrategyConfig:
    name: str = "as"
    gamma: float = 0.01
    order_size: int = 1
    horizon: str = "session"
    horizon_seconds: float = 3600.0
    half_spread_ticks: float = 5.0
    skew_ticks_per_unit: float = 0.0
    terminal_penalty: float = 0.0


@dataclass
class SessionsConfig:
    use: list[str] = field(default_factory=lambda: ["main"])
    custom: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class ReportConfig:
    out_dir: str = "reports/latest"
    plot_day: str | None = None  # день для детального графика котировок


@dataclass
class SimConfig:
    data: DataConfig = field(default_factory=DataConfig)
    instrument: InstrumentConfig = field(default_factory=InstrumentConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    calibration: CalibrationConfig = field(default_factory=CalibrationConfig)
    sessions: SessionsConfig = field(default_factory=SessionsConfig)
    report: ReportConfig = field(default_factory=ReportConfig)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SimConfig":
        cfg = cls()
        for f in fields(cls):
            section = raw.get(f.name, {})
            target = getattr(cfg, f.name)
            _apply(target, section, f.name)
        unknown = set(raw) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"Неизвестные разделы конфигурации: {', '.join(sorted(unknown))}")
        return cfg

    @classmethod
    def load(cls, path: str | Path) -> "SimConfig":
        with open(path, "rb") as fh:
            return cls.from_dict(tomllib.load(fh))

    def set(self, dotted: str, value: Any) -> None:
        """Переопределение вида ``strategy.gamma=0.1`` (строка приводится к типу поля)."""
        section, _, key = dotted.partition(".")
        target = getattr(self, section, None)
        if target is None or not key or not hasattr(target, key):
            raise ValueError(f"Неизвестный параметр '{dotted}'")
        current = getattr(target, key)
        setattr(target, key, _coerce(value, current))


def _apply(target, section: dict, name: str) -> None:
    allowed = {f.name for f in fields(target)}
    for key, value in section.items():
        if key not in allowed:
            raise ValueError(f"Неизвестный параметр [{name}] {key}. Допустимые: {', '.join(sorted(allowed))}")
        setattr(target, key, value)


def _coerce(value: Any, current: Any) -> Any:
    if not isinstance(value, str):
        return value
    low = value.strip().lower()
    if low in ("none", "null", ""):
        return None
    if isinstance(current, bool):
        return low in ("1", "true", "yes", "да", "on")
    if isinstance(current, int):
        number = float(value)
        return int(number) if number.is_integer() else number
    if isinstance(current, float):
        return float(value)
    if isinstance(current, list):
        return [v.strip() for v in value.split(",") if v.strip()]
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            pass
    return value


def load_market_data(cfg: SimConfig, progress=None) -> tuple[MarketData, str | None, str | None]:
    """Загружает данные согласно [data]. Возвращает (данные, trade_start, trade_end).

    Для walk-forward калибровки с MOEX дополнительно подгружается история до
    ``start`` (``window_days`` торговых дней с запасом на выходные).
    """
    d = cfg.data
    inst_over = {k: v for k, v in vars(cfg.instrument).items() if v is not None}
    if d.source == "synthetic":
        n_days = d.synthetic_days
        start = d.start or "2025-09-01"
        md = generate(SyntheticConfig(
            secid=d.secid, start_date=start, days=n_days, seed=d.synthetic_seed,
            lot_size=inst_over.get("lot_size", preset(d.secid).lot_size),
            tick_size=inst_over.get("tick_size", preset(d.secid).tick_size),
        ))
        md.instrument = md.instrument.with_overrides(**inst_over)
        return md, None, None
    if d.source == "csv":
        inst = preset(d.secid, board=d.board, engine=d.engine, market=d.market, **inst_over)
        trades = load_trades_csv(d.trades_csv) if d.trades_csv else None
        if d.candles_csv:
            candles = load_candles_csv(d.candles_csv, d.csv_volume_in_lots, inst.lot_size)
            bar = d.csv_bar_seconds
        elif trades is not None:
            bar = d.csv_bar_seconds
            candles = trades_to_candles(trades, bar, inst.lot_size)
        else:
            raise ValueError("Для source='csv' задайте candles_csv и/или trades_csv")
        md = MarketData(inst, candles, trades, bar, source=f"CSV {d.candles_csv or d.trades_csv}")
        return md, d.start, d.end
    if d.source == "moex":
        if not d.trades and (d.start is None or d.end is None):
            raise ValueError("Для source='moex' задайте data.start и data.end (YYYY-MM-DD)")
        client = MoexISS(cache_dir=d.cache_dir)
        inst = client.instrument(d.secid, d.engine, d.market, d.board).with_overrides(**inst_over)
        if d.trades:
            md = client.load(d.secid, None, None, d.interval, d.engine, d.market, d.board, True, inst)
            return md, None, None
        lookback = 0
        if cfg.calibration.mode == "walk_forward":
            lookback = int(cfg.calibration.window_days * 7 / 5) + 4
        hist_start = (pd.Timestamp(d.start) - pd.Timedelta(days=lookback)).strftime("%Y-%m-%d")
        md = client.load(d.secid, hist_start, d.end, d.interval, d.engine, d.market, d.board, False, inst, progress)
        return md, d.start, d.end
    raise ValueError("data.source: moex | csv | synthetic")
