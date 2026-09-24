"""Числовые ряды: найдите следующее число. После ответа показывается правило."""
from __future__ import annotations

import random

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..core import GameResult, linear_rating
from ..theme import T, font
from ..widgets.common import button, label
from .base import BigButton, GameContext, GameWidget, draw_cell, draw_text

PROBLEMS = 10
PRIMES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71]


def _arith(rng):
    a, d = rng.randint(1, 30), rng.choice([2, 3, 4, 5, 6, 7, 8, 9])
    if rng.random() < 0.3:
        a, d = rng.randint(60, 99), -d
        return [a + d * i for i in range(7)], f"Каждое число меньше предыдущего на {-d}", 5
    return [a + d * i for i in range(7)], f"Каждое число больше предыдущего на {d}", 5


def _arith_big(rng):
    a, d = rng.randint(5, 60), rng.randint(11, 27)
    return [a + d * i for i in range(7)], f"К каждому числу прибавляется {d}", 5


def _geom(rng):
    k = rng.choice([2, 2, 3])
    a = rng.randint(1, 5) if k == 2 else rng.randint(1, 3)
    return [a * k ** i for i in range(7)], f"Каждое число умножается на {k}", 5


def _alt_add_sub(rng):
    a, x, y = rng.randint(2, 20), rng.randint(3, 9), rng.randint(1, 5)
    if x == y:
        x += 2
    seq = [a]
    for i in range(6):
        seq.append(seq[-1] + (x if i % 2 == 0 else -y))
    return seq, f"Поочерёдно +{x} и −{y}", 6


def _squares(rng):
    s = rng.randint(1, 6)
    return [(s + i) ** 2 for i in range(7)], f"Квадраты чисел: {s}², {s + 1}², {s + 2}²…", 5


def _growing_diff(rng):
    a, d0, c = rng.randint(1, 20), rng.randint(1, 4), rng.choice([1, 2, 3])
    seq, d = [a], d0
    for _ in range(6):
        seq.append(seq[-1] + d)
        d += c
    return seq, f"Разность увеличивается на {c}: +{d0}, +{d0 + c}, +{d0 + 2 * c}…", 5


def _interleaved(rng):
    a, d1 = rng.randint(1, 10), rng.randint(2, 5)
    b, d2 = rng.randint(20, 40), rng.randint(2, 5)
    seq = []
    for i in range(4):
        seq += [a + d1 * i, b - d2 * i]
    return seq[:7], f"Два ряда через одно: первый растёт на {d1}, второй убывает на {d2}", 6


def _fib(rng):
    a, b = rng.randint(1, 5), rng.randint(1, 6)
    seq = [a, b]
    while len(seq) < 7:
        seq.append(seq[-1] + seq[-2])
    return seq, "Каждое число — сумма двух предыдущих", 5


def _mul_add(rng):
    k, c, a = rng.choice([2, 3]), rng.randint(1, 5), rng.randint(1, 4)
    seq = [a]
    for i in range(6):
        seq.append(seq[-1] * k if i % 2 == 0 else seq[-1] + c)
    return seq, f"Поочерёдно ×{k} и +{c}", 6


def _cubes(rng):
    s = rng.randint(1, 3)
    return [(s + i) ** 3 for i in range(7)], f"Кубы чисел: {s}³, {s + 1}³, {s + 2}³…", 5


def _double_diff(rng):
    a, d = rng.randint(1, 20), rng.choice([1, 2, 3])
    seq = [a]
    for i in range(6):
        seq.append(seq[-1] + d * 2 ** i)
    return seq, f"Разность удваивается: +{d}, +{2 * d}, +{4 * d}…", 5


def _times_plus(rng):
    c = rng.choice([1, 2, 3, -1])
    a = rng.randint(1, 4) if c > 0 else rng.randint(2, 5)
    seq = [a]
    for _ in range(6):
        seq.append(seq[-1] * 2 + c)
    sign = f"+ {c}" if c > 0 else f"− {-c}"
    return seq, f"Каждое число: предыдущее × 2 {sign}", 5


def _primes(rng):
    s = rng.randint(0, 6)
    return PRIMES[s:s + 7], "Простые числа по порядку", 5


