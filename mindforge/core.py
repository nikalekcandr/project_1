"""Базовые типы и вспомогательные функции, не зависящие от интерфейса."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

DOMAINS: dict[str, str] = {
    "memory": "Память",
    "attention": "Внимание",
    "speed": "Скорость",
    "logic": "Логика",
    "flexibility": "Гибкость",
    "spatial": "Пространство",
}

DOMAIN_HINTS: dict[str, str] = {
    "memory": "Удержание и воспроизведение информации: рабочая и кратковременная память.",
    "attention": "Концентрация, поиск и устойчивость внимания.",
    "speed": "Скорость обработки информации и реакции.",
    "logic": "Абстрактное мышление и поиск закономерностей (подвижный интеллект).",
    "flexibility": "Переключение между правилами и подавление автоматических реакций.",
    "spatial": "Работа с образами, формой и положением объектов в пространстве.",
}


def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def linear_rating(value: float, worst: float, best: float) -> float:
    """Переводит показатель в шкалу 0–100 (работает и когда «меньше — лучше»)."""
    if best == worst:
        return 0.0
    return clamp((value - worst) / (best - worst) * 100.0)


@dataclass
class GameResult:
    game: str
    score: float
    rating: float  # 0..100 — нормированная оценка для когнитивного профиля
    level: int  # уровень, на котором прошла сессия
    next_level: int  # уровень для следующей сессии
    accuracy: float | None = None  # 0..1
    duration: float = 0.0  # секунды
    metrics: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.rating = round(clamp(self.rating), 1)
        if self.accuracy is not None:
            self.accuracy = max(0.0, min(1.0, self.accuracy))


def fmt_seconds(sec: float) -> str:
    sec = max(0, int(round(sec)))
    return f"{sec // 60}:{sec % 60:02d}"


def fmt_duration_long(sec: float) -> str:
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m = rem // 60
    if h:
        return f"{h} ч {m} мин"
    if m:
        return f"{m} мин"
    return f"{sec} с"


def plural(n: int, one: str, few: str, many: str) -> str:
    """Русское склонение по числу: plural(5, 'день', 'дня', 'дней')."""
    n_abs = abs(n)
    if n_abs % 10 == 1 and n_abs % 100 != 11:
        return one
    if 2 <= n_abs % 10 <= 4 and not 12 <= n_abs % 100 <= 14:
        return few
    return many


def pct(x: float | None) -> str:
    return "—" if x is None else f"{round(x * 100)}%"
