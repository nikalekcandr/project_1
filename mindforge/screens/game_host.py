"""Экран упражнения: вступление → обратный отсчёт → игра → результаты."""
from __future__ import annotations

import random

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..catalog import GAME_BY_ID, GameMeta, option_values
from ..context import AppContext
from ..core import DOMAINS, GameResult
from ..games import GAME_ICONS, GAME_WIDGETS, GameContext, GameWidget
from ..progress import level_title
from ..theme import T, font
from ..widgets import icons
from ..widgets.charts import LineChart
from ..widgets.common import (
    Bar,
    Card,
    IconBadge,
    IconView,
    ProgressRing,
    ScrollPage,
    Segmented,
    button,
    clear_layout,
    hbox,
    label,
    vbox,
)


def domain_chip(domain: str) -> QLabel:
    lb = QLabel(DOMAINS.get(domain, domain))
    col = T.domain(domain)
    bg = QColor(col)
    bg.setAlpha(38)
    lb.setStyleSheet(
        f"color:{col.name()}; background: rgba({bg.red()},{bg.green()},{bg.blue()},{bg.alpha()});"
        "border-radius:9px; padding:3px 10px; font-weight:700; font-size:8.5pt;"
    )
    lb.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return lb


def verdict(rating: float) -> str:
    if rating >= 85:
        return "Великолепно!"
    if rating >= 70:
        return "Отлично!"
    if rating >= 50:
        return "Хорошая работа!"
    if rating >= 30:
        return "Неплохо!"
    return "Главное — регулярность!"


class CountdownOverlay(QWidget):
    done = Signal()

    def __init__(self, parent: QWidget, sound=None) -> None:
        super().__init__(parent)
        self.sound = sound
        self.value = 3
        self._t = 0.0
        self.anim = QPropertyAnimation(self, b"t", self)
        self.anim.setDuration(650)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.finished.connect(self._next)
        self.hide()

    def _get(self) -> float:
        return self._t

    def _set(self, v: float) -> None:
        self._t = v
        self.update()

    t = Property(float, _get, _set)

    def run(self, fast: bool = False) -> None:
        self.value = 3
        self.anim.setDuration(20 if fast else 650)
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self._beep()
        self.anim.start()

    def _beep(self) -> None:
        if self.sound:
            self.sound.play("tick" if self.value > 0 else "go")

    def _next(self) -> None:
        self.value -= 1
        if self.value < 0:
            self.hide()
            self.done.emit()
            return
        self._beep()
        self.anim.start()

    def stop(self) -> None:
        self.anim.stop()
        self.hide()

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = T.c("bg")
        bg.setAlpha(235)
        p.fillRect(self.rect(), bg)
        text = str(self.value) if self.value > 0 else "Старт!"
        scale = 1.4 - 0.4 * self._t
        col = QColor(T.c("accent") if self.value > 0 else T.c("success"))
        col.setAlphaF(max(0.0, 1.0 - self._t * 0.6))
        f = font(10, QFont.Weight.Black)
        f.setPixelSize(int((110 if self.value > 0 else 72) * scale))
        p.setFont(f)
        p.setPen(col)
        p.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, text)


