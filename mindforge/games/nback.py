"""Двойной N-назад (Dual N-Back)."""
from __future__ import annotations

import random

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ..core import GameResult, clamp
from ..theme import T, mix
from .base import BigButton, GameContext, GameWidget, draw_cell, draw_text, square_board

SCORED_TRIALS = 20
POSITIONS = [0, 1, 2, 3, 5, 6, 7, 8]  # клетки 3×3 без центральной
STIM_COLORS = ["#EF4444", "#F59E0B", "#FACC15", "#22C55E", "#22D3EE", "#3B82F6", "#A855F7", "#EC4899"]


def generate_block(n: int, rng: random.Random, dual: bool = True, targets: int = 6, both: int = 2,
                   values: int = 8) -> list[dict]:
    """Создаёт последовательность с заданным числом совпадений по каждому каналу."""
    total = SCORED_TRIALS + n
    scorable = list(range(n, total))
    if dual:
        both_idx = set(rng.sample(scorable, both))
        rest = [i for i in scorable if i not in both_idx]
        pos_only = set(rng.sample(rest, targets - both))
        rest2 = [i for i in rest if i not in pos_only]
        snd_only = set(rng.sample(rest2, targets - both))
        pos_t = both_idx | pos_only
        snd_t = both_idx | snd_only
    else:
        pos_t = set(rng.sample(scorable, targets))
        snd_t = set()

    def seq(target_set: set[int]) -> list[int]:
        out: list[int] = []
        for i in range(total):
            if i >= n and i in target_set:
                out.append(out[i - n])
            elif i >= n:
                out.append(rng.choice([v for v in range(values) if v != out[i - n]]))
            else:
                out.append(rng.randrange(values))
        return out

    pos = seq(pos_t)
    snd = seq(snd_t) if dual else [0] * total
    return [
        {"pos": pos[i], "snd": snd[i], "pos_match": i in pos_t, "snd_match": i in snd_t}
        for i in range(total)
    ]


def score_channel(trials: list[dict], responses: list[bool], key: str, n: int) -> dict:
    hits = misses = fa = cr = 0
    for i in range(n, len(trials)):
        target = trials[i][key]
        resp = responses[i]
        if target and resp:
            hits += 1
        elif target:
            misses += 1
        elif resp:
            fa += 1
        else:
            cr += 1
    denom = hits + misses + fa
    acc = hits / denom if denom else 1.0
    return {"hits": hits, "misses": misses, "fa": fa, "cr": cr, "acc": acc}


def next_level(n: int, acc: float, max_n: int = 9) -> int:
    if acc >= 0.8:
        return min(max_n, n + 1)
    if acc < 0.5:
        return max(1, n - 1)
    return n


def effective_level(n: int, acc: float) -> float:
    """Точность 80% = уровень N пройден, 50% = N−1, ниже 50% — пропорционально до нуля."""
    if acc < 0.5:
        return (n - 1) * acc / 0.5
    return min(float(n), n - 1 + (acc - 0.5) / 0.3)


def rating_for(n: int, acc: float, dual: bool) -> float:
    base = (effective_level(n, acc) - 0.5) / 6 * 100
    return clamp(base if dual else base * 0.75)


class Board(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.active: int | None = None
        self.color: QColor | None = None
        self.letter: str = ""
        self.setMinimumSize(300, 300)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height())
        area = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        cells, _ = square_board(area, 3, 3, margin=8, gap_frac=0.08)
        for i, r in enumerate(cells):
            if i == 4:
                c = r.center()
                pen = QPen(T.c("faint"), 3)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                s = r.width() * 0.12
                p.drawLine(c.x() - s, c.y(), c.x() + s, c.y())
                p.drawLine(c.x(), c.y() - s, c.x(), c.y() + s)
                continue
            if i == self.active:
                col = QColor(self.color or T.c("accent"))
                glow = QColor(col)
                glow.setAlpha(70)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(glow)
                p.drawRoundedRect(r.adjusted(-5, -5, 5, 5), r.width() * 0.2, r.width() * 0.2)
                draw_cell(p, r, col, mix(col, QColor("white"), 0.35), None, 2)
                if self.letter:
                    draw_text(p, r, self.letter, r.height() * 0.45, QColor("white"))
            else:
                draw_cell(p, r, T.c("cell"), T.c("border"))


