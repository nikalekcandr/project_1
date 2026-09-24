"""Таблицы Шульте."""
from __future__ import annotations

import random

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..core import GameResult, linear_rating
from ..theme import T, mix
from .base import GameContext, GameWidget, draw_cell, draw_text, square_board

MODE_FACTOR = {"classic": 1.0, "hidden": 1.1, "chaos": 1.25}


def make_table(size: int, rng: random.Random) -> list[int]:
    nums = list(range(1, size * size + 1))
    rng.shuffle(nums)
    return nums


def schulte_rating(time_s: float, errors: int, size: int, mode: str) -> float:
    cells = size * size
    tpc = (time_s + 1.5 * errors) / cells
    tpc /= 1 + 0.08 * (size - 5)
    tpc /= MODE_FACTOR.get(mode, 1.0)
    return linear_rating(tpc, 2.8, 0.7)


class SchulteBoard(QWidget):
    clicked_cell = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.size_n = 5
        self.numbers: list[int] = []
        self.found_upto = 0
        self.hide_found = False
        self.wrong_cell: int | None = None
        self.hover = -1
        self.setMouseTracking(True)
        self.setMinimumSize(340, 340)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def rects(self) -> list[QRectF]:
        side = min(self.width(), self.height())
        area = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        cells, _ = square_board(area, self.size_n, self.size_n, margin=4, gap_frac=0.07)
        return cells

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rects = self.rects()
        if not rects:
            return
        for i, r in enumerate(rects):
            num = self.numbers[i] if i < len(self.numbers) else 0
            done = num <= self.found_upto and not self.hide_found
            bg = T.c("cell_hover") if i == self.hover else T.c("cell")
            border = T.c("border")
            if i == self.wrong_cell:
                bg = mix(bg, T.c("danger"), 0.5)
                border = T.c("danger")
            if done:
                bg = mix(T.c("surface"), T.domain("attention"), 0.12)
            draw_cell(p, r, bg, border, r.width() * 0.14)
            col = T.c("faint") if done else T.c("text")
            draw_text(p, r, str(num), r.height() * 0.38, col, QFont.Weight.DemiBold)
        if self.size_n % 2 == 0:
            # точка фиксации взгляда на пересечении центральных клеток
            first, last = rects[0], rects[-1]
            c = QRectF(first.topLeft(), last.bottomRight()).center()
            p.setPen(Qt.PenStyle.NoPen)
            dot = QColor(T.domain("attention"))
            dot.setAlpha(200)
            p.setBrush(dot)
            p.drawEllipse(c, 4, 4)

    def mouseMoveEvent(self, e) -> None:
        idx = -1
        for i, r in enumerate(self.rects()):
            if r.contains(e.position()):
                idx = i
                break
        if idx != self.hover:
            self.hover = idx
            self.update()

    def leaveEvent(self, e) -> None:
        self.hover = -1
        self.update()

    def mousePressEvent(self, e) -> None:
        for i, r in enumerate(self.rects()):
            if r.contains(e.position()):
                self.clicked_cell.emit(i)
                return


class SchulteGame(GameWidget):
    game_id = "schulte"

    def __init__(self, ctx: GameContext, parent=None) -> None:
        super().__init__(ctx, parent)
        try:
            self.size_n = max(3, min(7, int(ctx.options.get("size", "5"))))
        except ValueError:
            self.size_n = 5
        self.mode = ctx.options.get("mode", "classic")
        self.total = self.size_n ** 2
        self.next_num = 1
        self.errors = 0
        self.board = SchulteBoard()
        self.board.size_n = self.size_n
        self.board.numbers = make_table(self.size_n, self.rng)
        self.board.hide_found = self.mode == "hidden"
        self.board.clicked_cell.connect(self.on_cell)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 8, 24, 24)
        lay.addWidget(self.board, 1)
        self._t0 = 0.0

    def start(self) -> None:
        self._t0 = self.elapsed()
        self.every(100, self._tick)
        self._update_hud()

    def _tick(self) -> None:
        t = self.elapsed() - self._t0
        self.set_hud(right=f"{t:.1f} с")

    def _update_hud(self) -> None:
        self.set_hud(f"Найдите: {self.next_num}" if self.next_num <= self.total else "Готово!")
        self.progress_changed.emit((self.next_num - 1) / self.total)

    def on_cell(self, i: int) -> None:
        if not self.alive:
            return
        num = self.board.numbers[i]
        if num == self.next_num:
            self.board.found_upto = num
            self.next_num += 1
            self.board.wrong_cell = None
            self.play("click")
            if self.mode == "chaos" and self.next_num <= self.total:
                self.rng.shuffle(self.board.numbers)
            self._update_hud()
            if self.next_num > self.total:
                self._finish()
        elif num > self.board.found_upto or self.mode == "hidden":
            self.errors += 1
            self.board.wrong_cell = i
            self.play("wrong")
            self.after(250, self._clear_wrong)
        self.board.update()

    def _clear_wrong(self) -> None:
        self.board.wrong_cell = None
        self.board.update()

    def _finish(self) -> None:
        t = max(0.1, self.elapsed() - self._t0)
        found = self.next_num - 1
        complete = found >= self.total
        rating = schulte_rating(t, self.errors, self.size_n, self.mode) if complete else 0.0
        acc = found / (found + self.errors) if found + self.errors else 0.0
        mode_name = {"classic": "Классика", "hidden": "Без подсказок", "chaos": "Хаос"}.get(self.mode, self.mode)
        self.finish(
            GameResult(
                game=self.game_id,
                score=round(found / t * 60),
                rating=rating,
                level=1,
                next_level=1,
                accuracy=acc,
                duration=round(t, 1),
                metrics={
                    "size": self.size_n,
                    "mode": self.mode,
                    "time": round(t, 2),
                    "errors": self.errors,
                    "trials": found,
                    "headline": f"{t:.1f} с · {self.size_n}×{self.size_n}",
                    "rows": [
                        ["Время", f"{t:.1f} с"],
                        ["Таблица", f"{self.size_n}×{self.size_n} · {mode_name}"],
                        ["Ошибок", str(self.errors)],
                        ["Скорость", f"{found / t * 60:.0f} чисел/мин"],
                    ],
                    "note": "Норма для 5×5: 35–45 с. Меньше 25 с — отличный результат.",
                },
            )
        )

    def on_force_finish(self) -> None:
        self._alive = True
        self._finish()


__all__ = ["SchulteGame", "make_table", "schulte_rating"]
