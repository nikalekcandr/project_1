"""Логические матрицы в стиле Равена с процедурной генерацией.

Каждая панель описывается четырьмя атрибутами: форма, количество, размер, заливка.
По строкам действуют правила: постоянство, прогрессия, «каждое значение по разу»,
арифметика (для количества). Варианты ответа строятся сбалансированным деревом
(как в I-RAVEN), поэтому правильный ответ нельзя угадать по частоте признаков.
"""
from __future__ import annotations

import random

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..core import GameResult, linear_rating
from ..theme import T, font, mix
from ..widgets.common import button
from .base import GameContext, GameWidget, draw_cell, draw_text
from .shapes import shape_path

PROBLEMS = 8
ATTRS = ("type", "count", "size", "color")
DOMAIN_SIZE = {"type": 5, "count": 4, "size": 4, "color": 4}
TYPE_NAMES = ["triangle", "square", "pentagon", "hexagon", "circle"]
SIZE_SCALE = [0.42, 0.58, 0.74, 0.92]
FILL = [0.0, 0.33, 0.66, 1.0]
ATTR_RU = {"type": "Форма", "count": "Количество", "size": "Размер", "color": "Заливка"}
ARITH_ROWS = [(0, 0, 1), (0, 1, 2), (1, 0, 2), (0, 2, 3), (2, 0, 3), (1, 1, 3)]  # индексы = количество − 1


def _rule_values(rule: str, attr: str, rng: random.Random) -> list[list[int]]:
    n = DOMAIN_SIZE[attr]
    if rule == "global":
        v = rng.randrange(n)
        return [[v] * 3 for _ in range(3)]
    if rule == "row":
        vals = rng.sample(range(n), 3)
        return [[v] * 3 for v in vals]
    if rule == "progression":
        steps = [1, -1] + ([2, -2] if n >= 5 else [])
        step = rng.choice(steps)
        starts = [s for s in range(n) if 0 <= s + 2 * step < n]
        rows = []
        for _ in range(3):
            s = rng.choice(starts)
            rows.append([s, s + step, s + 2 * step])
        return rows
    if rule == "distribute":
        a, b, c = rng.sample(range(n), 3)
        base = [a, b, c]
        shifts = [0, 1, 2] if rng.random() < 0.5 else [0, 2, 1]
        return [[base[(i + sh) % 3] for i in range(3)] for sh in shifts]
    if rule == "arithmetic":
        return [list(rng.choice(ARITH_ROWS)) for _ in range(3)]
    raise ValueError(rule)


def choose_rules(difficulty: int, rng: random.Random) -> dict[str, str]:
    d = max(1, min(6, difficulty))
    varying_n = {1: 1, 2: 2, 3: 2, 4: 3, 5: 3, 6: 4}[d]
    attrs = list(ATTRS)
    rng.shuffle(attrs)
    rules: dict[str, str] = {}
    for i, a in enumerate(attrs):
        if i < varying_n:
            options = ["progression", "distribute"]
            if a == "count" and d >= 5:
                options.append("arithmetic")
            rules[a] = rng.choice(options)
        else:
            rules[a] = "row" if d >= 3 and rng.random() < 0.6 else "global"
    return rules


def make_matrix(difficulty: int, rng: random.Random) -> dict:
    rules = choose_rules(difficulty, rng)
    grids = {a: _rule_values(r, a, rng) for a, r in rules.items()}
    panels = [[{a: grids[a][r][c] for a in ATTRS} for c in range(3)] for r in range(3)]
    answer = dict(panels[2][2])
    options = build_options(answer, grids, rng)
    return {"panels": panels, "answer": answer, "options": options, "rules": rules, "difficulty": difficulty}


def build_options(answer: dict, grids: dict[str, list[list[int]]], rng: random.Random) -> list[dict]:
    """Сбалансированное дерево вариантов: 3 атрибута × 2 значения = 8 вариантов."""
    attrs = list(ATTRS)
    rng.shuffle(attrs)
    chosen = attrs[:3]
    options = [dict(answer)]
    for a in chosen:
        seen = {v for row in grids[a] for v in row} - {answer[a]}
        near = {answer[a] - 1, answer[a] + 1} & set(range(DOMAIN_SIZE[a]))
        pool = sorted((seen | near) - {answer[a]})
        if not pool:
            pool = [v for v in range(DOMAIN_SIZE[a]) if v != answer[a]]
        alt = rng.choice(pool)
        options = options + [{**o, a: alt} for o in options]
    rng.shuffle(options)
    return options


def explain(rules: dict[str, str]) -> str:
    parts = []
    texts = {
        "progression": {
            "type": "число углов меняется на один шаг по строке",
            "count": "количество растёт или убывает по строке",
            "size": "размер меняется по строке",
            "color": "заливка становится светлее или темнее",
        },
        "distribute": "в каждой строке три разных значения, каждое по разу",
        "row": "одинаковая внутри строки",
        "arithmetic": "в третьей колонке — сумма первых двух",
    }
    for a in ATTRS:
        r = rules[a]
        if r == "global":
            continue
        t = texts[r][a] if r == "progression" else texts[r]
        parts.append(f"{ATTR_RU[a]}: {t}")
    return "; ".join(parts) if parts else "Все фигуры одинаковые"


