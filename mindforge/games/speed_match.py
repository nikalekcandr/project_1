"""Совпадение — быстрые решения «то же / другое»."""
from __future__ import annotations

import random

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ..core import GameResult, clamp, linear_rating
from ..theme import T, mix
from .base import BigButton, Countdown, GameContext, GameWidget, draw_cell, draw_text
from .shapes import SHAPES, shape_path

DURATION = 45
PALETTE = ["#F472B6", "#60A5FA", "#34D399", "#FBBF24", "#A78BFA", "#F87171", "#22D3EE", "#FB923C"]
SHAPE_COLOR = dict(zip(SHAPES, PALETTE))


def back_distance(level: int) -> int:
    return 2 if level >= 7 else 1


def random_colors(level: int) -> bool:
    return level >= 4


def make_sequence_item(history: list[dict], level: int, rng: random.Random) -> dict:
    k = back_distance(level)
    n_shapes = 5 if level <= 2 else (6 if level <= 5 else 8)
    pool = SHAPES[:n_shapes]
    if len(history) >= k and rng.random() < 0.4:
        shape = history[-k]["shape"]
    else:
        shape = rng.choice(pool)
        if len(history) >= k and shape == history[-k]["shape"]:
            shape = rng.choice([s for s in pool if s != history[-k]["shape"]])
    color = rng.choice(PALETTE) if random_colors(level) else SHAPE_COLOR[shape]
    return {"shape": shape, "color": color}


def is_match(history: list[dict], level: int) -> bool | None:
    k = back_distance(level)
    if len(history) <= k:
        return None
    return history[-1]["shape"] == history[-1 - k]["shape"]


def speed_rating(correct: int, errors: int, seconds: float, level: int) -> float:
    total = correct + errors
    acc = correct / total if total else 0.0
    cpm = correct / max(1.0, seconds) * 60
    return clamp(linear_rating(cpm * acc, 20, 80) + (level - 1) * 1.5)


class CardView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.item: dict | None = None
        self.caption = ""
        self._pop = 1.0
        self.anim = QPropertyAnimation(self, b"pop", self)
        self.anim.setDuration(160)
        self.anim.setEasingCurve(QEasingCurve.Type.OutBack)
        self.setMinimumHeight(260)

    def _get(self) -> float:
        return self._pop

    def _set(self, v: float) -> None:
        self._pop = v
        self.update()

    pop = Property(float, _get, _set)

    def show_item(self, item: dict) -> None:
        self.item = item
        self.anim.stop()
        self.anim.setStartValue(0.75)
        self.anim.setEndValue(1.0)
        self.anim.start()

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        side = min(r.width(), r.height() - 40) * 0.85 * self._pop
        card = QRectF(r.center().x() - side / 2, r.top() + (r.height() - 40 - side) / 2, side, side)
        draw_cell(p, card, T.c("surface"), T.c("border"), 24, 1.5)
        if self.item:
            col = QColor(self.item["color"])
            path = shape_path(self.item["shape"], card.adjusted(side * 0.22, side * 0.22, -side * 0.22, -side * 0.22))
            p.setPen(QPen(mix(col, QColor("white"), 0.25), 3))
            p.setBrush(col)
            p.drawPath(path)
        if self.caption:
            draw_text(p, QRectF(r.left(), r.bottom() - 34, r.width(), 30), self.caption, 15, T.c("muted"),
                      QFont.Weight.DemiBold)


class SpeedMatchGame(GameWidget):
    game_id = "speed_match"

    def __init__(self, ctx: GameContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.history: list[dict] = []
        self.correct = 0
        self.errors = 0
        self.streak = 0
        self.mult = 1
        self.points = 0
        self.best_mult = 1
        self.view = CardView()
        self.btn_no = BigButton("Нет", "←")
        self.btn_yes = BigButton("Да", "→")
        self.btn_no.clicked.connect(lambda: self.answer(False))
        self.btn_yes.clicked.connect(lambda: self.answer(True))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 8, 24, 24)
        lay.setSpacing(16)
        lay.addWidget(self.view, 1)
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addStretch(1)
        for b in (self.btn_no, self.btn_yes):
            b.setMaximumWidth(260)
            row.addWidget(b, 2)
        row.addStretch(1)
        lay.addLayout(row)
        self.k = back_distance(self.level)

    def start(self) -> None:
        self.timer = Countdown(self, DURATION, self._finish)
        self._advance()

    def _advance(self) -> None:
        item = make_sequence_item(self.history, self.level, self.rng)
        self.history.append(item)
        self.view.show_item(item)
        need = is_match(self.history, self.level)
        if need is None:
            self.view.caption = "Запомните фигуру" if self.k == 1 else "Запомните фигуры"
            self.btn_no.setEnabled(False)
            self.btn_yes.setEnabled(False)
            self.after(900, self._advance)
        else:
            self.view.caption = ("Совпадает с предыдущей?" if self.k == 1 else "Совпадает с фигурой 2 шага назад?")
            self.btn_no.setEnabled(True)
            self.btn_yes.setEnabled(True)
        self.btn_no.update()
        self.btn_yes.update()
        self.set_hud(f"Очки: {self.points} · ×{self.mult}")

    def answer(self, yes: bool) -> None:
        if not self.alive:
            return
        need = is_match(self.history, self.level)
        if need is None:
            return
        btn = self.btn_yes if yes else self.btn_no
        if yes == need:
            self.correct += 1
            self.streak += 1
            if self.streak % 4 == 0:
                self.mult = min(5, self.mult + 1)
                self.best_mult = max(self.best_mult, self.mult)
            self.points += 10 * self.mult
            btn.set_state("good", 150)
            self.play("click")
        else:
            self.errors += 1
            self.streak = 0
            self.mult = 1
            btn.set_state("bad", 250)
            self.feedback(False)
        self._advance()

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Left:
            self.answer(False)
        elif e.key() == Qt.Key.Key_Right:
            self.answer(True)
        else:
            super().keyPressEvent(e)

    def _finish(self) -> None:
        total = self.correct + self.errors
        acc = self.correct / total if total else 0.0
        secs = DURATION if not self.ctx.fast else max(1.0, self.elapsed())
        if acc >= 0.9 and self.correct >= 30:
            nl = self.level + 1
        elif acc < 0.75:
            nl = max(1, self.level - 1)
        else:
            nl = self.level
        self.finish(
            GameResult(
                game=self.game_id,
                score=self.points,
                rating=speed_rating(self.correct, self.errors, secs, self.level),
                level=self.level,
                next_level=nl,
                accuracy=acc,
                metrics={
                    "correct": self.correct,
                    "errors": self.errors,
                    "best_mult": self.best_mult,
                    "trials": total,
                    "headline": f"{self.points} очков",
                    "rows": [
                        ["Очки", str(self.points)],
                        ["Верных ответов", str(self.correct)],
                        ["Ошибок", str(self.errors)],
                        ["Лучший множитель", f"×{self.best_mult}"],
                        ["Скорость", f"{self.correct / secs * 60:.0f} ответов/мин"],
                    ],
                },
            )
        )

    def on_force_finish(self) -> None:
        self._alive = True
        self._finish()


__all__ = ["SpeedMatchGame", "make_sequence_item", "is_match", "speed_rating"]
