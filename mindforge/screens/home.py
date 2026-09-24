"""Главная: приветствие, серия, план дня, профиль, активность, совет дня."""
from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QGridLayout, QWidget

from ..catalog import GAME_BY_ID
from ..context import AppContext
from ..core import DOMAINS, plural
from ..data.tips import TIPS
from ..games import GAME_ICONS
from ..progress import level_title
from ..theme import T, font
from ..widgets.charts import Heatmap, RadarChart
from ..widgets.common import (
    Card,
    IconBadge,
    IconView,
    ScrollPage,
    StatTile,
    button,
    clear_layout,
    hbox,
    label,
    vbox,
)
from .game_host import domain_chip

MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
              "ноября", "декабря"]
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]


def greeting(hour: int) -> str:
    if 5 <= hour < 12:
        return "Доброе утро"
    if 12 <= hour < 18:
        return "Добрый день"
    if 18 <= hour < 23:
        return "Добрый вечер"
    return "Доброй ночи"


class PlanRow(QWidget):
    play = Signal(str)

    def __init__(self, game_id: str, done: bool, index: int) -> None:
        super().__init__()
        meta = GAME_BY_ID[game_id]
        col = T.domain(meta.domain)
        badge = IconBadge(GAME_ICONS.get(game_id, "brain"), col, 40)
        title = label(meta.title)
        title.setFont(font(11, QFont.Weight.DemiBold))
        tag = label(meta.tagline, "muted")
        if done:
            status = IconView("check", T.c("success"), 22)
        else:
            status = button("Играть", None, "sm", icon_name="play", on_click=lambda: self.play.emit(game_id))
        num = label(str(index + 1), "faint")
        num.setFixedWidth(14)
        lay = hbox(num, badge, vbox(title, tag, spacing=1), "stretch", domain_chip(meta.domain), status, spacing=12)
        lay.setContentsMargins(4, 4, 4, 4)
        self.setLayout(lay)
        if done:
            title.setStyleSheet(f"color:{T.hex('muted')};")


