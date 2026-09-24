"""Устный счёт на скорость."""
from __future__ import annotations

import random

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QFont, QPainter
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..core import GameResult, linear_rating, plural
from ..theme import T
from .base import BigButton, Countdown, GameContext, GameWidget, draw_text

DURATION = 60


def _add(rng, lo, hi):
    a, b = rng.randint(lo, hi), rng.randint(lo, hi)
    return f"{a} + {b}", a + b


def _sub(rng, lo, hi, allow_negative=False):
    a, b = rng.randint(lo, hi), rng.randint(lo, hi)
    if not allow_negative and b > a:
        a, b = b, a
    return f"{a} − {b}", a - b


def _mul(rng, lo1, hi1, lo2, hi2):
    a, b = rng.randint(lo1, hi1), rng.randint(lo2, hi2)
    if rng.random() < 0.5:
        a, b = b, a
    return f"{a} × {b}", a * b


def _div(rng, lo, hi):
    b, q = rng.randint(lo, hi), rng.randint(lo, hi)
    return f"{b * q} ÷ {b}", q


def _pct(rng):
    p = rng.choice([10, 20, 25, 50, 75])
    base = rng.choice([20, 40, 60, 80, 120, 160, 200, 240, 300, 400])
    return f"{p}% от {base}", base * p // 100


def make_problem(level: int, rng: random.Random) -> tuple[str, int, int]:
    """(текст, ответ, вес). Вес отражает сложность и используется в подсчёте очков."""
    L = max(1, min(12, level))
    menu: list[tuple[int, callable]] = []
    if L <= 2:
        hi = 9 if L == 1 else 20
        menu += [(1, lambda: _add(rng, 1, hi)), (1, lambda: _sub(rng, 1, hi))]
    if 2 <= L <= 5:
        menu += [(2, lambda: _mul(rng, 2, 5 if L < 4 else 9, 2, 9))]
    if 3 <= L <= 6:
        menu += [(2, lambda: _add(rng, 11, 60 if L < 5 else 99)), (2, lambda: _sub(rng, 11, 60 if L < 5 else 99))]
    if 5 <= L <= 8:
        menu += [(2, lambda: _div(rng, 2, 9))]
    if 6 <= L:
        menu += [(3, lambda: _mul(rng, 11, 19 if L < 8 else 49, 2, 9))]
        menu += [(3, lambda: _add(rng, 100, 499)), (3, lambda: _sub(rng, 100, 499))]
    if 8 <= L:
        menu += [(3, lambda: (lambda n: (f"{n}²", n * n))(rng.randint(11, 20 if L < 10 else 30)))]
        menu += [(3, lambda: _pct(rng))]
    if 9 <= L:
        menu += [(4, lambda: _mul(rng, 11, 19 if L < 11 else 29, 11, 19 if L < 11 else 29))]
        menu += [(3, lambda: _div(rng, 6, 19))]
    if 10 <= L:
        menu += [(3, lambda: _sub(rng, -50, 99, allow_negative=True))]
    weight, fn = rng.choice(menu)
    text, ans = fn()
    return text.replace("+ -", "− ").replace("− -", "+ "), ans, weight


def math_rating(points: int) -> float:
    return linear_rating(points, 5, 100)


class ProblemView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.text = ""
        self.typed = ""
        self.state = "idle"
        self.setMinimumHeight(180)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        px = min(r.height() * 0.3, r.width() / 11)
        draw_text(p, QRectF(r.left(), r.top(), r.width(), r.height() * 0.55), f"{self.text} =", px, T.c("text"))
        col = {"idle": T.c("accent"), "bad": T.c("danger"), "good": T.c("success")}[self.state]
        shown = self.typed if self.typed else "?"
        draw_text(p, QRectF(r.left(), r.top() + r.height() * 0.5, r.width(), r.height() * 0.45), shown, px * 1.05,
                  col if self.typed else T.c("faint"))


