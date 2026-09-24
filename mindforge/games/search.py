"""Зоркий глаз — зрительный поиск отличающегося символа."""
from __future__ import annotations

import random

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..core import GameResult, linear_rating, plural
from ..theme import T, font, mix
from .base import Countdown, GameContext, GameWidget, draw_cell

DURATION = 60
EASY_PAIRS = [("O", "Q"), ("E", "F"), ("P", "R"), ("C", "G"), ("Ш", "Щ"), ("Ь", "Ъ"), ("М", "Н"), ("Т", "Г")]
MID_PAIRS = [("b", "d"), ("p", "q"), ("6", "9"), ("И", "Й"), ("З", "Э"), ("V", "Y"), ("8", "B"), ("Л", "П")]
ROT_GLYPHS = ["F", "R", "Ж", "Я", "G", "Ф", "4", "К"]


def grid_dims(level: int) -> tuple[int, int]:
    cols = min(11, 4 + (level + 1) // 2 + level // 4)
    rows = min(7, 3 + level // 2)
    return cols, rows


def make_round(level: int, rng: random.Random) -> dict:
    cols, rows = grid_dims(level)
    n = cols * rows
    odd = rng.randrange(n)
    if level <= 3:
        a, b = rng.choice(EASY_PAIRS)
        if rng.random() < 0.5:
            a, b = b, a
        return {"cols": cols, "rows": rows, "odd": odd, "base": a, "odd_glyph": b, "rot": 0.0}
    if level <= 7:
        a, b = rng.choice(MID_PAIRS)
        if rng.random() < 0.5:
            a, b = b, a
        return {"cols": cols, "rows": rows, "odd": odd, "base": a, "odd_glyph": b, "rot": 0.0}
    g = rng.choice(ROT_GLYPHS)
    angle = max(10.0, 28.0 - (level - 8) * 4) * rng.choice([-1, 1])
    return {"cols": cols, "rows": rows, "odd": odd, "base": g, "odd_glyph": g, "rot": angle}


def search_rating(points: float) -> float:
    return linear_rating(points, 5, 110)


class SearchBoard(QWidget):
    clicked_cell = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.round: dict | None = None
        self.reveal = False
        self.wrong: int | None = None
        self.setMinimumSize(360, 300)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def rects(self) -> list[QRectF]:
        if not self.round:
            return []
        cols, rows = self.round["cols"], self.round["rows"]
        cell = min((self.width() - 20) / cols, (self.height() - 20) / rows)
        x0 = (self.width() - cell * cols) / 2
        y0 = (self.height() - cell * rows) / 2
        return [QRectF(x0 + (i % cols) * cell, y0 + (i // cols) * cell, cell, cell) for i in range(cols * rows)]

    def paintEvent(self, e) -> None:
        if not self.round:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        rects = self.rects()
        if not rects:
            return
        size = rects[0].width()
        f = font(10, QFont.Weight.DemiBold)
        f.setPixelSize(max(8, int(size * 0.52)))
        p.setFont(f)
        for i, r in enumerate(rects):
            is_odd = i == self.round["odd"]
            if self.reveal and is_odd:
                draw_cell(p, r.adjusted(3, 3, -3, -3), mix(T.c("surface"), T.c("success"), 0.3), T.c("success"), 8, 2)
            elif i == self.wrong:
                draw_cell(p, r.adjusted(3, 3, -3, -3), mix(T.c("surface"), T.c("danger"), 0.3), T.c("danger"), 8, 2)
            glyph = self.round["odd_glyph"] if is_odd else self.round["base"]
            p.setPen(T.c("text"))
            p.save()
            p.translate(r.center())
            if is_odd and self.round["rot"]:
                p.rotate(self.round["rot"])
            p.drawText(QRectF(-size / 2, -size / 2, size, size), Qt.AlignmentFlag.AlignCenter, glyph)
            p.restore()

    def mousePressEvent(self, e) -> None:
        for i, r in enumerate(self.rects()):
            if r.contains(e.position()):
                self.clicked_cell.emit(i)
                return


class SearchGame(GameWidget):
    game_id = "search"

    def __init__(self, ctx: GameContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.cur = max(1, self.level)
        self.start_level = self.cur
        self.max_reached = 0
        self.found = 0
        self.errors = 0
        self.points = 0
        self.streak = 0
        self.board = SearchBoard()
        self.board.clicked_cell.connect(self.on_cell)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 8, 24, 24)
        lay.addWidget(self.board, 1)
        self.locked = False

    def start(self) -> None:
        self.timer = Countdown(self, DURATION, self._finish)
        self.new_round()

    def new_round(self) -> None:
        self.board.round = make_round(self.cur, self.rng)
        self.board.reveal = False
        self.board.wrong = None
        self.locked = False
        self.board.update()
        self.set_hud(f"Уровень {self.cur} · Найдено: {self.found}")

    def on_cell(self, i: int) -> None:
        if not self.alive or self.locked or not self.board.round:
            return
        if i == self.board.round["odd"]:
            self.found += 1
            self.points += self.cur
            self.max_reached = max(self.max_reached, self.cur)
            self.streak += 1
            self.play("correct")
            if self.streak >= 3:
                self.streak = 0
                self.cur = min(12, self.cur + 1)
            self.board.reveal = True
            self.locked = True
            self.board.update()
            self.after(220, self.new_round)
        else:
            self.errors += 1
            self.streak = 0
            self.board.wrong = i
            self.play("wrong")
            self.board.update()
            self.after(300, self._clear_wrong)

    def _clear_wrong(self) -> None:
        self.board.wrong = None
        self.board.update()

    def _finish(self) -> None:
        total = self.found + self.errors
        acc = self.found / total if total else 0.0
        nl = max(1, self.max_reached - 1) if self.max_reached else self.start_level
        self.finish(
            GameResult(
                game=self.game_id,
                score=self.points * 10,
                rating=search_rating(self.points),
                level=self.start_level,
                next_level=nl,
                accuracy=acc,
                metrics={
                    "found": self.found,
                    "errors": self.errors,
                    "reached": self.max_reached,
                    "trials": total,
                    "headline": f"{self.found} {plural(self.found, 'находка', 'находки', 'находок')}",
                    "rows": [
                        ["Найдено", str(self.found)],
                        ["Ошибок", str(self.errors)],
                        ["Максимальный уровень", str(self.max_reached)],
                        ["Точность", f"{round(acc * 100)}%"],
                    ],
                },
            )
        )

    def on_force_finish(self) -> None:
        self._alive = True
        self._finish()


__all__ = ["SearchGame", "make_round", "grid_dims", "search_rating", "QColor", "QPointF"]
