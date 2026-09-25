"""Торговые сессии фондового рынка Московской биржи (время московское).

Границы сессий периодически меняются биржей, поэтому их можно переопределить в
конфигурации (``[sessions] custom = {main = ["10:00", "18:40"]}``). По умолчанию
симулируется только основная сессия непрерывных торгов, без аукционов открытия
и закрытия: в аукционах маркет-мейкер не котирует в привычном смысле.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

import numpy as np
import pandas as pd

DEFAULT_SESSIONS: dict[str, tuple[str, str]] = {
    "morning": ("07:00", "09:50"),
    "main": ("10:00", "18:40"),
    "evening": ("19:05", "23:50"),
}


@dataclass(frozen=True)
class Session:
    name: str
    start: time
    end: time

    @property
    def seconds(self) -> float:
        return (self.end.hour * 3600 + self.end.minute * 60 + self.end.second) - (
            self.start.hour * 3600 + self.start.minute * 60 + self.start.second
        )


def _parse(t: str) -> time:
    parts = [int(x) for x in t.split(":")]
    while len(parts) < 3:
        parts.append(0)
    return time(*parts)


def resolve_sessions(use: list[str], custom: dict[str, list[str]] | None = None) -> list[Session]:
    table = {**DEFAULT_SESSIONS, **{k: tuple(v) for k, v in (custom or {}).items()}}
    out = []
    for name in use:
        if name not in table:
            raise ValueError(f"Неизвестная сессия '{name}'. Доступны: {', '.join(table)}")
        start, end = table[name]
        out.append(Session(name, _parse(start), _parse(end)))
    return sorted(out, key=lambda s: s.start)


def assign_sessions(index: pd.DatetimeIndex, sessions: list[Session], bar_seconds: float) -> pd.DataFrame:
    """Сопоставляет барам торговую сессию.

    Бар относится к сессии, если он целиком помещается в её интервал. Возвращает
    таблицу с колонками ``session`` (имя или пусто), ``session_id`` (уникальный
    номер «дата+сессия»), ``session_end`` (момент окончания сессии).
    """
    idx = pd.DatetimeIndex(index)
    tod = (idx.hour * 3600 + idx.minute * 60 + idx.second).to_numpy()
    days = idx.normalize()
    name = np.full(len(idx), "", dtype=object)
    end = np.full(len(idx), np.datetime64("NaT"), dtype="datetime64[ns]")
    for s in sessions:
        s0 = s.start.hour * 3600 + s.start.minute * 60 + s.start.second
        s1 = s.end.hour * 3600 + s.end.minute * 60 + s.end.second
        mask = (tod >= s0) & (tod + bar_seconds <= s1 + 1e-9)
        name[mask] = s.name
        end[mask] = (days[mask] + pd.to_timedelta(s1, unit="s")).to_numpy()
    df = pd.DataFrame({"session": name, "session_end": end}, index=idx)
    key = pd.Series(days.strftime("%Y-%m-%d"), index=idx) + "/" + df["session"].astype(str)
    df["session_id"] = pd.factorize(key)[0]
    df.loc[df["session"] == "", "session_id"] = -1
    return df