class MathKeypad(QWidget):
    pressed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        g = QGridLayout(self)
        g.setSpacing(8)
        g.setContentsMargins(0, 0, 0, 0)
        keys = ["7", "8", "9", "4", "5", "6", "1", "2", "3", "−", "0", "⌫"]
        for i, k in enumerate(keys):
            b = BigButton(k)
            b.setFixedHeight(54)
            b.setMinimumWidth(70)
            b.clicked.connect(lambda k=k: self.pressed.emit(k))
            g.addWidget(b, i // 3, i % 3)
        ok = BigButton("Проверить")
        ok.setFixedHeight(54)
        ok.clicked.connect(lambda: self.pressed.emit("OK"))
        skip = BigButton("Пропуск")
        skip.setFixedHeight(54)
        skip.clicked.connect(lambda: self.pressed.emit("SKIP"))
        g.addWidget(ok, 4, 0, 1, 2)
        g.addWidget(skip, 4, 2, 1, 1)
        for c in range(3):
            g.setColumnStretch(c, 1)
        self.setFixedWidth(420)


class MathGame(GameWidget):
    game_id = "math"

    def __init__(self, ctx: GameContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.correct = 0
        self.errors = 0
        self.skipped = 0
        self.points = 0
        self.answer = 0
        self.weight = 1
        self.view = ProblemView()
        self.pad = MathKeypad()
        self.pad.pressed.connect(self.on_key)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 8, 24, 20)
        lay.setSpacing(12)
        lay.addWidget(self.view, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.pad)
        row.addStretch(1)
        lay.addLayout(row)
        hint = QLabel("Enter — проверить · Пробел — пропустить · верный ответ засчитывается сразу")
        hint.setProperty("role", "faint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(hint)

    def start(self) -> None:
        self.timer = Countdown(self, DURATION, self._finish)
        self.next_problem()

    def next_problem(self) -> None:
        text, self.answer, self.weight = make_problem(self.level, self.rng)
        self.view.text = text
        self.view.typed = ""
        self.view.state = "idle"
        self.view.update()
        self.set_hud(f"Решено: {self.correct}")

    def on_key(self, k: str) -> None:
        if not self.alive:
            return
        v = self.view
        if k == "⌫":
            v.typed = v.typed[:-1]
            v.state = "idle"
        elif k == "−":
            if not v.typed:
                v.typed = "-"
        elif k == "OK":
            if v.typed and v.typed != "-":
                if int(v.typed) == self.answer:
                    self._accept()
                    return
                self.errors += 1
                v.state = "bad"
                self.feedback(False)
                v.typed = ""
        elif k == "SKIP":
            self.skipped += 1
            self.play("flip")
            self.next_problem()
            return
        elif k.isdigit():
            if len(v.typed) < 7:
                v.typed += k
                v.state = "idle"
                try:
                    if int(v.typed) == self.answer:
                        self._accept()
                        return
                except ValueError:
                    pass
        v.update()

    def _accept(self) -> None:
        self.correct += 1
        self.points += self.weight
        self.view.state = "good"
        self.play("click")
        self.next_problem()

    def keyPressEvent(self, e) -> None:
        k = e.key()
        if Qt.Key.Key_0 <= k <= Qt.Key.Key_9:
            self.on_key(chr(k))
        elif k in (Qt.Key.Key_Minus,):
            self.on_key("−")
        elif k == Qt.Key.Key_Backspace:
            self.on_key("⌫")
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.on_key("OK")
        elif k == Qt.Key.Key_Space:
            self.on_key("SKIP")
        else:
            super().keyPressEvent(e)

    def _finish(self) -> None:
        attempts = self.correct + self.errors
        acc = self.correct / attempts if attempts else 0.0
        if self.correct >= 20 and acc >= 0.85:
            nl = self.level + 1
        elif self.correct < 10:
            nl = max(1, self.level - 1)
        else:
            nl = self.level
        self.finish(
            GameResult(
                game=self.game_id,
                score=self.points * 10,
                rating=math_rating(self.points),
                level=self.level,
                next_level=nl,
                accuracy=acc,
                metrics={
                    "correct": self.correct,
                    "errors": self.errors,
                    "skipped": self.skipped,
                    "points": self.points,
                    "trials": attempts,
                    "headline": f"{self.correct} {plural(self.correct, 'пример', 'примера', 'примеров')}",
                    "rows": [
                        ["Решено", str(self.correct)],
                        ["Ошибок", str(self.errors)],
                        ["Пропущено", str(self.skipped)],
                        ["Очки сложности", str(self.points)],
                    ],
                },
            )
        )

    def on_force_finish(self) -> None:
        self._alive = True
        self._finish()


__all__ = ["MathGame", "make_problem", "math_rating", "QFont"]