class IntroPage(ScrollPage):
    start_clicked = Signal()
    back_clicked = Signal()

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(max_width=900)
        self.ctx = ctx
        self.meta: GameMeta | None = None
        self.options: dict[str, str] = {}

    def load(self, meta: GameMeta, queue_info: str = "") -> None:
        self.meta = meta
        clear_layout(self.body_lay)
        st = self.ctx.storage
        self.options = option_values(meta, st.game_options(meta.id))

        back = button("Назад", "ghost", icon_name="arrow_left", on_click=self.back_clicked.emit,
                      icon_color=T.hex("muted"))
        top = [back, "stretch"]
        if queue_info:
            q = label(queue_info, "chip")
            top.append(q)
        self.body_lay.addLayout(hbox(*top))

        card = Card(padding=32, accent=T.domain(meta.domain))
        card.lay.setSpacing(16)
        badge = IconBadge(GAME_ICONS.get(meta.id, "brain"), T.domain(meta.domain), 72)
        title = label(meta.title, "h1")
        tagline = label(meta.tagline, "muted")
        tagline.setFont(font(12))
        card.lay.addLayout(hbox(badge, vbox(title, tagline, spacing=2), "stretch", domain_chip(meta.domain),
                                spacing=18))
        desc = label(meta.description, wrap=True)
        desc.setFont(font(11.5))
        card.lay.addWidget(desc)

        how = label("Как играть", "h3")
        card.lay.addWidget(how)
        for line in meta.howto:
            dot = IconView("check", T.domain(meta.domain), 18)
            t = label(line, wrap=True)
            t.setFont(font(10.5))
            card.lay.addLayout(hbox(dot, t, spacing=10))
        if meta.keys:
            card.lay.addLayout(hbox(IconView("keyboard", T.c("muted"), 18), label(meta.keys, "muted"), "stretch"))

        if meta.options:
            grid = QGridLayout()
            grid.setHorizontalSpacing(16)
            grid.setVerticalSpacing(10)
            for i, opt in enumerate(meta.options):
                seg = Segmented(opt.choices, self.options[opt.key])
                seg.changed.connect(lambda v, k=opt.key: self._set_option(k, v))
                grid.addWidget(label(opt.label, "muted"), i, 0)
                grid.addWidget(seg, i, 1)
            card.lay.addSpacing(4)
            card.lay.addLayout(grid)
            if meta.id == "nback" and not self.ctx.speech.available:
                card.lay.addWidget(label("Синтез речи не найден — в режиме «Голос» будут звучать ноты.", "faint"))

        info = []
        if meta.leveled:
            lvl = st.game_level(meta.id)
            info.append(label(f"Уровень {lvl} из {meta.max_level}", "chip"))
        best = st.best_result(meta.id, "rating")
        if best:
            info.append(label(f"Рекорд: {best['metrics'].get('headline', round(best['rating']))}", "chip"))
        info.append(label(f"≈ {meta.minutes:g} мин", "chip"))
        card.lay.addLayout(hbox(*info, "stretch", spacing=8))

        if meta.science:
            sci = label(meta.science, "muted", wrap=True)
            sci.setFont(font(9.5))
            card.lay.addLayout(hbox(IconView("info", T.c("muted"), 18), sci, spacing=10))

        start = button("Начать", "primary", "lg", icon_name="play", on_click=self.start_clicked.emit)
        hint = label("или нажмите Enter", "faint")
        card.lay.addSpacing(6)
        card.lay.addLayout(hbox(start, hint, "stretch", spacing=14))
        self.body_lay.addWidget(card)
        self.body_lay.addStretch(1)
        self.verticalScrollBar().setValue(0)

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.start_clicked.emit()
        else:
            super().keyPressEvent(e)

    def _set_option(self, key: str, value: str) -> None:
        self.options[key] = value
        if self.meta:
            self.ctx.storage.set_game_options(self.meta.id, dict(self.options))


class PlayPage(QWidget):
    exit_clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 14, 20, 12)
        lay.setSpacing(8)
        self.btn_exit = button("Выйти", "ghost", icon_name="close", on_click=self.exit_clicked.emit,
                               icon_color=T.hex("muted"))
        self.title = label("", "h3")
        self.hud_left = label("")
        self.hud_left.setFont(font(12, QFont.Weight.DemiBold))
        self.hud_right = label("")
        self.hud_right.setFont(font(13, QFont.Weight.Bold))
        self.hud_right.setMinimumWidth(120)
        self.hud_right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(hbox(self.btn_exit, self.title, "stretch", self.hud_left, "stretch", self.hud_right,
                           spacing=14))
        self.bar = Bar(5)
        lay.addWidget(self.bar)
        self.area = QWidget()
        self.area_lay = QVBoxLayout(self.area)
        self.area_lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.area, 1)
        self.overlay: CountdownOverlay | None = None

    def set_hud(self, left: str, right: str) -> None:
        self.hud_left.setText(left)
        self.hud_right.setText(right)

    def set_progress(self, v: float) -> None:
        if v < 0:
            self.bar.setVisible(False)
        else:
            self.bar.setVisible(True)
            self.bar.set_value(v, animate=False)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if self.overlay is not None and self.overlay.isVisible():
            self.overlay.setGeometry(self.area.rect())


