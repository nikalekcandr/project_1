"""Настройки."""
from __future__ import annotations

import csv
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QCheckBox, QFileDialog, QLineEdit, QMessageBox, QSlider

from .. import APP_NAME, __version__
from ..catalog import GAME_BY_ID
from ..context import AppContext
from ..theme import T, apply_theme
from ..widgets.common import Card, ScrollPage, Segmented, button, clear_layout, hbox, label, vbox


class SettingsPage(ScrollPage):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__(max_width=860)
        self.ctx = ctx
        self.build()

    def section(self, title: str, subtitle: str = "") -> Card:
        c = Card(padding=24)
        items = [label(title, "h3")]
        if subtitle:
            items.append(label(subtitle, "muted", wrap=True))
        c.lay.addLayout(vbox(*items, spacing=2))
        self.body_lay.addWidget(c)
        return c

    def build(self) -> None:
        clear_layout(self.body_lay)
        ctx = self.ctx
        self.body_lay.addWidget(label("Настройки", "h1"))

        prof = self.section("Профиль")
        self.name_edit = QLineEdit(ctx.setting("name", "") or "")
        self.name_edit.setPlaceholderText("Как к вам обращаться?")
        self.name_edit.setMaximumWidth(360)
        self.name_edit.editingFinished.connect(self._save_name)
        prof.lay.addLayout(hbox(label("Имя", "muted"), self.name_edit, "stretch", spacing=16))

        look = self.section("Оформление")
        theme = Segmented([("dark", "Тёмная"), ("light", "Светлая")], ctx.setting("theme", "dark"))
        theme.changed.connect(self._set_theme)
        look.lay.addLayout(hbox(label("Тема", "muted"), theme, spacing=16))

        snd = self.section("Звук", "Звуковые сигналы помогают держать ритм и дают мгновенную обратную связь.")
        cb = QCheckBox("Звуковые эффекты")
        cb.setChecked(ctx.sound.enabled)
        cb.toggled.connect(self._toggle_sound)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(int(ctx.sound.volume * 100))
        slider.setMaximumWidth(260)
        slider.sliderReleased.connect(lambda: self._set_volume(slider.value()))
        test = button("Проверить", None, "sm", icon_name="volume", on_click=lambda: ctx.sound.play("levelup"))
        snd.lay.addWidget(cb)
        snd.lay.addLayout(hbox(label("Громкость", "muted"), slider, test, "stretch", spacing=16))
        voice = ctx.speech.voice_name if ctx.speech.available else None
        vtxt = (f"Голос для «Двойного N-назад»: {voice}" if voice
                else "Синтез речи не найден — в «Двойном N-назад» будут использоваться ноты.")
        snd.lay.addWidget(label(vtxt, "faint", wrap=True))
        if voice:
            snd.lay.addLayout(hbox(button("Проверить голос", None, "sm", icon_name="volume",
                                          on_click=lambda: ctx.speech.say("ка, эль, эм")), "stretch"))

        tr = self.section("Тренировка дня", "Сколько упражнений включать в ежедневный план.")
        cnt = Segmented([(str(n), str(n)) for n in (3, 4, 5, 6)], str(ctx.progress.daily_count()))
        cnt.changed.connect(self._set_daily)
        tr.lay.addLayout(hbox(label("Упражнений", "muted"), cnt, spacing=16))

        data = self.section("Данные", f"Прогресс хранится локально: {Path(ctx.storage.path).parent}")
        data.lay.addLayout(hbox(
            button("Открыть папку", None, "sm", icon_name="folder", on_click=self._open_folder),
            button("Экспорт в CSV", None, "sm", icon_name="upload", on_click=self._export_csv),
            "stretch",
            button("Сбросить прогресс", "danger", "sm", icon_name="trash", icon_color=T.hex("danger"),
                   on_click=self._reset),
            spacing=10,
        ))

        about = self.section(f"О программе {APP_NAME}")
        about.lay.addWidget(label(
            f"Версия {__version__}. 14 упражнений на основе методик когнитивной психологии: N-назад, "
            "таблицы Шульте, тест Струпа, блоки Корси, матрицы Равена и другие. Адаптивная сложность, "
            "когнитивный профиль, интервальные повторения, достижения.", "muted", wrap=True))
        about.lay.addWidget(label(
            "Горячие клавиши: Esc — выйти из упражнения, Enter — начать/продолжить. "
            "В каждом упражнении подсказка по клавишам показана на экране правил.", "faint", wrap=True))
        self.body_lay.addStretch(1)

    # ------------------------------------------------------------ обработчики
    def _save_name(self) -> None:
        self.ctx.set_setting("name", self.name_edit.text().strip())
        self.ctx.data_changed.emit()

    def _set_theme(self, name: str) -> None:
        self.ctx.set_setting("theme", name)
        apply_theme(QApplication.instance(), name)
        self.ctx.theme_changed.emit()

    def _toggle_sound(self, on: bool) -> None:
        self.ctx.sound.set_enabled(on)
        self.ctx.set_setting("sound", on)

    def _set_volume(self, v: int) -> None:
        self.ctx.sound.set_volume(v / 100)
        self.ctx.set_setting("volume", v / 100)
        self.ctx.sound.play("correct")

    def _set_daily(self, v: str) -> None:
        self.ctx.set_setting("daily_count", int(v))
        if not self.ctx.storage.games_on_day(self.ctx.storage.today().isoformat()):
            self.ctx.progress.regenerate_plan()
        self.ctx.data_changed.emit()

    def _open_folder(self) -> None:
        folder = str(Path(self.ctx.storage.path).parent)
        if sys.platform == "win32":
            os.startfile(folder)  # noqa: S606
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(folder)):
            subprocess.Popen(["xdg-open", folder])

    def _export_csv(self) -> None:
        default = str(Path.home() / f"mindforge-{datetime.now():%Y%m%d}.csv")
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт результатов", default, "CSV (*.csv)")
        if not path:
            return
        rows = self.ctx.storage.results()
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Дата", "Упражнение", "Результат", "Оценка", "Уровень", "Точность", "Длительность, с"])
            for r in reversed(rows):
                meta = GAME_BY_ID.get(r["game"])
                w.writerow([
                    datetime.fromtimestamp(r["ts"]).strftime("%Y-%m-%d %H:%M"),
                    meta.title if meta else r["game"],
                    r["metrics"].get("headline", r["score"]),
                    f"{r['rating']:.0f}",
                    r["level"],
                    "" if r["accuracy"] is None else f"{r['accuracy'] * 100:.0f}%",
                    f"{r['duration']:.0f}",
                ])
        self.ctx.toast("Экспорт завершён", f"Сохранено записей: {len(rows)}", "upload", T.c("success"))

    def _reset(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Сбросить прогресс")
        box.setText("Удалить все результаты, уровни, опыт и достижения?\nКолоды карточек сохранятся. "
                    "Это действие нельзя отменить.")
        yes = box.addButton("Сбросить", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is yes:
            self.ctx.storage.clear_progress()
            self.ctx.data_changed.emit()
            self.ctx.toast("Прогресс сброшен", "Начинаем с чистого листа!", "refresh", T.c("muted"))
