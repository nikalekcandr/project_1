"""Запомни слова: изучение списка, затем свободное воспроизведение или узнавание."""
from __future__ import annotations

import random

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core import GameResult, clamp, linear_rating
from ..data.words_ru import WORDS
from ..theme import T, font
from ..widgets.common import button, label
from ..widgets.flow import FlowLayout
from .base import Countdown, GameContext, GameWidget


def word_count(level: int) -> int:
    return min(30, 6 + 2 * level)


def study_seconds(count: int) -> int:
    return int(count * 2.5 + 5)


def recall_seconds(count: int) -> int:
    return 45 + count * 4


def normalize(word: str) -> str:
    return word.strip().lower().replace("ё", "е")


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def pick_words(count: int, rng: random.Random, exclude: set[str] | None = None) -> list[str]:
    """Случайные слова, попарно отличающиеся хотя бы на 2 буквы (чтобы опечатки не путали)."""
    pool = [w for w in WORDS if not exclude or normalize(w) not in exclude]
    rng.shuffle(pool)
    chosen: list[str] = []
    for w in pool:
        nw = normalize(w)
        if all(levenshtein(nw, normalize(c)) >= 2 for c in chosen):
            chosen.append(w)
            if len(chosen) == count:
                break
    return chosen


def match_word(entry: str, targets: list[str], already: set[str]) -> str | None:
    """Находит слово из списка: точное совпадение или одна опечатка для слов от 5 букв."""
    e = normalize(entry)
    if not e:
        return None
    for t in targets:
        if normalize(t) == e:
            return t
    if len(e) >= 5:
        cands = [t for t in targets if t not in already and levenshtein(normalize(t), e) <= 1]
        if len(cands) == 1:
            return cands[0]
    return None


def recall_rating(correct: int, intrusions: int) -> float:
    return clamp(linear_rating(correct, 2, 20) - 2 * intrusions)


def recognition_rating(hits: int, false_alarms: int) -> float:
    return clamp(linear_rating(hits - false_alarms, 2, 24) * 0.8)


def chip(text: str, kind: str = "neutral") -> QLabel:
    lb = QLabel(text)
    lb.setFont(font(12, QFont.Weight.DemiBold))
    colors = {
        "neutral": (T.hex("surface2"), T.hex("border"), T.hex("text")),
        "good": (T.hex("surface2"), T.hex("success"), T.hex("text")),
        "bad": (T.hex("surface"), T.hex("danger"), T.hex("muted")),
    }
    bg, border, fg = colors[kind]
    deco = "text-decoration: line-through;" if kind == "bad" else ""
    lb.setStyleSheet(
        f"background:{bg}; border:1px solid {border}; color:{fg}; border-radius:10px; padding:8px 14px; {deco}"
    )
    return lb