class ResultPage(ScrollPage):
    again_clicked = Signal()
    next_clicked = Signal()
    back_clicked = Signal()

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(max_width=900)
        self.ctx = ctx
        self.has_next = False

    def load(self, meta: GameMeta, result: GameResult, outcome, next_title: str | None, queue_done: bool) -> None:
        clear_layout(self.body_lay)
        self.has_next = bool(next_title)
        col = T.domain(meta.domain)
        head = label(verdict(result.rating), "h1")
        sub = label(meta.title, "muted")
        sub.setFont(font(12))
        self.body_lay.addLayout(vbox(head, sub, spacing=2))

        top = Card(padding=28, accent=col)
        ring = ProgressRing(150, 12)
        ring.text = f"{round(result.rating)}"
        ring.subtext = "из 100"
        ring.color = col
        ring.set_value(result.rating / 100)
        headline = label(str(result.metrics.get("headline", result.score)))
        headline.setFont(font(24, QFont.Weight.Bold))
        badges = []
        if outcome.new_best:
            badges.append(self._badge("Новый рекорд!", "star", T.c("warning")))
        if meta.leveled and outcome.game_level_after != outcome.game_level_before:
            up = outcome.game_level_after > outcome.game_level_before
            badges.append(self._badge(
                f"Уровень {outcome.game_level_before} → {outcome.game_level_after}",
                "trend" if up else "refresh", T.c("success") if up else T.c("muted")))
        badges.append(self._badge(f"+{outcome.xp} XP", "sparkles", T.c("accent")))
        info = vbox(label("Результат", "muted"), headline, hbox(*badges, "stretch", spacing=8), "stretch", spacing=6)
        top.lay.addLayout(hbox(ring, info, spacing=28))
        self.body_lay.addWidget(top)

        rows = result.metrics.get("rows") or []
        if rows:
            grid_card = Card(padding=22)
            grid = QGridLayout()
            grid.setHorizontalSpacing(30)
            grid.setVerticalSpacing(12)
            for i, (k, v) in enumerate(rows):
                r, c = divmod(i, 2)
                kl = label(k, "muted")
                vl = label(v)
                vl.setFont(font(12, QFont.Weight.Bold))
                grid.addLayout(vbox(kl, vl, spacing=2), r, c)
            grid_card.lay.addLayout(grid)
            note = result.metrics.get("note")
            if note:
                nl = label(note, "muted", wrap=True)
                grid_card.lay.addSpacing(6)
                grid_card.lay.addLayout(hbox(IconView("info", T.c("muted"), 18), nl, spacing=10))
            self.body_lay.addWidget(grid_card)

        hist = list(reversed(self.ctx.storage.results(meta.id, limit=15)))
        if len(hist) >= 2:
            chart_card = Card(padding=20)
            chart_card.lay.addWidget(label("Динамика оценки", "h3"))
            chart = LineChart(height=170)
            pts = [(f"#{i + 1}", r["rating"]) for i, r in enumerate(hist)]
            chart.set_data(pts, 0, 100, col)
            chart_card.lay.addWidget(chart)
            self.body_lay.addWidget(chart_card)

        btns = [button("Ещё раз", None, "lg", icon_name="refresh", on_click=self.again_clicked.emit)]
        if next_title:
            btns.append(button(f"Далее: {next_title}", "primary", "lg", icon_name="arrow_right",
                               on_click=self.next_clicked.emit))
        elif queue_done:
            btns.append(button("Завершить тренировку", "primary", "lg", icon_name="check",
                               on_click=self.back_clicked.emit))
        else:
            btns.append(button("К упражнениям", "primary", "lg", icon_name="grid", on_click=self.back_clicked.emit))
        self.body_lay.addLayout(hbox("stretch", *btns, spacing=12))
        self.body_lay.addStretch(1)
        self.verticalScrollBar().setValue(0)

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            (self.next_clicked if self.has_next else self.again_clicked).emit()
        else:
            super().keyPressEvent(e)

    @staticmethod
    def _badge(text: str, icon_name: str, color: QColor) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(10, 4, 12, 4)
        lay.setSpacing(6)
        lay.addWidget(IconView(icon_name, color, 16))
        t = QLabel(text)
        t.setStyleSheet(f"color:{color.name()}; font-weight:700;")
        lay.addWidget(t)
        bg = QColor(color)
        w.setObjectName("badge")
        w.setStyleSheet(
            f"QWidget#badge {{ background: rgba({bg.red()},{bg.green()},{bg.blue()},36); border-radius: 12px; }}"
        )
        return w


