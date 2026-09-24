"""Блоки Корси — зрительно-пространственная последовательность."""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ..core import GameResult, linear_rating, plural
from ..theme import T, mix
from ..widgets.common import Hearts
from .base import GameContext, GameWidget, draw_cell, draw_text

LIVES = 3
MAX_SPAN = 11


def make_layout(n: int, rng: random.Random, min_dist: float = 0.21, tries: int = 4000) -> list[tuple[float, float]]:
    """Случайные позиции центров блоков в единичном квадрате без пересечений."""
    for dist in (min_dist, min_dist * 0.9, min_dist * 0.8, min_dist * 0.7):
        pts: list[tuple[float, float]] = []
        for _ in range(tries):
            x, y = rng.uniform(0.08, 0.92), rng.uniform(0.08, 0.92)
            if all(math.hypot(x - a, y - b) >= dist for a, b in pts):
                pts.append((x, y))
                if len(pts) == n:
                    return pts
    # запасной вариант — сетка
    side = math.ceil(math.sqrt(n))
    return [((i % side + 0.5) / side, (i // side + 0.5) / side) for i in range(n)]


def make_sequence(length: int, n_blocks: int, rng: random.Random) -> list[int]:
    return rng.sample(range(n_blocks), length)


def blocks_for(length: int) -> int:
    return 9 if length <= 8 else 12


class CorsiBoard(QWidget):
    clicked_block = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.layout_pts: list[tuple[float, float]] = []
        self.lit: set[int] = set()
        self.lit_color: QColor | None = None
        self.interactive = False
        self.setMinimumSize(360, 320)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def block_rects(self) -> list[QRectF]:
        side = min(self.width(), self.height()) - 20
        ox = (self.width() - side) / 2
        oy = (self.height() - side) / 2
        size = side * (0.145 if len(self.layout_pts) <= 9 else 0.12)
        return [
            QRectF(ox + x * side - size / 2, oy + y * side - size / 2, size, size) for x, y in self.layout_pts
        ]

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i, r in enumerate(self.block_rects()):
            if i in self.lit:
                col = QColor(self.lit_color or T.domain("spatial"))
                glow = QColor(col)
                glow.setAlpha(80)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(glow)
                p.drawRoundedRect(r.adjusted(-6, -6, 6, 6), 16, 16)
                draw_cell(p, r, col, mix(col, QColor("white"), 0.4), 12, 2)
            else:
                draw_cell(p, r, T.c("cell"), T.c("border"), 12)

    def mousePressEvent(self, e) -> None:
        if not self.interactive:
            return
        pos = e.position()
        for i, r in enumerate(self.block_rects()):
            if r.adjusted(-4, -4, 4, 4).contains(pos):
                self.clicked_block.emit(i)
                return


class CorsiGame(GameWidget):
    game_id = "corsi"

    def __init__(self, ctx: GameContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.mode = ctx.options.get("mode", "forward")
        self.length = max(2, min(MAX_SPAN, self.level))
        self.start_len = self.length
        self.lives = LIVES
        self.best = 0
        self.trials = 0
        self.correct = 0
        self.seq: list[int] = []
        self.pos = 0
        self.board = CorsiBoard()
        self.board.clicked_block.connect(self.on_click)
        self.hearts = Hearts(LIVES)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 8, 24, 24)
        top = QHBoxLayout()
        top.addStretch(1)
        top.addWidget(self.hearts)
        lay.addLayout(top)
        lay.addWidget(self.board, 1)
        self._n_blocks = 0

    def start(self) -> None:
        self.new_trial()

    def new_trial(self) -> None:
        nb = blocks_for(self.length)
        if nb != self._n_blocks:
            self._n_blocks = nb
            self.board.layout_pts = make_layout(nb, self.rng)
        self.seq = make_sequence(self.length, nb, self.rng)
        self.pos = 0
        self.board.interactive = False
        self.board.lit = set()
        self.board.update()
        self.set_hud(f"Длина: {self.length}", "Смотрите…")
        self._show_i = 0
        self.after(800, self._show_next)

    def _show_next(self) -> None:
        if self._show_i >= len(self.seq):
            self.board.lit = set()
            self.board.update()
            self.board.interactive = True
            self.set_hud(right="Обратный порядок!" if self.mode == "backward" else "Ваш ход")
            self.play("go")
            return
        self.board.lit = {self.seq[self._show_i]}
        self.board.lit_color = None
        self.board.update()
        self.play(f"tone{self._show_i % 8}")
        self._show_i += 1
        self.after(650, self._dim)

    def _dim(self) -> None:
        self.board.lit = set()
        self.board.update()
        self.after(280, self._show_next)

    def target_order(self) -> list[int]:
        return list(reversed(self.seq)) if self.mode == "backward" else self.seq

    def on_click(self, block: int) -> None:
        if not self.board.interactive:
            return
        target = self.target_order()
        if block == target[self.pos]:
            self.pos += 1
            self.board.lit = {block}
            self.board.lit_color = None
            self.board.update()
            self.play("click")
            self.after(180, self._unlit)
            if self.pos == len(target):
                self.board.interactive = False
                self.trials += 1
                self.correct += 1
                self.best = max(self.best, self.length)
                self.feedback(True)
                self.length = min(MAX_SPAN, self.length + 1)
                if self.best >= MAX_SPAN:
                    self.after(800, self._finish)
                else:
                    self.after(900, self.new_trial)
        else:
            self.board.interactive = False
            self.trials += 1
            self.lives -= 1
            self.hearts.set_left(self.lives)
            self.feedback(False)
            self.board.lit = {block}
            self.board.lit_color = T.c("danger")
            self.board.update()
            self.set_hud(right="Ошибка")
            if self.lives <= 0:
                self.after(1100, self._finish)
            else:
                self.after(1100, self.new_trial)

    def _unlit(self) -> None:
        if self.board.interactive or self.pos:
            self.board.lit = set()
            self.board.update()

    def _finish(self) -> None:
        span = self.best
        nl = max(2, span) if span else max(2, self.start_len - 1)
        rating = linear_rating(span, 2, 9) if self.mode == "forward" else linear_rating(span, 2, 8)
        self.finish(
            GameResult(
                game=self.game_id,
                score=span * 10 + self.correct,
                rating=rating,
                level=self.start_len,
                next_level=nl,
                accuracy=self.correct / self.trials if self.trials else 0.0,
                metrics={
                    "span": span,
                    "mode": self.mode,
                    "trials": self.trials,
                    "headline": f"{span} {plural(span, 'блок', 'блока', 'блоков')}",
                    "rows": [
                        ["Максимальная последовательность", str(span)],
                        ["Порядок", "Обратный" if self.mode == "backward" else "Прямой"],
                        ["Верных попыток", f"{self.correct} из {self.trials}"],
                    ],
                    "note": "Типичный результат взрослого — 5–6 блоков.",
                },
            )
        )

    def on_force_finish(self) -> None:
        self._alive = True
        self._finish()


__all__ = ["CorsiGame", "make_layout", "make_sequence", "QFont", "QPointF", "draw_text"]