class WordsGame(GameWidget):
    game_id = "words"

    def __init__(self, ctx: GameContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.mode = ctx.options.get("mode", "recall")
        self.count = word_count(self.level)
        self.words = pick_words(self.count, self.rng)
        self.found: list[str] = []
        self.intrusions: list[str] = []
        self.timer: Countdown | None = None
        self.phase = "study"

        self.stack = QStackedWidget()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 8, 32, 24)
        lay.addWidget(self.stack)

        # --- изучение
        study = QWidget()
        sl = QVBoxLayout(study)
        sl.setSpacing(18)
        t = label("Запомните эти слова", "h2", align=Qt.AlignmentFlag.AlignCenter)
        tip = label("Совет: представьте яркую картинку для каждого слова и свяжите их в историю.",
                    "muted", wrap=True, align=Qt.AlignmentFlag.AlignCenter)
        self.study_box = QWidget()
        fl = FlowLayout(self.study_box, spacing=12, center=True)
        for w in self.words:
            fl.addWidget(chip(w))
        self.btn_ready = button("Я запомнил(а)", "primary", "lg", on_click=self.start_test)
        self.btn_ready.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        sl.addStretch(1)
        sl.addWidget(t)
        sl.addWidget(tip)
        sl.addSpacing(8)
        sl.addWidget(self.study_box)
        sl.addSpacing(12)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.btn_ready)
        row.addStretch(1)
        sl.addLayout(row)
        sl.addStretch(2)
        self.stack.addWidget(study)

        # --- воспроизведение
        recall = QWidget()
        rl = QVBoxLayout(recall)
        rl.setSpacing(14)
        self.recall_title = label("Какие слова вы запомнили?", "h2", align=Qt.AlignmentFlag.AlignCenter)
        self.counter = label("", "muted", align=Qt.AlignmentFlag.AlignCenter)
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("Введите слово и нажмите Enter")
        self.entry.setFont(font(14))
        self.entry.setMinimumHeight(48)
        self.entry.setMaximumWidth(460)
        self.entry.returnPressed.connect(self.submit_word)
        self.msg = label("", "muted", align=Qt.AlignmentFlag.AlignCenter)
        self.found_box = QWidget()
        self.found_flow = FlowLayout(self.found_box, spacing=10, center=True)
        self.btn_done = button("Завершить", "primary", on_click=self._finish)
        rl.addSpacing(10)
        rl.addWidget(self.recall_title)
        rl.addWidget(self.counter)
        er = QHBoxLayout()
        er.addStretch(1)
        er.addWidget(self.entry, 1)
        er.addStretch(1)
        rl.addLayout(er)
        rl.addWidget(self.msg)
        rl.addWidget(self.found_box)
        rl.addStretch(1)
        br = QHBoxLayout()
        br.addStretch(1)
        br.addWidget(self.btn_done)
        br.addStretch(1)
        rl.addLayout(br)
        self.stack.addWidget(recall)

        # --- узнавание
        recog = QWidget()
        gl = QVBoxLayout(recog)
        gl.setSpacing(14)
        gl.addWidget(label("Отметьте слова, которые были в списке", "h2", align=Qt.AlignmentFlag.AlignCenter))
        self.recog_counter = label("", "muted", align=Qt.AlignmentFlag.AlignCenter)
        gl.addWidget(self.recog_counter)
        self.recog_box = QWidget()
        self.recog_flow = FlowLayout(self.recog_box, spacing=10, center=True)
        self.recog_buttons: list[QPushButton] = []
        gl.addWidget(self.recog_box)
        gl.addStretch(1)
        self.btn_check = button("Проверить", "primary", "lg", on_click=self._finish)
        self.btn_check.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        cr = QHBoxLayout()
        cr.addStretch(1)
        cr.addWidget(self.btn_check)
        cr.addStretch(1)
        gl.addLayout(cr)
        self.stack.addWidget(recog)

    def start(self) -> None:
        self.stack.setCurrentIndex(0)
        self.set_hud(f"Слов: {self.count}", "")
        self.timer = Countdown(self, study_seconds(self.count), self.start_test, "Изучение ")

    def start_test(self) -> None:
        if self.phase != "study" or not self.alive:
            return
        self.phase = "test"
        if self.timer:
            self.timer.stop()
        self.play("go")
        if self.mode == "recognize":
            distractors = pick_words(self.count, self.rng, exclude={normalize(w) for w in self.words})
            items = self.words + distractors
            self.rng.shuffle(items)
            for w in items:
                b = QPushButton(w)
                b.setProperty("kind", "seg")
                b.setCheckable(True)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.setFont(font(12, QFont.Weight.DemiBold))
                b.setMinimumHeight(42)
                b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                b.toggled.connect(self._update_recog_counter)
                self.recog_flow.addWidget(b)
                self.recog_buttons.append(b)
            self._update_recog_counter()
            self.stack.setCurrentIndex(2)
            self.setFocus()
            self.timer = Countdown(self, recall_seconds(self.count), self._finish)
        else:
            self._update_counter()
            self.stack.setCurrentIndex(1)
            self.entry.setFocus()
            self.timer = Countdown(self, recall_seconds(self.count), self._finish)

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.phase == "study":
                self.start_test()
                return
            if self.mode == "recognize":
                self._finish()
                return
        super().keyPressEvent(e)

    def _update_recog_counter(self, *_):
        n = sum(b.isChecked() for b in self.recog_buttons)
        self.recog_counter.setText(f"Отмечено: {n} · в списке было {self.count} слов")

    def _update_counter(self) -> None:
        self.counter.setText(f"Вспомнено: {len(self.found)} из {self.count}")
        self.set_hud(f"Вспомнено: {len(self.found)} / {self.count}")

    def submit_word(self) -> None:
        text = self.entry.text()
        self.entry.clear()
        if not normalize(text):
            return
        m = match_word(text, self.words, set(self.found))
        if m is None:
            if normalize(text) not in {normalize(x) for x in self.intrusions}:
                self.intrusions.append(text.strip())
                self.found_flow.addWidget(chip(text.strip(), "bad"))
            self.msg.setText(f"«{text.strip()}» — такого слова не было")
            self.play("wrong")
        elif m in self.found:
            self.msg.setText(f"«{m}» уже есть")
        else:
            self.found.append(m)
            self.found_flow.addWidget(chip(m, "good"))
            self.msg.setText("")
            self.play("correct")
            if len(self.found) == self.count:
                self.after(500, self._finish)
        self.found_box.updateGeometry()
        self._update_counter()

    def _finish(self) -> None:
        if self._done:
            return
        if self.timer:
            self.timer.stop()
        if self.mode == "recognize":
            targets = {normalize(w) for w in self.words}
            chosen = [b.text() for b in self.recog_buttons if b.isChecked()]
            hits = sum(normalize(c) in targets for c in chosen)
            fa = len(chosen) - hits
            total = len(self.recog_buttons) or 1
            correct_decisions = hits + (total - self.count - fa)
            acc = correct_decisions / total
            net = (hits - fa) / self.count
            nl = self.level + 1 if net >= 0.85 else (self.level - 1 if net < 0.6 else self.level)
            missed = [w for w in self.words if normalize(w) not in {normalize(c) for c in chosen}]
            rows = [
                ["Узнано слов", f"{hits} из {self.count}"],
                ["Ложные узнавания", str(fa)],
                ["Точность решений", f"{round(acc * 100)}%"],
            ]
            result = GameResult(
                game=self.game_id, score=max(0, hits * 10 - fa * 10), rating=recognition_rating(hits, fa),
                level=self.level, next_level=nl, accuracy=acc,
                metrics={"mode": "recognize", "correct": hits, "false_alarms": fa, "total": self.count,
                         "trials": total, "headline": f"{hits} из {self.count}", "rows": rows,
                         "note": ("Пропущены: " + ", ".join(missed)) if missed else "Все слова узнаны!"},
            )
        else:
            correct = len(self.found)
            frac = correct / self.count
            nl = self.level + 1 if frac >= 0.75 else (self.level - 1 if frac < 0.45 else self.level)
            missed = [w for w in self.words if w not in self.found]
            rows = [
                ["Вспомнено", f"{correct} из {self.count}"],
                ["Лишние слова", str(len(self.intrusions))],
                ["Доля", f"{round(frac * 100)}%"],
            ]
            result = GameResult(
                game=self.game_id, score=correct * 10 - 5 * len(self.intrusions),
                rating=recall_rating(correct, len(self.intrusions)), level=self.level, next_level=nl,
                accuracy=frac,
                metrics={"mode": "recall", "correct": correct, "intrusions": len(self.intrusions),
                         "total": self.count, "headline": f"{correct} из {self.count}", "rows": rows,
                         "note": ("Забыты: " + ", ".join(missed)) if missed else "Вы вспомнили все слова!"},
            )
        result.next_level = max(1, result.next_level)
        self.finish(result)

    def on_force_finish(self) -> None:
        self._alive = True
        self.phase = "test"
        self._finish()


__all__ = ["WordsGame", "pick_words", "match_word", "levenshtein", "normalize", "word_count"]
