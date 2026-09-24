"""Базовый класс упражнения и общие элементы игрового поля."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QElapsedTimer, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..core import GameResult
from ..sound import SoundEngine
from ..speech import Speech
from ..theme import T, font, mix
from ..widgets.common import FeedbackFlash


@dataclass
class GameContext:
    level: int = 1
    options: dict = field(default_factory=dict)
    sound: SoundEngine | None = None
    speech: Speech | None = None
    rng: random.Random = field(default_factory=random.Random)
    fast: bool = False  # ускоренный режим для автотестов


class GameWidget(QWidget):
    finished = Signal(object)  # GameResult
    hud_changed = Signal(str, str)  # (слева, справа)
    progress_changed = Signal(float)  # 0..1, либо -1 чтобы скрыть

    game_id = "base"

    def __init__(self, ctx: GameContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.level = max(1, int(ctx.level))
        self.rng = ctx.rng
        self._timers: list[QTimer] = []
        self._alive = False
        self._done = False
        self._clock = QElapsedTimer()
        self._started_wall = 0.0
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.flash_fx = FeedbackFlash(self)
        self._hud = ("", "")

    # ------------------------------------------------------------ таймеры
    def ms(self, value: int) -> int:
        """Длительности сокращаются в тестовом режиме."""
        return max(1, value // 25) if self.ctx.fast else value

    def after(self, ms: int, fn) -> QTimer:
        t = QTimer(self)
        t.setSingleShot(True)

        def fire() -> None:
            if t in self._timers:
                self._timers.remove(t)
            if self._alive:
                fn()

        t.timeout.connect(fire)
        t.start(self.ms(ms))
        self._timers.append(t)
        return t

    def every(self, ms: int, fn) -> QTimer:
        t = QTimer(self)
        t.timeout.connect(lambda: self._alive and fn())
        t.start(ms)
        self._timers.append(t)
        return t

    def cancel(self, t: QTimer | None) -> None:
        if t is not None:
            t.stop()
            if t in self._timers:
                self._timers.remove(t)

    def stop_all(self) -> None:
        for t in self._timers:
            t.stop()
        self._timers.clear()

    # ------------------------------------------------------ жизненный цикл
    def begin(self) -> None:
        self._alive = True
        self._clock.start()
        self._started_wall = time.time()
        self.setFocus()
        self.start()

    def start(self) -> None:  # переопределяется
        raise NotImplementedError

    def abort(self) -> None:
        self._alive = False
        self.stop_all()
        if self.ctx.speech:
            self.ctx.speech.stop()

    def elapsed(self) -> float:
        if not self._clock.isValid():
            return 0.0
        secs = self._clock.elapsed() / 1000.0
        return secs * 25 if self.ctx.fast else secs

    def finish(self, result: GameResult) -> None:
        if self._done:
            return
        self._done = True
        self._alive = False
        self.stop_all()
        if not result.duration:
            result.duration = round(self.elapsed(), 1)
        self.play("finish")
        self.finished.emit(result)

    def force_finish(self) -> None:
        """Завершить досрочно (используется в тестах и при нехватке времени)."""
        self.on_force_finish()

    def on_force_finish(self) -> None:
        raise NotImplementedError

    @property
    def alive(self) -> bool:
        return self._alive

    # --------------------------------------------------------------- прочее
    def play(self, name: str) -> None:
        if self.ctx.sound:
            self.ctx.sound.play(name)

    def feedback(self, good: bool, sound: bool = True) -> None:
        self.flash_fx.flash(good)
        if sound:
            self.play("correct" if good else "wrong")

    def set_hud(self, left: str | None = None, right: str | None = None) -> None:
        self._hud = (self._hud[0] if left is None else left, self._hud[1] if right is None else right)
        self.hud_changed.emit(*self._hud)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.flash_fx.setGeometry(self.rect())


class Countdown:
    """Обратный отсчёт внутри упражнения (обновляет HUD справа)."""

    def __init__(self, game: GameWidget, seconds: float, on_timeout, prefix: str = "") -> None:
        self.game = game
        self.total = seconds
        self.on_timeout = on_timeout
        self.prefix = prefix
        self._start = game.elapsed()
        self._timer = game.every(100, self._tick)
        self._tick()

    def left(self) -> float:
        return max(0.0, self.total - (self.game.elapsed() - self._start))

    def _tick(self) -> None:
        left = self.left()
        sec = int(left + 0.999)
        self.game.set_hud(right=f"{self.prefix}{sec // 60}:{sec % 60:02d}")
        self.game.progress_changed.emit(1 - left / self.total if self.total else 1)
        if left <= 0:
            self.stop()
            self.on_timeout()

    def stop(self) -> None:
        self.game.cancel(self._timer)


# ------------------------------------------------------------------ отрисовка
def draw_cell(p: QPainter, r: QRectF, fill: QColor, border: QColor | None = None, radius: float | None = None,
              width: float = 1.2) -> None:
    rad = radius if radius is not None else min(r.width(), r.height()) * 0.18
    p.setPen(QPen(border, width) if border is not None else Qt.PenStyle.NoPen)
    p.setBrush(fill)
    p.drawRoundedRect(r, rad, rad)


def draw_text(p: QPainter, r: QRectF, text: str, px: float, color: QColor, weight=QFont.Weight.Bold,
              align=Qt.AlignmentFlag.AlignCenter, family: str | None = None) -> None:
    f = font(10, weight, family)
    f.setPixelSize(max(6, int(px)))
    p.setFont(f)
    p.setPen(color)
    p.drawText(r, align, text)


def glow_color(base: QColor, t: float = 0.25) -> QColor:
    return mix(base, QColor("#FFFFFF"), t)


def square_board(rect: QRectF, cols: int, rows: int, margin: float = 16, gap_frac: float = 0.12):
    """Возвращает список прямоугольников клеток, вписанных по центру в rect."""
    avail_w = rect.width() - 2 * margin
    avail_h = rect.height() - 2 * margin
    cell = min(avail_w / (cols + (cols - 1) * gap_frac), avail_h / (rows + (rows - 1) * gap_frac))
    gap = cell * gap_frac
    total_w = cols * cell + (cols - 1) * gap
    total_h = rows * cell + (rows - 1) * gap
    x0 = rect.x() + (rect.width() - total_w) / 2
    y0 = rect.y() + (rect.height() - total_h) / 2
    cells = []
    for r in range(rows):
        for c in range(cols):
            cells.append(QRectF(x0 + c * (cell + gap), y0 + r * (cell + gap), cell, cell))
    return cells, QRectF(x0, y0, total_w, total_h)


class BigButton(QWidget):
    """Крупная кнопка ответа с подсказкой клавиши и цветовой обратной связью."""

    clicked = Signal()

    def __init__(self, text: str, key_hint: str = "", swatch: QColor | None = None, parent=None) -> None:
        super().__init__(parent)
        self.text = text
        self.key_hint = key_hint
        self.swatch = swatch
        self.state = "idle"
        self._hover = False
        self._revert: QTimer | None = None
        self.setMinimumSize(120, 64)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(72)

    def set_state(self, state: str, ms: int | None = None) -> None:
        self.state = state
        self.update()
        if self._revert is not None:
            self._revert.stop()
            self._revert = None
        if ms:
            self._revert = QTimer(self)
            self._revert.setSingleShot(True)
            self._revert.timeout.connect(lambda: self.set_state("idle"))
            self._revert.start(ms)

    def enterEvent(self, e) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, e) -> None:
        self._hover = False
        self.update()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.clicked.emit()

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        bg = T.c("surface2") if not self._hover else T.c("surface3")
        border = T.c("border")
        if self.state == "active":
            bg, border = mix(bg, T.c("accent"), 0.35), T.c("accent")
        elif self.state == "good":
            bg, border = mix(bg, T.c("success"), 0.35), T.c("success")
        elif self.state == "bad":
            bg, border = mix(bg, T.c("danger"), 0.35), T.c("danger")
        elif self.state == "miss":
            border = T.c("danger")
        if not self.isEnabled():
            bg = T.c("surface")
        draw_cell(p, r, bg, border, 14, 2 if self.state != "idle" else 1.2)
        x = r.left() + 18
        if self.swatch is not None:
            sw = QRectF(x, r.center().y() - 9, 18, 18)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.swatch)
            p.drawEllipse(sw)
        text_col = T.c("text") if self.isEnabled() else T.c("faint")
        draw_text(p, r, self.text, 17, text_col, QFont.Weight.Bold)
        if self.key_hint:
            f = font(9, QFont.Weight.Bold)
            f.setPixelSize(12)
            p.setFont(f)
            fm_w = max(24, p.fontMetrics().horizontalAdvance(self.key_hint) + 12)
            kr = QRectF(r.right() - fm_w - 12, r.center().y() - 11, fm_w, 22)
            draw_cell(p, kr, T.c("surface"), T.c("border"), 6)
            p.setPen(T.c("muted"))
            p.drawText(kr, Qt.AlignmentFlag.AlignCenter, self.key_hint)


__all__ = [
    "GameContext", "GameWidget", "Countdown", "BigButton", "draw_cell", "draw_text", "glow_color",
    "square_board", "T",
]