def _triangular(rng):
    s = rng.randint(1, 5)
    tri = [n * (n + 1) // 2 for n in range(s, s + 7)]
    return tri, "Треугольные числа: к числу прибавляется 1, 2, 3, 4… (каждый раз на 1 больше)", 5


def _factorial_like(rng):
    a = rng.choice([1, 2, 3])
    seq = [a]
    for i in range(1, 7):
        seq.append(seq[-1] * i)
    return seq, "Умножение по очереди на 1, 2, 3, 4, 5…", 5


def _square_diffs(rng):
    a = rng.randint(1, 10)
    seq = [a]
    for i in range(1, 7):
        seq.append(seq[-1] + i * i)
    return seq, "Разности — квадраты: +1, +4, +9, +16, +25…", 5


def _tribonacci(rng):
    seq = [rng.randint(0, 2), rng.randint(1, 3), rng.randint(1, 4)]
    while len(seq) < 7:
        seq.append(seq[-1] + seq[-2] + seq[-3])
    return seq, "Каждое число — сумма трёх предыдущих", 6


def _pronic(rng):
    s = rng.randint(1, 4)
    return [n * (n + 1) for n in range(s, s + 7)], "n × (n + 1): 1×2, 2×3, 3×4…", 5


def _alt_mul_sub(rng):
    a, c = rng.randint(2, 5), rng.randint(1, 3)
    seq = [a]
    for i in range(6):
        seq.append(seq[-1] * 2 if i % 2 == 0 else seq[-1] - c)
    return seq, f"Поочерёдно ×2 и −{c}", 6


TIERS = {
    1: [_arith],
    2: [_arith_big, _geom, _alt_add_sub],
    3: [_squares, _growing_diff, _interleaved, _geom],
    4: [_fib, _mul_add, _cubes, _double_diff],
    5: [_times_plus, _primes, _triangular, _interleaved, _mul_add],
    6: [_factorial_like, _square_diffs, _tribonacci, _pronic, _alt_mul_sub],
}


def make_distractors(seq: list[int], visible: int, answer: int, rng: random.Random) -> list[int]:
    last = seq[visible - 1]
    prev = seq[visible - 2]
    diff = last - prev
    cands = [
        last + diff,
        answer + 1,
        answer - 1,
        answer + 2,
        answer - 2,
        answer + abs(diff) if diff else answer + 3,
        answer - abs(diff) if diff else answer - 3,
        last * 2,
        answer + 10,
        answer - 10,
        round(answer * 1.5),
    ]
    rng.shuffle(cands)
    out: list[int] = []
    for c in cands:
        if c != answer and c not in out and (c >= 0 or answer < 0 or min(seq) < 0):
            out.append(c)
        if len(out) == 3:
            break
    k = 3
    while len(out) < 3:
        c = answer + k
        if c not in out and c != answer:
            out.append(c)
        k += 1
    return out


def make_problem(tier: int, rng: random.Random) -> dict:
    tier = max(1, min(6, tier))
    gen = rng.choice(TIERS[tier])
    seq, rule, visible = gen(rng)
    answer = seq[visible]
    options = make_distractors(seq, visible, answer, rng) + [answer]
    rng.shuffle(options)
    return {"shown": seq[:visible], "answer": answer, "options": options, "rule": rule, "tier": tier}


def series_rating(points: int) -> float:
    return linear_rating(points, 4, 50)


class SeriesView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.problem: dict | None = None
        self.revealed: bool = False
        self.setMinimumHeight(150)

    def paintEvent(self, e) -> None:
        if not self.problem:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        items = [str(x) for x in self.problem["shown"]] + [
            str(self.problem["answer"]) if self.revealed else "?"
        ]
        n = len(items)
        r = QRectF(self.rect())
        gap = 12
        w = min(118.0, (r.width() - gap * (n - 1)) / n)
        h = min(r.height() * 0.75, w * 0.85)
        total = n * w + (n - 1) * gap
        x0 = r.center().x() - total / 2
        y = r.center().y() - h / 2
        for i, txt in enumerate(items):
            cr = QRectF(x0 + i * (w + gap), y, w, h)
            last = i == n - 1
            border = T.domain("logic") if last else T.c("border")
            bg = T.c("surface2") if not last else T.c("surface")
            draw_cell(p, cr, bg, border, 14, 2 if last else 1.2)
            size = h * (0.42 if len(txt) <= 3 else 0.32 if len(txt) <= 4 else 0.26)
            draw_text(p, cr, txt, size, T.domain("logic") if last else T.c("text"))


class SeriesGame(GameWidget):
    game_id = "series"

    def __init__(self, ctx: GameContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.tier = max(1, min(6, self.level))
        self.start_tier = self.tier
        self.index = 0
        self.correct = 0
        self.points = 0
        self.max_solved = 0
        self.tiers_seen: list[int] = []
        self.problem: dict | None = None
        self.answered = False
        self.view = SeriesView()
        self.buttons: list[BigButton] = []
        self.explain = QLabel("")
        self.explain.setWordWrap(True)
        self.explain.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.explain.setFont(font(12, QFont.Weight.DemiBold))
        self.explain.setMinimumHeight(52)
        self.btn_next = button("Далее  →", "primary", on_click=self.next_problem)
        self.btn_next.setVisible(False)
        self.btn_next.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 8, 32, 24)
        lay.setSpacing(16)
        lay.addStretch(1)
        lay.addWidget(label("Какое число следующее?", "h2", align=Qt.AlignmentFlag.AlignCenter))
        lay.addWidget(self.view, 2)
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addStretch(1)
        for i in range(4):
            b = BigButton("", str(i + 1))
            b.setMaximumWidth(190)
            b.clicked.connect(lambda i=i: self.choose(i))
            row.addWidget(b, 2)
            self.buttons.append(b)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(self.explain)
        nr = QHBoxLayout()
        nr.addStretch(1)
        nr.addWidget(self.btn_next)
        nr.addStretch(1)
        lay.addLayout(nr)
        lay.addStretch(1)

    def start(self) -> None:
        self.next_problem()

    def next_problem(self) -> None:
        if not self.alive:
            return
        if self.index >= PROBLEMS:
            self._finish()
            return
        self.problem = make_problem(self.tier, self.rng)
        self.tiers_seen.append(self.tier)
        self.index += 1
        self.answered = False
        self.view.problem = self.problem
        self.view.revealed = False
        self.view.update()
        for b, opt in zip(self.buttons, self.problem["options"]):
            b.text = str(opt)
            b.set_state("idle")
            b.setEnabled(True)
        self.explain.setText("")
        self.btn_next.setVisible(False)
        self.set_hud(f"Сложность {self.tier} из 6", f"Задача {self.index} из {PROBLEMS}")
        self.progress_changed.emit((self.index - 1) / PROBLEMS)
        self.setFocus()

    def choose(self, i: int) -> None:
        if not self.alive or self.answered or not self.problem:
            return
        self.answered = True
        chosen = self.problem["options"][i]
        ok = chosen == self.problem["answer"]
        for b, opt in zip(self.buttons, self.problem["options"]):
            if opt == self.problem["answer"]:
                b.set_state("good")
            elif b is self.buttons[i]:
                b.set_state("bad")
        self.view.revealed = True
        self.view.update()
        self.feedback(ok)
        col = T.hex("success") if ok else T.hex("danger")
        head = "Верно!" if ok else f"Неверно. Ответ: {self.problem['answer']}"
        self.explain.setText(f"<span style='color:{col}'>{head}</span><br>"
                             f"<span style='color:{T.hex('muted')}'>Правило: {self.problem['rule']}</span>")
        if ok:
            self.correct += 1
            self.points += self.problem["tier"]
            self.max_solved = max(self.max_solved, self.problem["tier"])
            self.tier = min(6, self.tier + 1)
        else:
            self.tier = max(1, self.tier - 1)
        self.btn_next.setVisible(True)
        if self.index >= PROBLEMS:
            self.btn_next.setText("Результаты  →")

    def keyPressEvent(self, e) -> None:
        k = e.key()
        if Qt.Key.Key_1 <= k <= Qt.Key.Key_4:
            self.choose(k - Qt.Key.Key_1)
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space) and self.answered:
            self.next_problem()
        else:
            super().keyPressEvent(e)

    def _finish(self) -> None:
        recent = self.tiers_seen[-4:] or [self.start_tier]
        nl = max(1, min(6, round(sum(recent) / len(recent))))
        acc = self.correct / max(1, self.index)
        self.finish(
            GameResult(
                game=self.game_id,
                score=self.points * 10,
                rating=series_rating(self.points),
                level=self.start_tier,
                next_level=nl,
                accuracy=acc,
                metrics={
                    "correct": self.correct,
                    "total": self.index,
                    "max_solved": self.max_solved,
                    "points": self.points,
                    "trials": self.index,
                    "headline": f"{self.correct} из {self.index}",
                    "rows": [
                        ["Решено", f"{self.correct} из {self.index}"],
                        ["Максимальная сложность", f"{self.max_solved} из 6" if self.max_solved else "—"],
                        ["Очки сложности", str(self.points)],
                    ],
                },
            )
        )

    def on_force_finish(self) -> None:
        self._alive = True
        self._finish()


__all__ = ["SeriesGame", "make_problem", "make_distractors", "TIERS", "series_rating", "QColor"]