class HomePage(ScrollPage):
    start_plan = Signal(list, int)
    open_game = Signal(str)
    goto = Signal(str)

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        ctx.data_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        clear_layout(self.body_lay)
        st, pr = self.ctx.storage, self.ctx.progress
        now = datetime.fromtimestamp(st.now())
        name = self.ctx.setting("name", "") or ""
        hello = label(f"{greeting(now.hour)}{', ' + name if name else ''}!", "h1")
        date_txt = f"{WEEKDAYS[now.weekday()].capitalize()}, {now.day} {MONTHS_GEN[now.month - 1]}"
        cur, best = pr.streak()
        today_n = len([r for r in st.results(since_day=now.date().isoformat())])
        sub_parts = [date_txt]
        if today_n:
            sub_parts.append(f"сегодня {today_n} {plural(today_n, 'упражнение', 'упражнения', 'упражнений')}")
        sub = label(" · ".join(sub_parts), "muted")
        self.body_lay.addLayout(vbox(hello, sub, spacing=2))

        # --- плитки
        tiles = QGridLayout()
        tiles.setSpacing(16)
        lvl, into, need = pr.level_info()
        t1 = StatTile("flame", "Серия", f"{cur} {plural(cur, 'день', 'дня', 'дней')}",
                      f"Лучшая: {best}", T.c("warning"))
        idx = pr.index()
        prof = pr.profile()
        covered = sum(v is not None for v in prof.values())
        t2 = StatTile("bolt", "Индекс MindForge", str(idx) if idx is not None else "—",
                      f"по {covered} из 6 областей" if idx is not None else "выполните упражнения", T.c("accent2"))
        t3 = StatTile("award", f"Уровень · {level_title(lvl)}", str(lvl), f"{into} / {need} XP", T.c("accent"))
        week_start = (now.date() - timedelta(days=6)).isoformat()
        week = st.results(since_day=week_start)
        week_min = round(sum(r["duration"] for r in week) / 60)
        t4 = StatTile("clock", "За 7 дней", f"{week_min} мин",
                      f"{len(week)} {plural(len(week), 'упражнение', 'упражнения', 'упражнений')}", T.c("success"))
        for i, t in enumerate((t1, t2, t3, t4)):
            tiles.addWidget(t, 0, i)
        self.body_lay.addLayout(tiles)

        # --- план дня + профиль
        row = QGridLayout()
        row.setSpacing(16)
        plan_card = Card(padding=22, accent=T.c("accent"))
        status = pr.plan_status()
        done_n = sum(d for _, d in status)
        total_min = sum(GAME_BY_ID[g].minutes for g, _ in status)
        title = label("Тренировка дня", "h2")
        bonus_taken = bool(st.get(f"planbonus.{now.date().isoformat()}"))
        info = f"{len(status)} упражнений · ≈ {total_min:g} мин · " + ("бонус получен ✓" if bonus_taken else "+60 XP бонус")
        regen = button("Обновить", "ghost", "sm", icon_name="refresh", icon_color=T.hex("muted"),
                       on_click=self._regen)
        regen.setToolTip("Подобрать другие упражнения на сегодня")
        regen.setVisible(done_n == 0)
        plan_card.lay.addLayout(hbox(vbox(title, label(info, "muted"), spacing=2), "stretch", regen))
        from ..widgets.common import Bar

        bar = Bar(8)
        bar.set_value(done_n / len(status) if status else 0, animate=False)
        plan_card.lay.addWidget(bar)
        for i, (g, d) in enumerate(status):
            r = PlanRow(g, d, i)
            r.play.connect(self.open_game.emit)
            plan_card.lay.addWidget(r)
        first_undone = next((i for i, (_, d) in enumerate(status) if not d), None)
        if first_undone is None:
            btn = button("План выполнен — сыграть ещё раз", None, "lg", icon_name="refresh",
                         on_click=lambda: self.start_plan.emit([g for g, _ in status], 0))
        else:
            txt = "Начать тренировку" if done_n == 0 else f"Продолжить ({done_n}/{len(status)})"
            queue = [g for g, _ in status]
            btn = button(txt, "primary", "lg", icon_name="play",
                         on_click=lambda: self.start_plan.emit(queue, first_undone))
        plan_card.lay.addSpacing(4)
        plan_card.lay.addLayout(hbox(btn, "stretch"))
        row.addWidget(plan_card, 0, 0)

        prof_card = Card(padding=22)
        prof_card.lay.addLayout(hbox(label("Когнитивный профиль", "h3"), "stretch",
                                     button("Подробнее", "ghost", "sm", on_click=lambda: self.goto.emit("stats"))))
        radar = RadarChart(size=260)
        radar.compact = True
        radar.set_data([(DOMAINS[d], prof[d], T.domain(d)) for d in DOMAINS])
        prof_card.lay.addWidget(radar, 1)
        if covered == 0:
            prof_card.lay.addWidget(label("Профиль заполнится после первых упражнений.", "faint", wrap=True,
                                          align=Qt.AlignmentFlag.AlignCenter))
        row.addWidget(prof_card, 0, 1)
        row.setColumnStretch(0, 3)
        row.setColumnStretch(1, 2)
        self.body_lay.addLayout(row)

        # --- активность + совет дня
        row2 = QGridLayout()
        row2.setSpacing(16)
        act = Card(padding=22)
        days_active = len(pr.active_days())
        act.lay.addLayout(hbox(label("Активность", "h3"), "stretch",
                               label(f"{days_active} {plural(days_active, 'день', 'дня', 'дней')} с тренировками",
                                     "muted")))
        hm = Heatmap(weeks=22)
        hm.set_data(st.activity_by_day(), st.today())
        act.lay.addWidget(hm)
        row2.addWidget(act, 0, 0)

        tip_title, tip_text = TIPS[now.date().toordinal() % len(TIPS)]
        tip = Card(padding=22, tint=T.hex("accent2"))
        tip.lay.addLayout(hbox(IconBadge("sparkles", T.c("accent2"), 34), label("Совет дня", "h3"), "stretch"))
        tt = label(tip_title)
        tt.setFont(font(11.5, QFont.Weight.Bold))
        tip.lay.addWidget(tt)
        tip.lay.addWidget(label(tip_text, "muted", wrap=True))
        tip.lay.addStretch(1)
        row2.addWidget(tip, 0, 1)
        row2.setColumnStretch(0, 3)
        row2.setColumnStretch(1, 2)
        self.body_lay.addLayout(row2)

        # --- карточки
        due = st.total_due()
        new = sum(d["new"] for d in st.decks())
        cards = Card(padding=20, clickable=True)
        cards.clicked.connect(lambda: self.goto.emit("cards"))
        if due or new:
            msg = f"К повторению: {due} · новых: {new}. Интервальные повторения закрепляют знания надолго."
        else:
            msg = "Создайте колоду карточек или добавьте готовую — и запоминайте что угодно навсегда."
        cards.lay.addLayout(hbox(IconBadge("cards", T.domain("memory"), 44),
                                 vbox(label("Карточки для запоминания", "h3"), label(msg, "muted", wrap=True),
                                      spacing=2), "stretch",
                                 button("Открыть", None, "sm", icon_name="arrow_right",
                                        on_click=lambda: self.goto.emit("cards")), spacing=16))
        self.body_lay.addWidget(cards)
        self.body_lay.addStretch(1)

    def _regen(self) -> None:
        self.ctx.progress.regenerate_plan()
        self.refresh()
