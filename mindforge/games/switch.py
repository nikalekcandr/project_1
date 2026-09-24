"""Переключение задач: «число чётное?» / «буква гласная?»."""
from __future__ import annotations

import random
from statistics import mean

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFont, QPainter
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ..core import GameResult, clamp, linear_rating, plural
from ..theme import T, mix
from .base import BigButton, Countdown, GameContext, GameWidget, draw_cell, draw_text

DURATION = 60
VOWELS = "АЕИОУЫЭЮЯ"
CONSONANTS = "БВГДКЛМНПРСТФХ"
DIGITS = [1, 2, 3, 4, 6, 7, 8, 9]


def switch_probability(level: int) -> float | None:
    """None — предсказуемые смены (уровни 1–2)."""
    if level <= 2:
        return None
    return min(0.5, 0.3 + 0.03 * (level - 3))


def deadline(level: int) -> float | None:
    if level < 6:
        return None
    return max(1.3, 2.6 - 0.2 * (level - 6))


def next_position(level: int, index: int, prev: str | None, rng: random.Random) -> str:
    if prev is None:
        return rng.choice(["top", "bottom"])
    p = switch_probability(level)
    if p is None:
        run = 4 if level == 1 else 2
        if index % run == 0:
            return "bottom" if prev == "top" else "top"
        return prev
    if rng.random() < p:
        return "bottom" if prev == "top" else "top"
    return prev


def make_card(position: str, rng: random.Random) -> dict:
    digit = rng.choice(DIGITS)
    letter = rng.choice(VOWELS) if rng.random() < 0.5 else rng.choice(CONSONANTS)
    answer = (digit % 2 == 0) if position == "top" else (letter in VOWELS)
    return {"pos": position, "digit": digit, "letter": letter, "answer": answer}


def switch_rating(correct: int, errors: int, seconds: float, level: int) -> float:
    total = correct + errors
    acc = correct / total if total else 0.0
    cpm = correct / max(1.0, seconds) * 60
    return clamp(linear_rating(cpm * acc, 10, 55) + (level - 1) * 1.5)


class SwitchDisplay(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.card: dict | None = None
        self.setMinimumSize(320, 300)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = min(self.width() - 20, 520)
        h = min(self.height() - 10, 420)
        box = QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)
        top = QRectF(box.left(), box.top(), w, h / 2 - 4)
        bottom = QRectF(box.left(), box.top() + h / 2 + 4, w, h / 2 - 4)
        col = T.domain("flexibility")
        for rect, caption, key in ((top, "ЧИСЛО ЧЁТНОЕ?", "top"), (bottom, "БУКВА ГЛАСНАЯ?", "bottom")):
            active = self.card is not None and self.card["pos"] == key
            bg = mix(T.c("surface"), col, 0.08 if active else 0.0)
            draw_cell(p, rect, bg, mix(T.c("border"), col, 0.6 if active else 0.0), 18, 1.5)
            draw_text(p, QRectF(rect.left() + 18, rect.top() + 10, rect.width() - 36, 22), caption, 12,
                      T.c("muted"), QFont.Weight.Bold, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if self.card:
            rect = top if self.card["pos"] == "top" else bottom
            cw, ch = min(190.0, rect.width() * 0.45), rect.height() * 0.62
            cr = QRectF(rect.center().x() - cw / 2, rect.center().y() - ch / 2 + 8, cw, ch)
            draw_cell(p, cr, T.c("surface3"), col, 16, 2)
            draw_text(p, cr, f"{self.card['digit']}{self.card['letter']}", ch * 0.55, T.c("text"), QFont.Weight.Black)


class SwitchGame(GameWidget):
    game_id = "switch"

    def __init__(self, ctx: GameContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.correct = 0
        self.errors = 0
        self.timeouts = 0
        self.rt_switch: list[float] = []
        self.rt_repeat: list[float] = []
        self.index = 0
        self.card: dict | None = None
        self.prev_pos: str | None = None
        self.was_switch = False
        self.deadline_timer = None
        self.t_shown = 0.0
        self.display = SwitchDisplay()
        self.btn_no = BigButton("Нет", "←")
        self.btn_yes = BigButton("Да", "→")
        self.btn_no.clicked.connect(lambda: self.answer(False))
        self.btn_yes.clicked.connect(lambda: self.answer(True))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 8, 24, 24)
        lay.setSpacing(18)
        lay.addWidget(self.display, 1)
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addStretch(1)
        for b in (self.btn_no, self.btn_yes):
            b.setMaximumWidth(260)
            row.addWidget(b, 2)
        row.addStretch(1)
        lay.addLayout(row)

    def start(self) -> None:
        self.timer = Countdown(self, DURATION, self._finish)
        self.next_card()

    def next_card(self) -> None:
        pos = next_position(self.level, self.index, self.prev_pos, self.rng)
        self.was_switch = self.prev_pos is not None and pos != self.prev_pos
        self.prev_pos = pos
        self.index += 1
        self.card = make_card(pos, self.rng)
        self.display.card = self.card
        self.display.update()
        self.t_shown = self.elapsed()
        self.set_hud(f"Верно: {self.correct} · Ошибок: {self.errors}")
        dl = deadline(self.level)
        self.cancel(self.deadline_timer)
        if dl:
            self.deadline_timer = self.after(int(dl * 1000), self._timeout)

    def _timeout(self) -> None:
        self.timeouts += 1
        self.errors += 1
        self.feedback(False)
        self.next_card()

    def answer(self, yes: bool) -> None:
        if not self.alive or not self.card:
            return
        rt = self.elapsed() - self.t_shown
        btn = self.btn_yes if yes else self.btn_no
        if yes == self.card["answer"]:
            self.correct += 1
            (self.rt_switch if self.was_switch else self.rt_repeat).append(rt)
            btn.set_state("good", 150)
            self.play("click")
        else:
            self.errors += 1
            btn.set_state("bad", 250)
            self.feedback(False)
        self.next_card()

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
        if acc >= 0.9 and self.correct >= 25:
            nl = self.level + 1
        elif acc < 0.7:
            nl = max(1, self.level - 1)
        else:
            nl = self.level
        cost = None
        if self.rt_switch and self.rt_repeat:
            cost = round((mean(self.rt_switch) - mean(self.rt_repeat)) * 1000)
        rows = [["Верных ответов", str(self.correct)], ["Ошибок", str(self.errors)],
                ["Точность", f"{round(acc * 100)}%"]]
        if self.timeouts:
            rows.append(["Не успели ответить", str(self.timeouts)])
        if cost is not None:
            rows.append(["Цена переключения", f"{cost:+d} мс"])
        self.finish(
            GameResult(
                game=self.game_id,
                score=self.correct * 10 - self.errors * 5,
                rating=switch_rating(self.correct, self.errors, secs, self.level),
                level=self.level,
                next_level=nl,
                accuracy=acc,
                metrics={
                    "correct": self.correct,
                    "errors": self.errors,
                    "switch_cost_ms": cost,
                    "trials": total,
                    "headline": f"{self.correct} {plural(self.correct, 'верный ответ', 'верных ответа', 'верных ответов')}",
                    "rows": rows,
                    "note": "Цена переключения — насколько вы медленнее после смены правила. "
                            "С тренировкой она уменьшается.",
                },
            )
        )

    def on_force_finish(self) -> None:
        self._alive = True
        self._finish()


__all__ = ["SwitchGame", "make_card", "next_position", "switch_rating", "deadline"]
