"""mmsim — симулятор маркет-мейкинга Авельянеды–Стойкова на данных Московской биржи."""

from mmsim.data import MarketData, MoexISS, generate
from mmsim.engine import BacktestResult, CalibrationConfig, ExecutionConfig, run_backtest
from mmsim.instruments import Instrument, preset
from mmsim.strategies import AvellanedaStoikov, FixedSpread, GLFT, GLFTExact, make_strategy

__version__ = "0.1.0"

__all__ = [
    "AvellanedaStoikov",
    "BacktestResult",
    "CalibrationConfig",
    "ExecutionConfig",
    "FixedSpread",
    "GLFT",
    "GLFTExact",
    "Instrument",
    "MarketData",
    "MoexISS",
    "generate",
    "make_strategy",
    "preset",
    "run_backtest",
]
