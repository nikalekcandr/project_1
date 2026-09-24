"""Статистика: индекс, профиль по областям, прогресс по упражнениям, история."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QGridLayout, QHeaderView, QTableWidget, QTableWidgetItem

from ..catalog import GAME_BY_ID, GAMES, games_in_domain
from ..context import AppContext
from ..core import DOMAIN_HINTS, DOMAINS, fmt_duration_long
from ..theme import T, font
from ..widgets.charts import LineChart, RadarChart
from ..widgets.common import Bar, Card, ScrollPage, StatTile, clear_layout, hbox, label, vbox


def short_date(day: str) -> str:
    d = datetime.fromisoformat(day)
    return f"{d.day:02d}.{d.month:02d}"


class StatsPage(ScrollPage):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.selected_game = GAMES[0].id
        ctx.data_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        clear_layout(self.body_lay)
        st, pr = self.ctx.storage, self.ctx.progress
        self.body_lay.addLayout(vbox(label("Статистика", "h1"),
                                     label("Как меняются ваши способности со временем.", "muted"), spacing=4))
        tiles = QGridLayout()
        tiles.setSpacing(16)
        cur, best = pr.streak()
        items = [
            StatTile("target", "Упражнений выполнено", str(st.result_count()), "", T.c("accent")),
            StatTile("clock", "Время тренировок", fmt_duration_long(st.total_duration()), "", T.c("success")),
            StatTile("flame", "Лучшая серия", f"{best} дн.", f"Текущая: {cur}", T.c("warning")),
            StatTile("cards", "Карточек повторено", str(st.review_count()), "", T.domain("memory")),
        ]
        for i, t in enumerate(items):
            tiles.addWidget(t, 0, i)
        self.body_lay.addLayout(tiles)

        # индекс
        idx_card = Card(padding=22)
        idx = pr.index()
        idx_card.lay.addLayout(hbox(label("Индекс MindForge", "h3"), "stretch",
                                    label(str(idx) if idx is not None else "—", "h2")))
        idx_card.lay.addWidget(label("Среднее по всем областям (0–1000). Рассчитывается по трём лучшим из "
                                     "последних десяти попыток в каждом упражнении.", "muted", wrap=True))
        chart = LineChart(height=200)
        hist = pr.index_history(90)
        chart.set_data([(short_date(d), v) for d, v in hist], None, None, T.c("accent"))
        chart.empty_text = "График появится после первых упражнений"
        idx_card.lay.addWidget(chart)
        self.body_lay.addWidget(idx_card)

        # профиль
        row = QGridLayout()
        row.setSpacing(16)
        prof = pr.profile()
        radar_card = Card(padding=22)
        radar_card.lay.addWidget(label("Когнитивный профиль", "h3"))
        radar = RadarChart(size=320)
        radar.set_data([(DOMAINS[d], prof[d], T.domain(d)) for d in DOMAINS])
        radar_card.lay.addWidget(radar, 1)
        row.addWidget(radar_card, 0, 0)
        dom_card = Card(padding=22)
        dom_card.lay.addWidget(label("Области", "h3"))
        for d, name in DOMAINS.items():
            v = prof[d]
            nm = label(name)
            nm.setFont(font(10.5, QFont.Weight.DemiBold))
            val = label(f"{v:.0f}" if v is not None else "—")
            val.setFont(font(10.5, QFont.Weight.Bold))
            bar = Bar(7)
            bar.color = T.domain(d)
            bar.color2 = T.domain(d)
            bar.set_value((v or 0) / 100, animate=False)
            games = ", ".join(g.title for g in games_in_domain(d))
            hint = label(f"{DOMAIN_HINTS[d]} Упражнения: {games}.", "faint", wrap=True)
            hint.setFont(font(8.5))
            dom_card.lay.addLayout(vbox(hbox(nm, "stretch", val), bar, hint, spacing=4))
        row.addWidget(dom_card, 0, 1)
        row.setColumnStretch(0, 1)
        row.setColumnStretch(1, 1)
        self.body_lay.addLayout(row)

        # по упражнениям
        game_card = Card(padding=22)
        combo = QComboBox()
        for g in GAMES:
            combo.addItem(g.title, g.id)
        combo.setCurrentIndex(max(0, combo.findData(self.selected_game)))
        combo.setMinimumWidth(240)
        game_card.lay.addLayout(hbox(label("Прогресс по упражнению", "h3"), "stretch", combo))
        self.game_chart = LineChart(height=200)
        self.game_info = label("", "muted")
        game_card.lay.addWidget(self.game_chart)
        game_card.lay.addWidget(self.game_info)
        combo.currentIndexChanged.connect(lambda i: self._select_game(combo.itemData(i)))
        self.body_lay.addWidget(game_card)
        self._select_game(self.selected_game)

        # история
        hist_card = Card(padding=22)
        hist_card.lay.addWidget(label("Последние упражнения", "h3"))
        rows = st.results(limit=30)
        if not rows:
            hist_card.lay.addWidget(label("Здесь появится история ваших тренировок.", "faint"))
        else:
            table = QTableWidget(len(rows), 4)
            table.setHorizontalHeaderLabels(["Дата", "Упражнение", "Результат", "Оценка"])
            table.verticalHeader().setVisible(False)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
            table.setShowGrid(False)
            table.setAlternatingRowColors(True)
            table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            hh = table.horizontalHeader()
            hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
            for i, r in enumerate(rows):
                dt = datetime.fromtimestamp(r["ts"])
                meta = GAME_BY_ID.get(r["game"])
                vals = [dt.strftime("%d.%m.%Y %H:%M"), meta.title if meta else r["game"],
                        str(r["metrics"].get("headline", r["score"])), f"{r['rating']:.0f}"]
                for j, v in enumerate(vals):
                    item = QTableWidgetItem(v)
                    if j == 3:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    table.setItem(i, j, item)
            table.setMinimumHeight(min(560, 44 + 38 * len(rows)))
            hist_card.lay.addWidget(table)
        self.body_lay.addWidget(hist_card)
        self.body_lay.addStretch(1)

    def _select_game(self, game_id: str) -> None:
        self.selected_game = game_id
        meta = GAME_BY_ID[game_id]
        rows = list(reversed(self.ctx.storage.results(game_id, limit=40)))
        pts = [(short_date(r["day"]), r["rating"]) for r in rows]
        self.game_chart.set_data(pts, 0, 100, T.domain(meta.domain))
        self.game_chart.empty_text = "Вы ещё не выполняли это упражнение"
        if rows:
            gr = self.ctx.progress.game_rating(game_id)
            best = max(rows, key=lambda r: r["rating"])
            lvl = f" · текущий уровень {self.ctx.storage.game_level(game_id)}" if meta.leveled else ""
            self.game_info.setText(
                f"Попыток: {self.ctx.storage.result_count(game_id)} · оценка {gr:.0f} · "
                f"рекорд: {best['metrics'].get('headline', best['rating'])}{lvl}"
            )
        else:
            self.game_info.setText("")
