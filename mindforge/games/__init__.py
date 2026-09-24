"""Реестр виджетов упражнений."""
from __future__ import annotations

from .base import GameContext, GameWidget
from .corsi import CorsiGame
from .digit_span import DigitSpanGame
from .math_sprint import MathGame
from .matrix import MatrixGame
from .nback import NBackGame
from .raven import RavenGame
from .rotation import RotationGame
from .schulte import SchulteGame
from .search import SearchGame
from .series import SeriesGame
from .speed_match import SpeedMatchGame
from .stroop import StroopGame
from .switch import SwitchGame
from .words import WordsGame

GAME_WIDGETS: dict[str, type[GameWidget]] = {
    cls.game_id: cls
    for cls in (
        NBackGame,
        DigitSpanGame,
        WordsGame,
        MatrixGame,
        CorsiGame,
        RotationGame,
        SchulteGame,
        SearchGame,
        StroopGame,
        SwitchGame,
        MathGame,
        SpeedMatchGame,
        SeriesGame,
        RavenGame,
    )
}

GAME_ICONS = {
    "nback": "brain",
    "digit_span": "hash",
    "words": "book",
    "matrix": "grid",
    "corsi": "cube",
    "rotation": "rotate",
    "schulte": "table",
    "search": "search",
    "stroop": "palette",
    "switch": "shuffle",
    "math": "calc",
    "speed_match": "bolt",
    "series": "trend",
    "raven": "puzzle",
}

__all__ = ["GAME_WIDGETS", "GAME_ICONS", "GameContext", "GameWidget"]
