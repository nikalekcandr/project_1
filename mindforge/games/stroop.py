"""Эффект Струпа с правилом-переключателем на высоких уровнях."""
from __future__ import annotations

import random
from statistics import mean

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ..core import GameResult, clamp, linear_rating, plural
from ..theme import T, font
from .base import BigButton, Countdown, GameContext, GameWidget, draw_text

DURATION = 45
COLORS = [("КРАСНЫЙ", "Красный", "#EF4444"), ("СИНИЙ", "Синий", "#3B82F6"),
          ("ЗЕЛЁНЫЙ", "Зелёный", "#22C55E"), ("ЖЁЛТЫЙ", "Жёлтый", "#FACC15")]


def frame_probability(level: int) -> float:
    if level < 4:
        return 0.0
    return min(0.5, 0.2 + 0.06 * (level - 4))


def make_trial(level: int, rng: random.Random, prev: dict | None = None) -> dict:
    while True:
        word = rng.randrange(4)
        congruent = rng.random() < 0.25
        ink = word if congruent else rng.choice([i for i in range(4) if i != word])
        framed = rng.random() < frame_probability(level)
        answer = word if framed else ink
        t = {"word": word, "ink": ink, "framed": framed, "answer": answer, "congruent": congruent}
        if prev is None or (t["word"], t["ink"]) != (prev["word"], prev["ink"]):
            return t


def stroop_rating(correct: int, errors: int, seconds: float, level: int) -> float:
    total = correct + errors
    acc = correct / total if total else 0.0
    cpm = correct / max(1.0, seconds) * 60
    return clamp(linear_rating(cpm * acc, 15, 60) + (level - 1) * 2)


class StroopDisplay(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.trial: dict | None = None
        self.setMinimumHeight(220)

    def paintEvent(self, e) -> None:
        if not self.trial:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        word, _, _ = COLORS[self.trial["word"]]
        ink = QColor(COLORS[self.trial["ink"]][2])
        f = font(10, QFont.Weight.Black)
        px = min(r.height() * 0.3, 140.0)
        f.setPixelSize(int(px))
        fm = QFontMetricsF(f)
        tw = fm.horizontalAdvance(word)
        max_w = r.width() * 0.72
        if tw > max_w:
            px *= max_w / tw
            f.setPixelSize(int(px))
            fm = QFontMetricsF(f)
            tw = fm.horizontalAdvance(word)
        if self.trial["framed"]:
            th = fm.height()
            fr = QRectF(r.center().x() - tw / 2 - px * 0.4, r.center().y() - th / 2 - px * 0.15,
                        tw + px * 0.8, th + px * 0.3)
            pen = QPen(T.c("text"), 3)
            pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(fr, 14, 14)
        p.setFont(f)
        p.setPen(ink)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, word)
        hint = "Слово в рамке — отвечайте по СМЫСЛУ" if self.trial["framed"] else "Выберите ЦВЕТ букв"
        draw_text(p, QRectF(r.left(), r.bottom() - 30, r.width(), 26), hint, 14, T.c("muted"), QFont.Weight.DemiBold)


class StroopGame(GameWidget):
    game_id = "stroop"

    def __init__(self, ctx: GameContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.correct = 0
        self.errors = 0
        self.rt_cong: list[float] = []
        self.rt_incong: list[float] = []
        self.trial: dict | None = None
        self.t_shown = 0.0
        self.display = StroopDisplay()
        self.buttons: list[BigButton] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 8, 24, 24)
        lay.setSpacing(18)
        lay.addWidget(self.display, 1)
        row = QHBoxLayout()
        row.setSpacing(12)
        for i, (_, name, hexc) in enumerate(COLORS):
            b = BigButton(name, str(i + 1), QColor(hexc))
            b.clicked.connect(lambda i=i: self.answer(i))
            row.addWidget(b)
            self.buttons.append(b)
        lay.addLayout(row)

    def start(self) -> None:
        self.timer = Countdown(self, DURATION, self._finish)
        self.next_trial()

    def next_trial(self) -> None:
        self.trial = make_trial(self.level, self.rng, self.trial)
        self.display.trial = self.trial
        self.display.update()
        self.t_shown = self.elapsed()
        self.set_hud(f"Верно: {self.correct} · Ошибок: {self.errors}")

    def answer(self, i: int) -> None:
        if not self.alive or not self.trial:
            return
        rt = self.elapsed() - self.t_shown
        ok = i == self.trial["answer"]
        if ok:
            self.correct += 1
            if not self.trial["framed"]:
                (self.rt_cong if self.trial["congruent"] else self.rt_incong).append(rt)
            self.buttons[i].set_state("good", 160)
            self.play("click")
        else:
            self.errors += 1
            self.buttons[i].set_state("bad", 260)
            self.feedback(False)
        self.next_trial()

    def keyPressEvent(self, e) -> None:
        k = e.key()
        if Qt.Key.Key_1 <= k <= Qt.Key.Key_4:
            self.answer(k - Qt.Key.Key_1)
        else:
            super().keyPressEvent(e)

    def _finish(self) -> None:
        total = self.correct + self.errors
        acc = self.correct / total if total else 0.0
        secs = DURATION if not self.ctx.fast else max(1.0, self.elapsed())
        rating = stroop_rating(self.correct, self.errors, secs, self.level)
        if acc >= 0.9 and self.correct >= 25:
            nl = self.level + 1
        elif acc < 0.7:
            nl = max(1, self.level - 1)
        else:
            nl = self.level
        interference = None
        if self.rt_cong and self.rt_incong:
            interference = round((mean(self.rt_incong) - mean(self.rt_cong)) * 1000)
        rows = [
            ["Верных ответов", str(self.correct)],
            ["Ошибок", str(self.errors)],
            ["Точность", f"{round(acc * 100)}%"],
        ]
        if self.rt_cong or self.rt_incong:
            rows.append(["Среднее время", f"{round(mean(self.rt_cong + self.rt_incong) * 1000)} мс"])
        if interference is not None:
            rows.append(["Эффект интерференции", f"{interference:+d} мс"])
        self.finish(
            GameResult(
                game=self.game_id,
                score=self.correct * 10 - self.errors * 5,
                rating=rating,
                level=self.level,
                next_level=nl,
                accuracy=acc,
                metrics={
                    "correct": self.correct,
                    "errors": self.errors,
                    "interference_ms": interference,
                    "trials": total,
                    "headline": f"{self.correct} {plural(self.correct, 'верный ответ', 'верных ответа', 'верных ответов')}",
                    "rows": rows,
                    "note": "Интерференция — насколько дольше вы отвечаете, когда слово и цвет не совпадают. "
                            "Чем она меньше, тем лучше контроль внимания.",
                },
            )
        )

    def on_force_finish(self) -> None:
        self._alive = True
        self._finish()


__all__ = ["StroopGame", "make_trial", "stroop_rating", "frame_probability", "clamp"]
