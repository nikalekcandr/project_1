"""Стратегии котирования.

Стратегия получает ``MarketState`` (только информация, доступная на момент
выставления котировок) и возвращает ``Quote``. Округление к шагу цены, лимиты
позиции и запрет пересечения рынка применяет движок — стратегии работают в
«непрерывных» ценах модели.
"""

from __future__ import annotations

import inspect
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

from mmsim.models import avellaneda_stoikov as AS
from mmsim.models import glft


@dataclass
class MarketState:
    time: object  # pd.Timestamp начала шага
    mid: float  # оценка mid-цены
    tau: float  # секунд до конца сессии
    inventory: int  # позиция, лоты
    sigma: float  # руб./√с
    A: float  # 1/с
    k: float  # 1/руб.
    tick: float
    step_seconds: float
    max_inventory: int


@dataclass
class Quote:
    bid: float | None
    ask: float | None
    reservation: float = math.nan
    bid_size: int | None = None  # лоты; None — размер по умолчанию стратегии
    ask_size: int | None = None


class Strategy(ABC):
    name: str = "base"

    def __init__(self, order_size: int = 1):
        if order_size < 1:
            raise ValueError("order_size должен быть ≥ 1 лота")
        self.order_size = int(order_size)

    def reset(self) -> None:  # вызывается в начале каждой сессии
        pass

    def units(self, state: MarketState) -> float:
        """Запас в единицах размера котировки (q в формулах моделей)."""
        return state.inventory / self.order_size

    @abstractmethod
    def quote(self, state: MarketState) -> Quote: ...

    def params(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}

    def label(self) -> str:
        return self.name


class AvellanedaStoikov(Strategy):
    """Авельянеда–Стойков.

    horizon:
        ``session`` — T = конец торговой сессии (как в статье: спред и перекос
        по запасу сужаются к закрытию);
        ``rolling`` — постоянный горизонт ``horizon_seconds`` (скользящее окно);
        ``infinite`` — стационарный вариант с ограничением |q| ≤ q_max.
    inventory_skew=False даёт «симметричную» стратегию из статьи: тот же
    оптимальный спред, но вокруг mid, без учёта запаса.
    """

    name = "as"

    def __init__(
        self,
        gamma: float = 0.01,
        order_size: int = 1,
        horizon: str = "session",
        horizon_seconds: float = 3600.0,
        inventory_skew: bool = True,
    ):
        super().__init__(order_size)
        if gamma <= 0:
            raise ValueError("gamma должна быть > 0")
        if horizon not in ("session", "rolling", "infinite"):
            raise ValueError("horizon: session | rolling | infinite")
        self.gamma = float(gamma)
        self.horizon = horizon
        self.horizon_seconds = float(horizon_seconds)
        self.inventory_skew = inventory_skew
        if not inventory_skew:
            self.name = "as_symmetric"

    def label(self) -> str:
        base = "AS" if self.inventory_skew else "AS-sym"
        return f"{base}(γ={self.gamma:g}, {self.horizon})"

    def quote(self, s: MarketState) -> Quote:
        q = self.units(s) if self.inventory_skew else 0.0
        if self.horizon == "infinite":
            q_max = max(1.0, s.max_inventory / self.order_size)
            bid, ask, r, _ = AS.infinite_horizon_quotes(s.mid, q, self.gamma, s.sigma, s.k, q_max)
            return Quote(float(bid), float(ask), float(r))
        tau = s.tau if self.horizon == "session" else self.horizon_seconds
        bid, ask, r, _ = AS.quotes(s.mid, q, self.gamma, s.sigma, tau, s.k)
        return Quote(float(bid), float(ask), float(r))


class GLFT(Strategy):
    """GLFT: асимптотическая замкнутая формула (стационарные котировки)."""

    name = "glft"

    def __init__(self, gamma: float = 0.01, order_size: int = 1):
        super().__init__(order_size)
        self.gamma = float(gamma)

    def label(self) -> str:
        return f"GLFT(γ={self.gamma:g})"

    def quote(self, s: MarketState) -> Quote:
        bid, ask, r, _ = glft.asymptotic_quotes(s.mid, self.units(s), self.gamma, s.sigma, s.A, s.k)
        return Quote(float(bid), float(ask), float(r))


