"""Спецификации инструментов Московской биржи.

Позиция в симуляторе всегда хранится в **лотах**. Денежная стоимость изменения
цены на 1 единицу для 1 лота задаётся ``Instrument.multiplier``:

* акции: ``multiplier = lot_size`` (в лоте ``lot_size`` штук, цена за штуку);
* фьючерсы FORTS: ``multiplier = step_price / tick_size`` (цена в пунктах,
  стоимость шага цены в рублях).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Instrument:
    secid: str
    board: str = "TQBR"
    engine: str = "stock"
    market: str = "shares"
    lot_size: int = 1
    tick_size: float = 0.01
    step_price: float | None = None  # стоимость шага цены за лот, руб. (FORTS)
    currency: str = "RUB"
    name: str = ""

    @property
    def multiplier(self) -> float:
        """Рублей за изменение цены на 1 единицу для 1 лота."""
        if self.step_price is not None:
            return self.step_price / self.tick_size
        return float(self.lot_size)

    @property
    def decimals(self) -> int:
        return max(0, -int(math.floor(math.log10(self.tick_size) + 1e-9)))

    def _ticks(self, price: float) -> float:
        return price / self.tick_size

    def round_bid(self, price: float) -> float:
        """Округление цены покупки вниз к шагу цены."""
        return round(math.floor(self._ticks(price) + 1e-9) * self.tick_size, self.decimals + 2)

    def round_ask(self, price: float) -> float:
        """Округление цены продажи вверх к шагу цены."""
        return round(math.ceil(self._ticks(price) - 1e-9) * self.tick_size, self.decimals + 2)

    def round_price(self, price: float) -> float:
        return round(round(self._ticks(price)) * self.tick_size, self.decimals + 2)

    def with_overrides(self, **kwargs) -> "Instrument":
        clean = {k: v for k, v in kwargs.items() if v is not None}
        return replace(self, **clean) if clean else self


# Справочные значения для популярных бумаг режима TQBR. При загрузке с MOEX ISS
# лот и шаг цены всегда берутся из ответа биржи — пресеты нужны для офлайн-режима
# (CSV, синтетика). Проверяйте актуальность: биржа меняет параметры после сплитов.
PRESETS: dict[str, Instrument] = {
    "SBER": Instrument("SBER", lot_size=10, tick_size=0.01, name="Сбербанк ао"),
    "SBERP": Instrument("SBERP", lot_size=10, tick_size=0.01, name="Сбербанк ап"),
    "GAZP": Instrument("GAZP", lot_size=10, tick_size=0.01, name="Газпром ао"),
    "LKOH": Instrument("LKOH", lot_size=1, tick_size=0.5, name="Лукойл ао"),
}


def preset(secid: str, **overrides) -> Instrument:
    """Пресет инструмента (или шаблон по умолчанию) с переопределениями."""
    base = PRESETS.get(secid.upper(), Instrument(secid.upper()))
    return base.with_overrides(**overrides)
