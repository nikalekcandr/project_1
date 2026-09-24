"""Визуальная память: восстановить подсвеченный узор."""
from __future__ import annotations

import random

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ..core import GameResult, linear_rating
from ..theme import T, mix
from ..widgets.common import Hearts
from .base import GameContext, GameWidget, draw_cell, square_board

LIVES = 3
MAX_WRONG = 3


def grid_size(level: int) -> int:
    return min(8, 3 + level // 3)


def cell_count(level: int) -> int:
    return min(level + 2, grid_size(level) ** 2 - 2)


def make_pattern(level: int, rng: random.Random) -> set[int]:
    g = grid_size(level)
    return set(rng.sample(range(g * g), cell_count(level)))


class MatrixBoard(QWidget):
    clicked_cell = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.size_n = 3
        self.shown: set[int] = set()
        self.found: set[int] = set()
        self.wrong: set[int] = set()
        self.missed: set[int] = set()
        self.interactive = False
        self.setMinimumSize(320, 320)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def rects(self) -> list[QRectF]:
        side = min(self.width(), self.height())
        area = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        cells, _ = square_board(area, self.size_n, self.size_n, margin=6, gap_frac=0.1)
        return cells

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = T.domain("memory")
        for i, r in enumerate(self.rects()):
            if i in self.shown or i in self.found:
                draw_cell(p, r, accent, mix(accent, QColor("white"), 0.35), None, 2)
            elif i in self.wrong:
                draw_cell(p, r, mix(T.c("cell"), T.c("danger"), 0.55), T.c("danger"), None, 2)
            elif i in self.missed:
                draw_cell(p, r, T.c("cell"), accent, None, 2.5)
            else:
                draw_cell(p, r, T.c("cell"), T.c("border"))

    def mousePressEvent(self, e) -> None:
        if not self.interactive:
            return
        for i, r in enumerate(self.rects()):
            if r.contains(e.position()):
                self.clicked_cell.emit(i)
                return


class MatrixGame(GameWidget):
    game_id = "matrix"

    def __init__(self, ctx: GameContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.cur = max(1, self.level)
        self.start_level = self.cur
        self.reached = 0
        self.lives = LIVES
        self.rounds = 0
        self.perfect_rounds = 0
        self.total_wrong = 0
        self.pattern: set[int] = set()
        self.wrong_in_round = 0
        self.board = MatrixBoard()
        self.board.clicked_cell.connect(self.on_cell)
        self.hearts = Hearts(LIVES)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 8, 24, 24)
        top = QHBoxLayout()
        top.addStretch(1)
        top.addWidget(self.hearts)
        lay.addLayout(top)
        lay.addWidget(self.board, 1)

    def start(self) -> None:
        self.new_round()

    def new_round(self) -> None:
        self.pattern = make_pattern(self.cur, self.rng)
        self.wrong_in_round = 0
        b = self.board
        b.size_n = grid_size(self.cur)
        b.found, b.wrong, b.missed = set(), set(), set()
        b.shown = set()
        b.interactive = False
        b.update()
        self.set_hud(f"Уровень {self.cur}", f"Клеток: {len(self.pattern)}")
        self.after(500, self._show)

    def _show(self) -> None:
        self.board.shown = set(self.pattern)
        self.board.update()
        self.play("flip")
        self.after(900 + 60 * len(self.pattern), self._hide)

    def _hide(self) -> None:
        self.board.shown = set()
        self.board.interactive = True
        self.board.update()

    def on_cell(self, i: int) -> None:
        b = self.board
        if not b.interactive or i in b.found or i in b.wrong:
            return
        if i in self.pattern:
            b.found.add(i)
            self.play("click")
            if b.found == self.pattern:
                b.interactive = False
                self.rounds += 1
                if self.wrong_in_round == 0:
                    self.perfect_rounds += 1
                self.reached = max(self.reached, self.cur)
                self.feedback(True)
                self.cur += 1
                self.after(700, self.new_round)
        else:
            b.wrong.add(i)
            self.wrong_in_round += 1
            self.total_wrong += 1
            self.play("wrong")
            if self.wrong_in_round >= MAX_WRONG:
                b.interactive = False
                b.missed = self.pattern - b.found
                self.rounds += 1
                self.lives -= 1
                self.hearts.set_left(self.lives)
                self.feedback(False, sound=False)
                if self.lives <= 0:
                    self.after(1400, self._finish)
                else:
                    self.after(1400, self.new_round)
        b.update()

    def _finish(self) -> None:
        reached = self.reached
        nl = max(1, reached - 2) if reached else max(1, self.start_level - 2)
        self.finish(
            GameResult(
                game=self.game_id,
                score=reached * 10 + self.perfect_rounds * 2,
                rating=linear_rating(reached, 1, 16),
                level=self.start_level,
                next_level=nl,
                accuracy=self.perfect_rounds / self.rounds if self.rounds else 0.0,
                metrics={
                    "reached": reached,
                    "trials": self.rounds,
                    "headline": f"Уровень {reached}",
                    "rows": [
                        ["Пройденный уровень", str(reached)],
                        ["Клеток в последнем узоре", str(cell_count(reached)) if reached else "—"],
                        ["Раундов без ошибок", f"{self.perfect_rounds} из {self.rounds}"],
                        ["Ошибочных кликов", str(self.total_wrong)],
                    ],
                    "note": "Следующая попытка начнётся на пару уровней ниже рекорда — для разминки.",
                },
            )
        )

    def on_force_finish(self) -> None:
        self._alive = True
        self._finish()


__all__ = ["MatrixGame", "grid_size", "cell_count", "make_pattern"]
