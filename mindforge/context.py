"""Общий контекст приложения, доступный всем экранам."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor

from .progress import Achievement, Progress
from .sound import SoundEngine
from .speech import Speech
from .storage import Storage


class AppContext(QObject):
    data_changed = Signal()  # результаты/XP/карточки изменились
    theme_changed = Signal()

    def __init__(self, storage: Storage) -> None:
        super().__init__()
        self.storage = storage
        self.progress = Progress(storage)
        self.sound = SoundEngine(
            enabled=bool(storage.get("settings.sound", True)),
            volume=float(storage.get("settings.volume", 0.7)),
        )
        self.speech = Speech()
        self.window = None  # MainWindow, выставляется позднее

    def setting(self, key: str, default: Any = None) -> Any:
        return self.storage.get(f"settings.{key}", default)

    def set_setting(self, key: str, value: Any) -> None:
        self.storage.set(f"settings.{key}", value)

    def toast(self, title: str, text: str, icon_name: str = "award", color: QColor | None = None) -> None:
        if self.window is not None:
            from .widgets.common import Toast

            Toast(self.window.centralWidget(), title, text, icon_name, color)

    def announce_achievements(self, achs: list[Achievement]) -> None:
        for a in achs:
            self.toast("Достижение открыто!", f"{a.title} — {a.description}", a.icon)
            self.sound.play("levelup")
