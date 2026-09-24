"""Карточки с интервальными повторениями."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import srs
from ..context import AppContext
from ..core import plural
from ..data.decks import STARTER_DECKS
from ..theme import T, font
from ..widgets.common import (
    Bar,
    Card,
    IconBadge,
    ResponsiveGrid,
    ScrollPage,
    button,
    clear_layout,
    hbox,
    label,
    vbox,
)


class Dialog(QDialog):
    def __init__(self, parent, title: str, width: int = 520) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(width)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(24, 22, 24, 22)
        self.lay.setSpacing(12)
        self.lay.addWidget(label(title, "h2"))


class AddCardsDialog(Dialog):
    def __init__(self, parent, ctx: AppContext, deck_id: int) -> None:
        super().__init__(parent, "Новые карточки")
        self.ctx, self.deck_id, self.added = ctx, deck_id, 0
        self.front = QPlainTextEdit()
        self.front.setPlaceholderText("Вопрос / слово / термин")
        self.front.setFixedHeight(80)
        self.back = QPlainTextEdit()
        self.back.setPlaceholderText("Ответ / перевод / определение")
        self.back.setFixedHeight(80)
        self.status = label("", "muted")
        self.lay.addWidget(label("Лицевая сторона", "muted"))
        self.lay.addWidget(self.front)
        self.lay.addWidget(label("Обратная сторона", "muted"))
        self.lay.addWidget(self.back)
        self.lay.addWidget(self.status)
        add = button("Добавить", "primary", icon_name="plus", on_click=self.add)
        done = button("Готово", None, on_click=self.accept)
        self.lay.addLayout(hbox(label("Ctrl+Enter — добавить", "faint"), "stretch", done, add))
        sc = QShortcut(QKeySequence("Ctrl+Return"), self)
        sc.activated.connect(self.add)
        self.front.setFocus()

    def add(self) -> None:
        f, b = self.front.toPlainText().strip(), self.back.toPlainText().strip()
        if not f or not b:
            self.status.setText("Заполните обе стороны карточки")
            return
        self.ctx.storage.add_cards(self.deck_id, [(f, b)])
        self.added += 1
        self.status.setText(f"Добавлено карточек: {self.added}")
        self.front.clear()
        self.back.clear()
        self.front.setFocus()


class ImportDialog(Dialog):
    def __init__(self, parent, ctx: AppContext, deck_id: int) -> None:
        super().__init__(parent, "Импорт карточек", 620)
        self.ctx, self.deck_id = ctx, deck_id
        self.lay.addWidget(label("Вставьте текст: одна карточка на строку, вопрос и ответ разделены "
                                 "точкой с запятой, табуляцией, « — » или «=».", "muted", wrap=True))
        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText("apple; яблоко\nСтолица Франции — Париж\n2^10 = 1024")
        self.edit.setMinimumHeight(260)
        self.edit.textChanged.connect(self._preview)
        self.lay.addWidget(self.edit)
        self.status = label("Найдено карточек: 0", "muted")
        self.btn = button("Импортировать", "primary", icon_name="upload", on_click=self._do)
        self.lay.addLayout(hbox(self.status, "stretch", button("Отмена", None, on_click=self.reject), self.btn))

    def _preview(self) -> None:
        self.status.setText(f"Найдено карточек: {len(srs.parse_import(self.edit.toPlainText()))}")

    def _do(self) -> None:
        pairs = srs.parse_import(self.edit.toPlainText())
        if not pairs:
            self.status.setText("Не удалось распознать ни одной карточки")
            return
        self.ctx.storage.add_cards(self.deck_id, pairs)
        self.accept()


class BrowseDialog(Dialog):
    def __init__(self, parent, ctx: AppContext, deck_id: int, deck_name: str) -> None:
        super().__init__(parent, f"Колода «{deck_name}»", 760)
        self.ctx, self.deck_id = ctx, deck_id
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Вопрос", "Ответ", "Повторение", "Интервал"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setMinimumHeight(380)
        self.table.cellDoubleClicked.connect(self._edit)
        self.lay.addWidget(self.table)
        self.lay.addLayout(hbox(label("Двойной клик — редактировать", "faint"), "stretch",
                                button("Удалить выбранные", "danger", icon_name="trash", on_click=self._delete,
                                       icon_color=T.hex("danger")),
                                button("Закрыть", None, on_click=self.accept)))
        self._load()

    def _load(self) -> None:
        self.cards = self.ctx.storage.cards(self.deck_id)
        self.table.setRowCount(len(self.cards))
        now = self.ctx.storage.now()
        for i, c in enumerate(self.cards):
            if c["last_review"] is None:
                when = "новая"
            elif c["due"] <= now:
                when = "сейчас"
            else:
                when = datetime.fromtimestamp(c["due"]).strftime("%d.%m.%Y")
            ivl = f"{c['interval']:.0f} дн" if c["interval"] >= 1 else "—"
            for j, v in enumerate((c["front"], c["back"], when, ivl)):
                self.table.setItem(i, j, QTableWidgetItem(v))

    def _edit(self, row: int, _col: int) -> None:
        c = self.cards[row]
        f, ok = QInputDialog.getText(self, "Редактирование", "Вопрос:", QLineEdit.EchoMode.Normal, c["front"])
        if not ok:
            return
        b, ok = QInputDialog.getText(self, "Редактирование", "Ответ:", QLineEdit.EchoMode.Normal, c["back"])
        if ok and f.strip() and b.strip():
            self.ctx.storage.edit_card(c["id"], f, b)
            self._load()

    def _delete(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Удалить карточки")
        box.setText(f"Удалить карточек: {len(rows)}?")
        yes = box.addButton("Удалить", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not yes:
            return
        for r in rows:
            self.ctx.storage.delete_card(self.cards[r]["id"])
        self._load()


class ReviewView(QWidget):
    finished = Signal()

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.setObjectName("Page")
        self.ctx = ctx
        self.queue: list[dict] = []
        self.card: dict | None = None
        self.revealed = False
        self.reviewed = 0
        self.again_count = 0
        self.deck_name = ""
        self.initial = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(36, 22, 36, 30)
        lay.setSpacing(16)
        self.btn_back = button("Колоды", "ghost", icon_name="arrow_left", icon_color=T.hex("muted"),
                               on_click=self.finish)
        self.title = label("", "h3")
        self.counter = label("", "muted")
        lay.addLayout(hbox(self.btn_back, self.title, "stretch", self.counter, spacing=14))
        self.bar = Bar(6)
        lay.addWidget(self.bar)
        self.card_box = Card(padding=36, accent=T.domain("memory"))
        self.front = QLabel("")
        self.front.setWordWrap(True)
        self.front.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.front.setFont(font(22, QFont.Weight.Bold))
        self.sep = QWidget()
        self.sep.setFixedHeight(1)
        self.sep.setStyleSheet(f"background:{T.hex('border')};")
        self.back = QLabel("")
        self.back.setWordWrap(True)
        self.back.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.back.setFont(font(18, QFont.Weight.DemiBold))
        self.back.setStyleSheet(f"color:{T.domain('memory').name()};")
        self.card_box.lay.addStretch(1)
        self.card_box.lay.addWidget(self.front)
        self.card_box.lay.addSpacing(10)
        self.card_box.lay.addWidget(self.sep)
        self.card_box.lay.addSpacing(10)
        self.card_box.lay.addWidget(self.back)
        self.card_box.lay.addStretch(1)
        self.card_box.setMinimumHeight(320)
        lay.addWidget(self.card_box, 1)

        self.btn_show = button("Показать ответ", "primary", "lg", on_click=self.reveal)
        self.show_row = QWidget()
        self.show_row.setLayout(hbox("stretch", self.btn_show, label("Пробел", "faint"), "stretch", spacing=12))
        lay.addWidget(self.show_row)
        self.grade_row = QWidget()
        gl = QHBoxLayout(self.grade_row)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(12)
        gl.addStretch(1)
        self.grade_btns = {}
        colors = {1: T.hex("danger"), 2: T.hex("warning"), 3: T.hex("success"), 4: T.hex("accent2")}
        for g in (1, 2, 3, 4):
            b = button("", None, "lg", on_click=lambda _=False, g=g: self.grade(g))
            b.setMinimumWidth(150)
            b.setStyleSheet(f"QPushButton {{ border-bottom: 3px solid {colors[g]}; }}")
            self.grade_btns[g] = b
            gl.addWidget(b)
        gl.addStretch(1)
        lay.addWidget(self.grade_row)
        for b in [self.btn_back, self.btn_show, *self.grade_btns.values()]:
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.hint = label("Оцените, насколько легко вспомнили: клавиши 1–4", "faint", align=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.hint)
        self.done_box = QWidget()
        dl = QVBoxLayout(self.done_box)
        self.done_title = label("", "h2", align=Qt.AlignmentFlag.AlignCenter)
        self.done_text = label("", "muted", wrap=True, align=Qt.AlignmentFlag.AlignCenter)
        dl.addWidget(self.done_title)
        dl.addWidget(self.done_text)
        dl.addLayout(hbox("stretch", button("Вернуться к колодам", "primary", on_click=self.finish), "stretch"))
        lay.addWidget(self.done_box)

    def start(self, deck_id: int, deck_name: str) -> None:
        self.deck_name = deck_name
        self.queue = self.ctx.storage.due_cards(deck_id)
        self.initial = len(self.queue)
        self.reviewed = 0
        self.again_count = 0
        self.title.setText(deck_name)
        self.next_card()
        self.setFocus()

    def next_card(self) -> None:
        self.revealed = False
        if not self.queue:
            self.card = None
            self.card_box.setVisible(False)
            self.show_row.setVisible(False)
            self.grade_row.setVisible(False)
            self.hint.setVisible(False)
            self.done_box.setVisible(True)
            self.done_title.setText("На сегодня всё!" if self.reviewed else "Нет карточек к повторению")
            self.done_text.setText(
                f"Повторено: {self.reviewed}. Интервалы подобраны так, чтобы вы повторяли каждую карточку "
                "прямо перед тем, как начнёте её забывать." if self.reviewed else
                "Добавьте новые карточки или загляните позже."
            )
            self.counter.setText("")
            self.bar.set_value(1)
            self.ctx.sound.play("finish" if self.reviewed else "click")
            return
        self.done_box.setVisible(False)
        self.card_box.setVisible(True)
        self.card = self.queue.pop(0)
        self.front.setText(self.card["front"])
        self.back.setText("")
        self.sep.setVisible(False)
        self.show_row.setVisible(True)
        self.grade_row.setVisible(False)
        self.hint.setVisible(False)
        left = len(self.queue) + 1
        self.counter.setText(f"Осталось: {left}")
        total = max(1, self.initial + self.again_count)
        self.bar.set_value(self.reviewed / total)

    def reveal(self) -> None:
        if not self.card or self.revealed:
            return
        self.revealed = True
        self.ctx.sound.play("flip")
        self.back.setText(self.card["back"])
        self.sep.setVisible(True)
        self.show_row.setVisible(False)
        prev = srs.preview(self.card, self.ctx.storage.now())
        for g, b in self.grade_btns.items():
            b.setText(f"{g}  {srs.GRADE_LABELS[g]}  ·  {prev[g]}")
        self.grade_row.setVisible(True)
        self.hint.setVisible(True)

    def grade(self, g: int) -> None:
        if not self.card or not self.revealed:
            return
        now = self.ctx.storage.now()
        updated = srs.schedule(self.card, g, now)
        self.ctx.storage.update_card_schedule(updated, g)
        achs = self.ctx.progress.record_review()
        self.ctx.announce_achievements(achs)
        self.reviewed += 1
        if g == 1:
            self.again_count += 1
            self.queue.append(updated)
        self.ctx.sound.play("click" if g > 1 else "wrong")
        self.next_card()

    def keyPressEvent(self, e) -> None:
        k = e.key()
        if k in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter) and not self.revealed:
            self.reveal()
        elif Qt.Key.Key_1 <= k <= Qt.Key.Key_4 and self.revealed:
            self.grade(k - Qt.Key.Key_0)
        elif k == Qt.Key.Key_Escape:
            self.finish()
        else:
            super().keyPressEvent(e)

    def finish(self) -> None:
        self.finished.emit()


class FlashcardsPage(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.stack = QStackedWidget()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.stack)
        self.list_page = ScrollPage()
        self.review = ReviewView(ctx)
        self.review.finished.connect(self._back_from_review)
        self.stack.addWidget(self.list_page)
        self.stack.addWidget(self.review)
        ctx.data_changed.connect(self._maybe_refresh)
        self.refresh()

    def _maybe_refresh(self) -> None:
        if self.stack.currentWidget() is self.list_page:
            self.refresh()

    def refresh(self) -> None:
        body = self.list_page.body_lay
        clear_layout(body)
        st = self.ctx.storage
        new_btn = button("Новая колода", "primary", icon_name="plus", on_click=self.new_deck)
        starter = button("Готовые колоды", None, icon_name="cards_stack", on_click=self.starter_menu)
        self.starter_btn = starter
        head = hbox(spacing=10)
        head.addLayout(vbox(label("Карточки", "h1"),
                            label("Интервальные повторения: алгоритм сам решает, когда показать карточку, "
                                  "чтобы она перешла в долговременную память.", "muted", wrap=True),
                            spacing=4), 1)
        head.addWidget(starter, 0, Qt.AlignmentFlag.AlignTop)
        head.addWidget(new_btn, 0, Qt.AlignmentFlag.AlignTop)
        body.addLayout(head)
        decks = st.decks()
        if not decks:
            empty = Card(padding=36)
            empty.lay.addWidget(IconBadge("cards", T.domain("memory"), 64), 0, Qt.AlignmentFlag.AlignHCenter)
            empty.lay.addWidget(label("Пока нет ни одной колоды", "h2", align=Qt.AlignmentFlag.AlignCenter))
            empty.lay.addWidget(label("Создайте свою колоду (слова, формулы, даты, термины) или начните с готовой.",
                                      "muted", wrap=True, align=Qt.AlignmentFlag.AlignCenter))
            empty.lay.addLayout(hbox("stretch", button("Добавить готовую колоду", None, icon_name="cards_stack",
                                                       on_click=self.starter_menu),
                                     button("Создать колоду", "primary", icon_name="plus", on_click=self.new_deck),
                                     "stretch", spacing=10))
            body.addWidget(empty)
        else:
            grid = ResponsiveGrid(320, 16)
            items = []
            for d in decks:
                items.append(self._deck_card(d))
            grid.set_items(items)
            body.addWidget(grid)
        how = Card(padding=22, tint=T.hex("accent2"))
        how.lay.addWidget(label("Как это работает", "h3"))
        for t in (
            "Посмотрите на вопрос и постарайтесь вспомнить ответ, прежде чем открыть его.",
            "Честно оцените себя: «Снова», «Трудно», «Хорошо» или «Легко».",
            "Чем легче вспомнили, тем дольше интервал до следующего показа: 1 день → 3 дня → неделя → месяц…",
            "Повторяйте карточки каждый день — даже 5 минут дают отличный результат.",
        ):
            how.lay.addWidget(label("•  " + t, "muted", wrap=True))
        body.addWidget(how)
        body.addStretch(1)

    def _deck_card(self, d: dict) -> Card:
        c = Card(padding=20, accent=T.domain("memory"))
        title = label(d["name"])
        title.setFont(font(13, QFont.Weight.Bold))
        more = button("", "ghost", "sm", icon_name="list", icon_color=T.hex("muted"))
        more.setToolTip("Действия с колодой")
        more.clicked.connect(lambda _=False, d=d, b=more: self.deck_menu(d, b))
        c.lay.addLayout(hbox(IconBadge("cards", T.domain("memory"), 40), title, "stretch", more, spacing=12))
        stats = [
            label(f"Всего: {d['total']}", "chip"),
            label(f"Новых: {d['new']}", "chip"),
            label(f"К повторению: {d['due']}", "chip"),
        ]
        c.lay.addLayout(hbox(*stats, "stretch", spacing=6))
        todo = d["due"] + min(d["new"], 20)
        learn = button(f"Учить ({todo})" if todo else "Всё повторено", "primary" if todo else None,
                       icon_name="play" if todo else "check", on_click=lambda _=False, d=d: self.study(d))
        learn.setEnabled(bool(todo))
        add = button("Добавить", None, icon_name="plus", on_click=lambda _=False, d=d: self.add_cards(d))
        c.lay.addLayout(hbox(learn, add, "stretch", spacing=8))
        return c

    # ------------------------------------------------------------ действия
    def new_deck(self) -> None:
        name, ok = QInputDialog.getText(self, "Новая колода", "Название колоды:")
        if ok and name.strip():
            deck_id = self.ctx.storage.create_deck(name)
            self.refresh()
            self.add_cards({"id": deck_id, "name": name})

    def starter_menu(self) -> None:
        menu = QMenu(self)
        existing = {d["name"] for d in self.ctx.storage.decks()}
        for name, text in STARTER_DECKS.items():
            n = len(srs.parse_import(text))
            act = menu.addAction(f"{name}  ({n} {plural(n, 'карточка', 'карточки', 'карточек')})")
            act.setEnabled(name not in existing)
            act.triggered.connect(lambda _=False, name=name, text=text: self.add_starter(name, text))
        btn = self.starter_btn
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def add_starter(self, name: str, text: str) -> None:
        deck_id = self.ctx.storage.create_deck(name)
        n = self.ctx.storage.add_cards(deck_id, srs.parse_import(text))
        self.ctx.toast("Колода добавлена", f"«{name}» — {n} карточек. Новые карточки выдаются по 20 в день.",
                       "cards", T.domain("memory"))
        self.refresh()
        self.ctx.data_changed.emit()

    def deck_menu(self, d: dict, anchor: QWidget) -> None:
        menu = QMenu(self)
        menu.addAction("Список карточек", lambda: self.browse(d))
        menu.addAction("Импорт из текста", lambda: self.import_cards(d))
        menu.addAction("Переименовать", lambda: self.rename(d))
        menu.addSeparator()
        menu.addAction("Удалить колоду", lambda: self.delete(d))
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def add_cards(self, d: dict) -> None:
        AddCardsDialog(self, self.ctx, d["id"]).exec()
        self.refresh()

    def import_cards(self, d: dict) -> None:
        if ImportDialog(self, self.ctx, d["id"]).exec():
            self.refresh()

    def browse(self, d: dict) -> None:
        BrowseDialog(self, self.ctx, d["id"], d["name"]).exec()
        self.refresh()

    def rename(self, d: dict) -> None:
        name, ok = QInputDialog.getText(self, "Переименовать", "Новое название:", QLineEdit.EchoMode.Normal, d["name"])
        if ok and name.strip():
            self.ctx.storage.rename_deck(d["id"], name)
            self.refresh()

    def delete(self, d: dict) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Удалить колоду")
        box.setText(f"Удалить колоду «{d['name']}» и все её карточки?")
        yes = box.addButton("Удалить", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is yes:
            self.ctx.storage.delete_deck(d["id"])
            self.refresh()

    def study(self, d: dict) -> None:
        self.stack.setCurrentWidget(self.review)
        self.review.start(d["id"], d["name"])

    def _back_from_review(self) -> None:
        self.stack.setCurrentWidget(self.list_page)
        self.refresh()
        self.ctx.data_changed.emit()
