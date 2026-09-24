"""Мысленное вращение фигур-полимино (задача Шепарда–Метцлера в 2D)."""
from __future__ import annotations

import random
from statistics import mean

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ..core import GameResult, clamp, linear_rating, plural
from ..theme import T, mix
from .base import BigButton, Countdown, GameContext, GameWidget, draw_cell, draw_text

DURATION = 60
Cell = tuple[int, int]


def normalize(cells) -> tuple[Cell, ...]:
    mx = min(x for x, _ in cells)
    my = min(y for _, y in cells)
    return tuple(sorted((x - mx, y - my) for x, y in cells))


def rotate90(cells) -> tuple[Cell, ...]:
    return normalize([(y, -x) for x, y in cells])


def mirror(cells) -> tuple[Cell, ...]:
    return normalize([(-x, y) for x, y in cells])


def rotations(cells) -> set[tuple[Cell, ...]]:
    out = set()
    cur = normalize(cells)
    for _ in range(4):
        out.add(cur)
        cur = rotate90(cur)
    return out


def is_chiral(cells) -> bool:
    return mirror(cells) not in rotations(cells)


def make_polyomino(k: int, rng: random.Random) -> tuple[Cell, ...]:
    while True:
        cells = {(0, 0)}
        while len(cells) < k:
            x, y = rng.choice(sorted(cells))
            dx, dy = rng.choice([(1, 0), (-1, 0), (0, 1), (0, -1)])
            cells.add((x + dx, y + dy))
        shape = normalize(cells)
        xs = [x for x, _ in shape]
        ys = [y for _, y in shape]
        # отбрасываем слишком «линейные» фигуры и симметричные относительно зеркала
        if max(xs) >= 1 and max(ys) >= 1 and is_chiral(shape):
            return shape


def level_params(level: int) -> tuple[int, list[int]]:
    """(число клеток, допустимые углы поворота)."""
    if level <= 2:
        return 5, [0, 90, 180, 270]
    if level <= 4:
        return 6, [60, 90, 120, 180, 240, 270]
    if level <= 7:
        return 7, list(range(30, 360, 30))
    return 8, list(range(20, 360, 20))


def make_trial(level: int, rng: random.Random) -> dict:
    k, angles = level_params(level)
    shape = make_polyomino(k, rng)
    mirrored = rng.random() < 0.5
    right = mirror(shape) if mirrored else shape
    angle = rng.choice(angles)
    left_angle = rng.choice([0, 0, 90, 180, 270]) if level >= 8 else 0
    return {"left": shape, "right": right, "angle": angle, "left_angle": left_angle, "mirrored": mirrored}


def rotation_rating(correct: int, errors: int, seconds: float, level: int) -> float:
    total = correct + errors
    acc = correct / total if total else 0.0
    cpm = correct / max(1.0, seconds) * 60
    return clamp(linear_rating(cpm * acc, 5, 34) + (level - 1) * 2)


def draw_polyomino(p: QPainter, cells, center: QPointF, unit: float, angle: float, color: QColor) -> None:
    xs = [x for x, _ in cells]
    ys = [y for _, y in cells]
    cx = (min(xs) + max(xs) + 1) / 2
    cy = (min(ys) + max(ys) + 1) / 2
    p.save()
    p.translate(center)
    p.rotate(angle)
    for x, y in cells:
        r = QRectF((x - cx) * unit, (y - cy) * unit, unit, unit).adjusted(1.5, 1.5, -1.5, -1.5)
        draw_cell(p, r, color, mix(color, QColor("white"), 0.35), unit * 0.16, 1.5)
    p.restore()


class RotationView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.trial: dict | None = None
        self.setMinimumHeight(260)

    def paintEvent(self, e) -> None:
        if not self.trial:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        gap = 24
        pw = min((r.width() - gap) / 2, r.height() - 10)
        total = pw * 2 + gap
        x0 = r.center().x() - total / 2
        y0 = r.center().y() - pw / 2
        col = T.domain("spatial")
        for i, (cells, ang) in enumerate(((self.trial["left"], self.trial["left_angle"]),
                                          (self.trial["right"], self.trial["angle"] + self.trial["left_angle"]))):
            panel = QRectF(x0 + i * (pw + gap), y0, pw, pw)
            draw_cell(p, panel, T.c("surface"), T.c("border"), 20, 1.2)
            span = max(max(x for x, _ in cells), max(y for _, y in cells)) + 1
            unit = pw * 0.62 / span
            draw_polyomino(p, cells, panel.center(), unit, ang, col if i == 0 else mix(col, T.domain("memory"), 0.35))


class RotationGame(GameWidget):
    game_id = "rotation"

    def __init__(self, ctx: GameContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.correct = 0
        self.errors = 0
        self.rts: list[float] = []
        self.trial: dict | None = None
        self.t_shown = 0.0
        self.view = RotationView()
        self.btn_same = BigButton("Совпадает", "←")
        self.btn_mirror = BigButton("Зеркальная", "→")
        self.btn_same.clicked.connect(lambda: self.answer(False))
        self.btn_mirror.clicked.connect(lambda: self.answer(True))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 8, 24, 24)
        lay.setSpacing(16)
        lay.addWidget(self.view, 1)
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addStretch(1)
        for b in (self.btn_same, self.btn_mirror):
            b.setMaximumWidth(280)
            row.addWidget(b, 2)
        row.addStretch(1)
        lay.addLayout(row)

    def start(self) -> None:
        self.timer = Countdown(self, DURATION, self._finish)
        self.next_trial()

    def next_trial(self) -> None:
        self.trial = make_trial(self.level, self.rng)
        self.view.trial = self.trial
        self.view.update()
        self.t_shown = self.elapsed()
        self.set_hud(f"Верно: {self.correct} · Ошибок: {self.errors}")

    def answer(self, says_mirror: bool) -> None:
        if not self.alive or not self.trial:
            return
        btn = self.btn_mirror if says_mirror else self.btn_same
        if says_mirror == self.trial["mirrored"]:
            self.correct += 1
            self.rts.append(self.elapsed() - self.t_shown)
            btn.set_state("good", 180)
            self.play("correct")
        else:
            self.errors += 1
            btn.set_state("bad", 300)
            self.feedback(False)
        self.next_trial()

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
        if acc >= 0.9 and self.correct >= 15:
            nl = self.level + 1
        elif acc < 0.7:
            nl = max(1, self.level - 1)
        else:
            nl = self.level
        rows = [["Верных ответов", str(self.correct)], ["Ошибок", str(self.errors)],
                ["Точность", f"{round(acc * 100)}%"]]
        if self.rts:
            rows.append(["Среднее время ответа", f"{mean(self.rts):.2f} с"])
        self.finish(
            GameResult(
                game=self.game_id,
                score=self.correct * 10 - self.errors * 5,
                rating=rotation_rating(self.correct, self.errors, secs, self.level),
                level=self.level,
                next_level=nl,
                accuracy=acc,
                metrics={
                    "correct": self.correct,
                    "errors": self.errors,
                    "trials": total,
                    "headline": f"{self.correct} {plural(self.correct, 'верный', 'верных', 'верных')} · {round(acc * 100)}%",
                    "rows": rows,
                },
            )
        )

    def on_force_finish(self) -> None:
        self._alive = True
        self._finish()


__all__ = ["RotationGame", "make_polyomino", "is_chiral", "mirror", "rotations", "make_trial"]