class GameHost(QWidget):
    closed = Signal()

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.meta: GameMeta | None = None
        self.game: GameWidget | None = None
        self.queue: list[str] = []
        self.queue_pos = 0
        self.fast = False
        self.stack = QStackedWidget()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.stack)
        self.intro = IntroPage(ctx)
        self.play_page = PlayPage()
        self.result_page = ResultPage(ctx)
        for w in (self.intro, self.play_page, self.result_page):
            self.stack.addWidget(w)
        self.intro.start_clicked.connect(self.start_game)
        self.intro.back_clicked.connect(self.close_host)
        self.play_page.exit_clicked.connect(self.request_exit)
        self.result_page.again_clicked.connect(self.again)
        self.result_page.next_clicked.connect(self.next_in_queue)
        self.result_page.back_clicked.connect(self.close_host)
        self.last_result: GameResult | None = None
        esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        esc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        esc.activated.connect(self.request_exit)

    # ------------------------------------------------------------ навигация
    def open(self, game_id: str, queue: list[str] | None = None, pos: int = 0) -> None:
        self.queue = list(queue or [])
        self.queue_pos = pos
        self._open_intro(game_id)

    def _open_intro(self, game_id: str) -> None:
        self._teardown()
        self.meta = GAME_BY_ID[game_id]
        info = f"Тренировка дня · {self.queue_pos + 1} из {len(self.queue)}" if self.queue else ""
        self.intro.load(self.meta, info)
        self.stack.setCurrentWidget(self.intro)
        self.intro.setFocus()

    def close_host(self) -> None:
        self._teardown()
        self.closed.emit()

    def request_exit(self) -> None:
        if self.stack.currentWidget() is self.play_page and self.game is not None and not self.game._done:
            box = QMessageBox(self)
            box.setWindowTitle("Прервать упражнение?")
            box.setText("Прервать упражнение?\nРезультат этой попытки не будет сохранён.")
            yes = box.addButton("Прервать", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Продолжить", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if self.stack.currentWidget() is not self.play_page:
                return  # упражнение успело завершиться, пока открыт диалог
            if box.clickedButton() is not yes:
                if self.game:
                    self.game.setFocus()
                return
            self._teardown()
            self._open_intro(self.meta.id)
        elif self.stack.currentWidget() is self.intro:
            self.close_host()
        else:
            self.close_host()

    def _teardown(self) -> None:
        if self.play_page.overlay is not None:
            self.play_page.overlay.stop()
            self.play_page.overlay.deleteLater()
            self.play_page.overlay = None
        if self.game is not None:
            self.game.abort()
            self.game.setParent(None)
            self.game.deleteLater()
            self.game = None

    # ----------------------------------------------------------------- игра
    def start_game(self) -> None:
        if self.meta is None:
            return
        self._teardown()
        st = self.ctx.storage
        level = st.game_level(self.meta.id) if self.meta.leveled else 1
        gctx = GameContext(
            level=level,
            options=option_values(self.meta, st.game_options(self.meta.id)),
            sound=self.ctx.sound,
            speech=self.ctx.speech,
            rng=random.Random(),
            fast=self.fast,
        )
        game = GAME_WIDGETS[self.meta.id](gctx)
        game.hud_changed.connect(self.play_page.set_hud)
        game.progress_changed.connect(self.play_page.set_progress)
        game.finished.connect(self.on_finished)
        self.game = game
        self.play_page.title.setText(self.meta.title)
        self.play_page.set_hud("", "")
        self.play_page.set_progress(-1)
        self.play_page.area_lay.addWidget(game)
        self.stack.setCurrentWidget(self.play_page)
        overlay = CountdownOverlay(self.play_page.area, self.ctx.sound)
        overlay.done.connect(self._begin)
        self.play_page.overlay = overlay
        QTimer.singleShot(0, lambda: overlay.run(self.fast))

    def _begin(self) -> None:
        if self.game is not None:
            self.game.begin()

    def on_finished(self, result: GameResult) -> None:
        self.last_result = result
        prog = self.ctx.progress
        outcome = prog.record(result)
        next_title = None
        queue_done = False
        if self.queue:
            if self.queue_pos + 1 < len(self.queue):
                next_title = GAME_BY_ID[self.queue[self.queue_pos + 1]].title
            else:
                queue_done = True
        QTimer.singleShot(0, self._teardown)
        self.result_page.load(self.meta, result, outcome, next_title, queue_done)
        self.stack.setCurrentWidget(self.result_page)
        self.result_page.setFocus()
        self.ctx.data_changed.emit()
        if outcome.plan_completed:
            self.ctx.toast("Тренировка дня выполнена!", "Бонус +60 XP. Возвращайтесь завтра, чтобы продлить серию.",
                           "calendar", T.c("success"))
        if outcome.player_level_after > outcome.player_level_before:
            lvl = outcome.player_level_after
            self.ctx.toast(f"Новый уровень: {lvl}", f"Ваше звание — «{level_title(lvl)}»", "trophy", T.c("accent"))
            self.ctx.sound.play("levelup")
        self.ctx.announce_achievements(outcome.achievements)

    def again(self) -> None:
        self.start_game()

    def next_in_queue(self) -> None:
        if self.queue and self.queue_pos + 1 < len(self.queue):
            self.queue_pos += 1
            self._open_intro(self.queue[self.queue_pos])
        else:
            self.close_host()

    # -------------------------------------------------------------- клавиши
    def handle_key(self, key: int) -> bool:
        cur = self.stack.currentWidget()
        if key == Qt.Key.Key_Escape:
            self.request_exit()
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if cur is self.intro:
                self.start_game()
                return True
        return False


__all__ = ["GameHost", "domain_chip", "QKeySequence", "QShortcut", "icons"]