class GLFTExact(Strategy):
    """GLFT: точное решение конечного горизонта (до конца сессии) с |q| ≤ Q.

    Решатель пересобирается при изменении параметров (σ, A, k) — обычно раз в
    сессию при walk-forward калибровке, либо при EWMA-оценке σ с шагом
    ``resolve_tolerance`` (относительное изменение σ).
    """

    name = "glft_exact"

    def __init__(self, gamma: float = 0.01, order_size: int = 1, terminal_penalty: float = 0.0, resolve_tolerance: float = 0.05):
        super().__init__(order_size)
        self.gamma = float(gamma)
        self.terminal_penalty = float(terminal_penalty)
        self.resolve_tolerance = float(resolve_tolerance)
        self._solver: glft.GLFTSolver | None = None
        self._key: tuple | None = None

    def label(self) -> str:
        return f"GLFT-exact(γ={self.gamma:g})"

    def _get_solver(self, s: MarketState) -> glft.GLFTSolver:
        Q = max(1, s.max_inventory // self.order_size)
        key = (s.sigma, s.A, s.k, Q)
        if self._key is not None:
            same = (
                self._key[1:] == key[1:]
                and abs(self._key[0] - key[0]) <= self.resolve_tolerance * self._key[0]
            )
            if same:
                return self._solver  # type: ignore[return-value]
        self._solver = glft.GLFTSolver(self.gamma, s.sigma, s.A, s.k, Q, self.terminal_penalty)
        self._key = key
        return self._solver

    def quote(self, s: MarketState) -> Quote:
        solver = self._get_solver(s)
        q = int(round(self.units(s)))
        bid, ask, r, _ = solver.quotes(s.mid, q, s.tau)
        return Quote(None if np.isnan(bid) else float(bid), None if np.isnan(ask) else float(ask), float(r))


class FixedSpread(Strategy):
    """Базовый бенчмарк: фиксированный полуспред вокруг mid, опционально линейный перекос."""

    name = "fixed"

    def __init__(self, half_spread_ticks: float = 5.0, order_size: int = 1, skew_ticks_per_unit: float = 0.0):
        super().__init__(order_size)
        self.half_spread_ticks = float(half_spread_ticks)
        self.skew_ticks_per_unit = float(skew_ticks_per_unit)

    def label(self) -> str:
        skew = f", skew={self.skew_ticks_per_unit:g}" if self.skew_ticks_per_unit else ""
        return f"Fixed({self.half_spread_ticks:g} тик{skew})"

    def quote(self, s: MarketState) -> Quote:
        r = s.mid - self.skew_ticks_per_unit * self.units(s) * s.tick
        h = self.half_spread_ticks * s.tick
        return Quote(r - h, r + h, r)


STRATEGIES = {
    "as": AvellanedaStoikov,
    "as_symmetric": lambda **kw: AvellanedaStoikov(inventory_skew=False, **kw),
    "glft": GLFT,
    "glft_exact": GLFTExact,
    "fixed": FixedSpread,
}


_SIGNATURE_OF = {"as_symmetric": AvellanedaStoikov}


def make_strategy(name: str, **params) -> Strategy:
    """Создаёт стратегию по имени; параметры, которых у неё нет, игнорируются."""
    try:
        factory = STRATEGIES[name]
    except KeyError:
        raise ValueError(f"Неизвестная стратегия '{name}'. Доступны: {', '.join(STRATEGIES)}") from None
    accepted = inspect.signature(_SIGNATURE_OF.get(name, factory)).parameters
    kwargs = {k: v for k, v in params.items() if k in accepted and v is not None}
    if name == "as_symmetric":
        kwargs.pop("inventory_skew", None)
    return factory(**kwargs)