class NBackGame(GameWidget):
    game_id = "nback"

    def __init__(self, ctx: GameContext, parent=None) -> None:
        super().__init__(ctx, parent)
        self.n = max(1, self.level)
        mode = ctx.options.get("stimulus", "voice")
        self.note = ""
        if mode == "voice" and not (ctx.speech and ctx.speech.available):
            mode = "tones"
            self.note = "Синтез речи недоступен — используются ноты."
        self.mode = mode
        self.dual = mode != "none"
        self.letters = ctx.speech.letters() if (ctx.speech and mode == "voice") else []
        self.trials = generate_block(self.n, self.rng, dual=self.dual)
        self.resp_pos = [False] * len(self.trials)
        self.resp_snd = [False] * len(self.trials)
        self.idx = -1

        self.board = Board()
        second = {"voice": "Звук", "tones": "Звук", "color": "Цвет"}.get(mode, "")
        self.btn_pos = BigButton("Позиция", "A")
        self.btn_snd = BigButton(second, "L")
        self.btn_pos.clicked.connect(lambda: self.respond("pos"))
        self.btn_snd.clicked.connect(lambda: self.respond("snd"))
        self.btn_snd.setVisible(self.dual)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 12, 24, 24)
        lay.setSpacing(18)
        lay.addWidget(self.board, 1)
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addStretch(1)
        self.btn_pos.setMaximumWidth(280)
        self.btn_snd.setMaximumWidth(280)
        row.addWidget(self.btn_pos, 2)
        row.addWidget(self.btn_snd, 2)
        row.addStretch(1)
        lay.addLayout(row)

    def start(self) -> None:
        self.set_hud(f"N = {self.n}", "")
        self.next_trial()

    def next_trial(self) -> None:
        if self.idx >= 0:
            self._evaluate(self.idx)
        self.idx += 1
        if self.idx >= len(self.trials):
            self.after(400, self._finish)
            return
        t = self.trials[self.idx]
        self.set_hud(right=f"Ход {self.idx + 1} из {len(self.trials)}")
        self.progress_changed.emit(self.idx / len(self.trials))
        self.board.active = POSITIONS[t["pos"]]
        self.board.color = QColor(STIM_COLORS[t["snd"]]) if self.mode == "color" else None
        self.board.letter = ""
        self.board.update()
        if self.mode == "voice" and self.letters:
            self.ctx.speech.say(self.letters[t["snd"]][1])
        elif self.mode == "tones":
            self.play(f"tone{t['snd']}")
        self.after(800, self._hide)
        self.after(3000, self.next_trial)

    def _hide(self) -> None:
        self.board.active = None
        self.board.update()

    def respond(self, channel: str) -> None:
        if not self.alive or self.idx < 0 or self.idx >= len(self.trials):
            return
        if channel == "snd" and not self.dual:
            return
        arr = self.resp_pos if channel == "pos" else self.resp_snd
        if arr[self.idx]:
            return
        arr[self.idx] = True
        (self.btn_pos if channel == "pos" else self.btn_snd).set_state("active")

    def _evaluate(self, i: int) -> None:
        if i < self.n:
            self.btn_pos.set_state("idle")
            self.btn_snd.set_state("idle")
            return
        t = self.trials[i]
        for btn, key, resp in (
            (self.btn_pos, "pos_match", self.resp_pos[i]),
            (self.btn_snd, "snd_match", self.resp_snd[i]),
        ):
            if key == "snd_match" and not self.dual:
                continue
            if resp:
                btn.set_state("good" if t[key] else "bad", 450)
            elif t[key]:
                btn.set_state("miss", 450)
            else:
                btn.set_state("idle")

    def keyPressEvent(self, e) -> None:
        k = e.key()
        if k in (Qt.Key.Key_A, Qt.Key.Key_Left) or e.text().lower() in ("a", "ф"):
            self.respond("pos")
        elif k in (Qt.Key.Key_L, Qt.Key.Key_Right) or e.text().lower() in ("l", "д"):
            self.respond("snd")
        else:
            super().keyPressEvent(e)

    def _finish(self) -> None:
        sp = score_channel(self.trials, self.resp_pos, "pos_match", self.n)
        ss = score_channel(self.trials, self.resp_snd, "snd_match", self.n) if self.dual else None
        if ss:
            hits = sp["hits"] + ss["hits"]
            denom = hits + sp["misses"] + ss["misses"] + sp["fa"] + ss["fa"]
        else:
            hits = sp["hits"]
            denom = hits + sp["misses"] + sp["fa"]
        acc = hits / denom if denom else 1.0
        nl = next_level(self.n, acc)
        label2 = {"voice": "Звук", "tones": "Ноты", "color": "Цвет"}.get(self.mode, "")
        rows = [["Точность", f"{round(acc * 100)}%"], ["Позиция", f"{round(sp['acc'] * 100)}%"]]
        if ss:
            rows.append([label2, f"{round(ss['acc'] * 100)}%"])
        rows += [
            ["Попадания", str(hits)],
            ["Пропуски", str(sp["misses"] + (ss["misses"] if ss else 0))],
            ["Ложные нажатия", str(sp["fa"] + (ss["fa"] if ss else 0))],
        ]
        verdict = "N повышен!" if nl > self.n else ("N понижен." if nl < self.n else "N остаётся прежним.")
        self.finish(
            GameResult(
                game=self.game_id,
                score=round(acc * 100 * self.n),
                rating=rating_for(self.n, acc, self.dual),
                level=self.n,
                next_level=nl,
                accuracy=acc,
                metrics={
                    "n": self.n,
                    "mode": self.mode,
                    "acc_pos": round(sp["acc"], 3),
                    "acc_snd": round(ss["acc"], 3) if ss else None,
                    "trials": len(self.trials) - self.n,
                    "headline": f"{self.n}-назад · {round(acc * 100)}%",
                    "rows": rows,
                    "note": verdict + (" " + self.note if self.note else ""),
                },
            )
        )

    def on_force_finish(self) -> None:
        self.stop_all()
        self.idx = len(self.trials)
        self._alive = True
        self._finish()


__all__ = ["NBackGame", "generate_block", "score_channel", "next_level", "rating_for", "QFont"]