def raven_rating(points: int) -> float:
    return linear_rating(points, 3, 40)


def paint_panel(p: QPainter, rect: QRectF, panel: dict | None, question: bool = False) -> None:
    if panel is None:
        if question:
            draw_text(p, rect, "?", rect.height() * 0.45, T.domain("logic"))
        return
    count = panel["count"] + 1
    slots: list[QRectF]
    w, h = rect.width(), rect.height()
    if count == 1:
        slots = [rect]
    elif count == 2:
        slots = [QRectF(rect.x(), rect.y() + h / 4, w / 2, h / 2), QRectF(rect.x() + w / 2, rect.y() + h / 4, w / 2, h / 2)]
    elif count == 3:
        slots = [QRectF(rect.x() + w / 4, rect.y(), w / 2, h / 2), QRectF(rect.x(), rect.y() + h / 2, w / 2, h / 2),
                 QRectF(rect.x() + w / 2, rect.y() + h / 2, w / 2, h / 2)]
    else:
        slots = [QRectF(rect.x() + (i % 2) * w / 2, rect.y() + (i // 2) * h / 2, w / 2, h / 2) for i in range(4)]
    ink = T.c("text")
    fill = FILL[panel["color"]]
    scale = SIZE_SCALE[panel["size"]]
    kind = TYPE_NAMES[panel["type"]]
    for s in slots:
        side = min(s.width(), s.height()) * scale * 0.86
        sr = QRectF(s.center().x() - side / 2, s.center().y() - side / 2, side, side)
        path = shape_path(kind, sr)
        pen = QPen(ink, max(1.5, side * 0.05))
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        if fill > 0:
            p.setBrush(mix(T.c("surface"), ink, fill))
        else:
            p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)


class MatrixView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.data: dict | None = None
        self.reveal = False
        self.setMinimumSize(300, 300)

    def paintEvent(self, e) -> None:
        if not self.data:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height()) - 4
        x0 = (self.width() - side) / 2
        y0 = (self.height() - side) / 2
        draw_cell(p, QRectF(x0, y0, side, side), T.c("surface"), T.c("border"), 18, 1.2)
        gap = side * 0.025
        cell = (side - gap * 4) / 3
        for r in range(3):
            for c in range(3):
                cr = QRectF(x0 + gap + c * (cell + gap), y0 + gap + r * (cell + gap), cell, cell)
                last = r == 2 and c == 2
                if last:
                    pen = QPen(T.domain("logic"), 2, Qt.PenStyle.DashLine)
                    p.setPen(pen)
                    p.setBrush(T.c("surface2"))
                    p.drawRoundedRect(cr, 12, 12)
                    if self.reveal:
                        paint_panel(p, cr.adjusted(cell * 0.1, cell * 0.1, -cell * 0.1, -cell * 0.1), self.data["answer"])
                    else:
                        paint_panel(p, cr, None, question=True)
                else:
                    draw_cell(p, cr, T.c("surface2"), None, 12)
                    paint_panel(p, cr.adjusted(cell * 0.1, cell * 0.1, -cell * 0.1, -cell * 0.1), self.data["panels"][r][c])


class OptionsView(QWidget):
    chosen = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.options: list[dict] = []
        self.states: dict[int, str] = {}
        self.hover = -1
        self.enabled_input = True
        self.setMouseTracking(True)
        self.setMinimumSize(300, 200)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def rects(self) -> list[QRectF]:
        cols, rows = 4, 2
        gap = 12
        cell = min((self.width() - gap * (cols - 1)) / cols, (self.height() - gap * (rows - 1) - 18) / rows)
        total_w = cols * cell + (cols - 1) * gap
        x0 = (self.width() - total_w) / 2
        y0 = (self.height() - (rows * cell + gap)) / 2
        return [QRectF(x0 + (i % cols) * (cell + gap), y0 + (i // cols) * (cell + gap), cell, cell) for i in range(8)]

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i, (r, opt) in enumerate(zip(self.rects(), self.options)):
            st = self.states.get(i, "")
            border = T.c("border")
            bg = T.c("surface2") if i == self.hover and self.enabled_input else T.c("surface")
            if st == "good":
                border, bg = T.c("success"), mix(T.c("surface"), T.c("success"), 0.18)
            elif st == "bad":
                border, bg = T.c("danger"), mix(T.c("surface"), T.c("danger"), 0.18)
            draw_cell(p, r, bg, border, 12, 2 if st else 1.2)
            inner = r.adjusted(r.width() * 0.12, r.height() * 0.12, -r.width() * 0.12, -r.height() * 0.12)
            paint_panel(p, inner, opt)
            f = font(8, QFont.Weight.Bold)
            f.setPixelSize(11)
            p.setFont(f)
            p.setPen(T.c("faint"))
            p.drawText(QRectF(r.left() + 7, r.top() + 4, 20, 16), Qt.AlignmentFlag.AlignLeft, str(i + 1))

    def mouseMoveEvent(self, e) -> None:
        idx = -1
        for i, r in enumerate(self.rects()):
            if r.contains(e.position()):
                idx = i
        if idx != self.hover:
            self.hover = idx
            self.update()

    def leaveEvent(self, e) -> None:
        self.hover = -1
        self.update()

    def mousePressEvent(self, e) -> None:
        if not self.enabled_input:
            return
        for i, r in enumerate(self.rects()):
            if r.contains(e.position()) and i < len(self.options):
                self.chosen.emit(i)
                return


class RavenGame(GameWidget):
    game_id = "raven"

    def __init__(self, ctx: GameContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.diff = max(1, min(6, self.level))
        self.start_diff = self.diff
        self.index = 0
        self.correct = 0
        self.points = 0
        self.max_solved = 0
        self.diffs: list[int] = []
        self.data: dict | None = None
        self.answered = False
        self.matrix = MatrixView()
        self.opts = OptionsView()
        self.opts.chosen.connect(self.choose)
        self.explain = QLabel("")
        self.explain.setWordWrap(True)
        self.explain.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.explain.setFont(font(11, QFont.Weight.DemiBold))
        self.btn_next = button("Далее  →", "primary", on_click=self.next_problem)
        self.btn_next.setVisible(False)
        self.btn_next.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(24, 8, 24, 20)
        lay.setSpacing(28)
        lay.addWidget(self.matrix, 4)
        right = QVBoxLayout()
        right.setSpacing(12)
        right.addStretch(1)
        right.addWidget(self.opts, 6)
        right.addWidget(self.explain)
        nr = QHBoxLayout()
        nr.addStretch(1)
        nr.addWidget(self.btn_next)
        nr.addStretch(1)
        right.addLayout(nr)
        right.addStretch(1)
        lay.addLayout(right, 6)

    def start(self) -> None:
        self.next_problem()

    def next_problem(self) -> None:
        if not self.alive:
            return
        if self.index >= PROBLEMS:
            self._finish()
            return
        self.data = make_matrix(self.diff, self.rng)
        self.diffs.append(self.diff)
        self.index += 1
        self.answered = False
        self.matrix.data = self.data
        self.matrix.reveal = False
        self.opts.options = self.data["options"]
        self.opts.states = {}
        self.opts.enabled_input = True
        self.matrix.update()
        self.opts.update()
        self.explain.setText("")
        self.btn_next.setVisible(False)
        self.set_hud(f"Сложность {self.diff} из 6", f"Матрица {self.index} из {PROBLEMS}")
        self.progress_changed.emit((self.index - 1) / PROBLEMS)
        self.setFocus()

    def choose(self, i: int) -> None:
        if not self.alive or self.answered or not self.data or i >= len(self.data["options"]):
            return
        self.answered = True
        opts = self.data["options"]
        correct_idx = opts.index(self.data["answer"])
        ok = i == correct_idx
        self.opts.states = {correct_idx: "good"}
        if not ok:
            self.opts.states[i] = "bad"
        self.opts.enabled_input = False
        self.matrix.reveal = True
        self.matrix.update()
        self.opts.update()
        self.feedback(ok)
        col = T.hex("success") if ok else T.hex("danger")
        head = "Верно!" if ok else f"Неверно — правильный вариант {correct_idx + 1}"
        self.explain.setText(f"<span style='color:{col}'>{head}</span><br>"
                             f"<span style='color:{T.hex('muted')}'>{explain(self.data['rules'])}</span>")
        if ok:
            self.correct += 1
            self.points += self.diff
            self.max_solved = max(self.max_solved, self.diff)
            self.diff = min(6, self.diff + 1)
        else:
            self.diff = max(1, self.diff - 1)
        self.btn_next.setVisible(True)
        if self.index >= PROBLEMS:
            self.btn_next.setText("Результаты  →")

    def keyPressEvent(self, e) -> None:
        k = e.key()
        if Qt.Key.Key_1 <= k <= Qt.Key.Key_8:
            self.choose(k - Qt.Key.Key_1)
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space) and self.answered:
            self.next_problem()
        else:
            super().keyPressEvent(e)

    def _finish(self) -> None:
        recent = self.diffs[-3:] or [self.start_diff]
        nl = max(1, min(6, round(sum(recent) / len(recent))))
        self.finish(
            GameResult(
                game=self.game_id,
                score=self.points * 10,
                rating=raven_rating(self.points),
                level=self.start_diff,
                next_level=nl,
                accuracy=self.correct / max(1, self.index),
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


__all__ = ["RavenGame", "make_matrix", "build_options", "choose_rules", "explain", "raven_rating", "QColor", "QPointF"]
