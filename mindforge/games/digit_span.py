"""Цифровой ряд (Digit Span) — прямой и обратный."""
from __future__ import annotations

import random

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QFont, QPainter
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..core import GameResult, linear_rating, plural
from ..theme import T, font
from ..widgets.common import Hearts
from .base import BigButton, GameContext, GameWidget, draw_cell, draw_text

LIVES = 3


def make_sequence(length: int, rng: random.Random) -> list[int]:
    """Цифры без повторов подряд и без простых «лесенок» (1-2-3)."""
    seq: list[int] = []
    while len(seq) < length:
        d = rng.randrange(10)
        if seq and d == seq[-1]:
            continue
        if len(seq) >= 2 and seq[-1] - seq[-2] == d - seq[-1] and abs(d - seq[-1]) == 1:
            continue
        seq.append(d)
    return seq


def expected_answer(seq: list[int], mode: str) -> list[int]:
    return list(reversed(seq)) if mode == "backward" else list(seq)


def start_length(level: int, mode: str) -> int:
    base = 3 if mode == "forward" else 2
    return max(base, level)


def span_rating(span: int, mode: str) -> float:
    if mode == "backward":
        return linear_rating(span, 2, 9)
    return linear_rating(span, 3, 11)


class DigitDisplay(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.text = ""
        self.caption = ""
        self.slots = 0
        self.entered: list[int] = []
        self.mode = "show"  # show | input
        self.result: bool | None = None
        self.setMinimumHeight(220)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        if self.mode == "show":
            draw_text(p, r.adjusted(0, -10, 0, -10), self.text, min(r.height() * 0.6, 150), T.c("text"))
        else:
            n = max(1, self.slots)
            size = min(58.0, (r.width() - 40) / n - 8)
            total = n * size + (n - 1) * 8
            x0 = r.center().x() - total / 2
            y = r.center().y() - size / 2 - 10
            for i in range(n):
                cr = QRectF(x0 + i * (size + 8), y, size, size * 1.2)
                filled = i < len(self.entered)
                border = T.c("accent") if i == len(self.entered) else T.c("border")
                if self.result is True:
                    border = T.c("success")
                elif self.result is False:
                    border = T.c("danger")
                draw_cell(p, cr, T.c("surface2") if filled else T.c("surface"), border, 10, 2 if filled else 1.2)
                if filled:
                    draw_text(p, cr, str(self.entered[i]), size * 0.6, T.c("text"))
        if self.caption:
            draw_text(p, QRectF(r.left(), r.bottom() - 34, r.width(), 28), self.caption, 15, T.c("muted"),
                      QFont.Weight.DemiBold)


class Keypad(QWidget):
    pressed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setSpacing(10)
        grid.setContentsMargins(0, 0, 0, 0)
        keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "⌫", "0", "OK"]
        self.buttons = {}
        for i, k in enumerate(keys):
            b = BigButton(k)
            b.setFixedHeight(58)
            b.setMinimumWidth(80)
            b.clicked.connect(lambda k=k: self.pressed.emit(k))
            grid.addWidget(b, i // 3, i % 3)
            self.buttons[k] = b
        self.setMaximumWidth(360)


class DigitSpanGame(GameWidget):
    game_id = "digit_span"

    def __init__(self, ctx: GameContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.mode = ctx.options.get("mode", "forward")
        self.length = start_length(self.level, self.mode)
        self.start_len = self.length
        self.lives = LIVES
        self.best_span = 0
        self.trials = 0
        self.correct = 0
        self.seq: list[int] = []
        self.accepting = False

        self.display = DigitDisplay()
        self.hearts = Hearts(LIVES)
        self.keypad = Keypad()
        self.keypad.pressed.connect(self.on_key)
        self.keypad.setEnabled(False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 8, 24, 24)
        lay.setSpacing(12)
        top = QHBoxLayout()
        top.addStretch(1)
        top.addWidget(self.hearts)
        lay.addLayout(top)
        lay.addWidget(self.display, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.keypad)
        row.addStretch(1)
        lay.addLayout(row)
        self.hint = QLabel("")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setFont(font(10))
        self.hint.setProperty("role", "muted")
        lay.addWidget(self.hint)

    def start(self) -> None:
        self.new_trial()

    def new_trial(self) -> None:
        self.seq = make_sequence(self.length, self.rng)
        self.display.mode = "show"
        self.display.text = ""
        self.display.caption = f"Запоминайте: {self.length} цифр"
        self.display.result = None
        self.display.update()
        self.keypad.setEnabled(False)
        self.accepting = False
        self.set_hud(f"Длина ряда: {self.length}", f"Лучший: {self.best_span or '—'}")
        self.hint.setText("")
        self._show_idx = 0
        self.after(700, self._show_next)

    def _show_next(self) -> None:
        if self._show_idx >= len(self.seq):
            self.display.text = ""
            self.display.update()
            self.after(350, self._start_input)
            return
        self.display.text = str(self.seq[self._show_idx])
        self.display.update()
        self.play("flip")
        self._show_idx += 1
        self.after(750, self._blank)

    def _blank(self) -> None:
        self.display.text = ""
        self.display.update()
        self.after(250, self._show_next)

    def _start_input(self) -> None:
        self.display.mode = "input"
        self.display.slots = self.length
        self.display.entered = []
        self.display.caption = "Введите цифры в обратном порядке" if self.mode == "backward" else "Введите цифры"
        self.display.update()
        self.keypad.setEnabled(True)
        self.accepting = True
        self.hint.setText("Цифры 0–9 · Backspace — стереть · Enter — проверить")

    def on_key(self, k: str) -> None:
        if not self.accepting:
            return
        if k == "⌫":
            if self.display.entered:
                self.display.entered.pop()
                self.play("click")
        elif k == "OK":
            if self.display.entered:
                self._check()
            return
        elif k.isdigit() and len(self.display.entered) < self.length:
            self.display.entered.append(int(k))
            self.play("click")
            if len(self.display.entered) == self.length:
                self.display.update()
                self.after(250, self._check)
        self.display.update()

    def _check(self) -> None:
        if not self.accepting:
            return
        self.accepting = False
        self.keypad.setEnabled(False)
        self.trials += 1
        ok = self.display.entered == expected_answer(self.seq, self.mode)
        self.display.result = ok
        self.display.update()
        self.feedback(ok)
        if ok:
            self.correct += 1
            self.best_span = max(self.best_span, self.length)
            self.length += 1
        else:
            self.lives -= 1
            self.hearts.set_left(self.lives)
            answer = " ".join(str(d) for d in expected_answer(self.seq, self.mode))
            self.hint.setText(f"Правильно: {answer}")
        if self.lives <= 0 or self.length > 20:
            self.after(1300, self._finish)
        else:
            self.after(1300 if not ok else 700, self.new_trial)

    def keyPressEvent(self, e) -> None:
        k = e.key()
        if Qt.Key.Key_0 <= k <= Qt.Key.Key_9:
            self.on_key(chr(k))
        elif k in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            self.on_key("⌫")
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.on_key("OK")
        else:
            super().keyPressEvent(e)

    def _finish(self) -> None:
        span = self.best_span
        base = 3 if self.mode == "forward" else 2
        nl = max(base, span) if span else max(base, self.start_len - 1)
        acc = self.correct / self.trials if self.trials else 0.0
        self.finish(
            GameResult(
                game=self.game_id,
                score=span * 10 + self.correct,
                rating=span_rating(span, self.mode),
                level=self.start_len,
                next_level=nl,
                accuracy=acc,
                metrics={
                    "span": span,
                    "mode": self.mode,
                    "trials": self.trials,
                    "headline": f"{span} {plural(span, 'цифра', 'цифры', 'цифр')}",
                    "rows": [
                        ["Максимальный ряд", str(span)],
                        ["Порядок", "Обратный" if self.mode == "backward" else "Прямой"],
                        ["Верных попыток", f"{self.correct} из {self.trials}"],
                    ],
                    "note": "Средний результат взрослого — 7 цифр в прямом порядке и 5 в обратном.",
                },
            )
        )

    def on_force_finish(self) -> None:
        self._alive = True
        self._finish()


__all__ = ["DigitSpanGame", "make_sequence", "expected_answer", "span_rating", "start_length"]
