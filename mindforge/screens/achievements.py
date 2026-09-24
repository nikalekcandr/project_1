"""Достижения."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtGui import QFont

from ..context import AppContext
from ..progress import ACHIEVEMENTS, LEVEL_TITLES, level_title
from ..theme import T, font
from ..widgets.common import (
    Bar,
    Card,
    IconBadge,
    ProgressRing,
    ResponsiveGrid,
    ScrollPage,
    clear_layout,
    hbox,
    label,
    vbox,
)


class AchievementsPage(ScrollPage):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        ctx.data_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        clear_layout(self.body_lay)
        pr = self.ctx.progress
        unlocked = pr.unlocked()
        self.body_lay.addLayout(vbox(label("Достижения", "h1"),
                                     label(f"Открыто {len(unlocked)} из {len(ACHIEVEMENTS)}", "muted"), spacing=4))

        # уровень игрока
        lvl, into, need = pr.level_info()
        card = Card(padding=24, accent=T.c("accent"))
        ring = ProgressRing(110, 10)
        ring.text = str(lvl)
        ring.subtext = "уровень"
        ring.set_value(into / need)
        nxt = next((l for l, _ in LEVEL_TITLES if l > lvl), None)
        t = label(level_title(lvl), "h2")
        sub = label(f"{pr.xp} XP всего · до следующего уровня {need - into} XP", "muted")
        extra = label(f"Следующее звание — «{level_title(nxt)}» на уровне {nxt}" if nxt else "Высшее звание получено!",
                      "faint")
        xp_help = label("Опыт начисляется за каждое упражнение (больше — за высокую оценку и рекорды), "
                        "за тренировку дня и достижения.", "faint", wrap=True)
        card.lay.addLayout(hbox(ring, vbox(t, sub, extra, xp_help, spacing=4), spacing=24))
        self.body_lay.addWidget(card)

        grid = ResponsiveGrid(250, 14)
        cards = []
        for a in ACHIEVEMENTS:
            got = a.id in unlocked
            if a.secret and not got:
                title, desc, icon_name = "Секретное достижение", "Откроется при особых обстоятельствах", "lock"
            else:
                title, desc, icon_name = a.title, a.description, a.icon if got else "lock"
            c = Card(padding=18, accent=T.c("warning") if got else None)
            c.setMinimumHeight(150)
            badge = IconBadge(icon_name, T.c("warning") if got else T.c("faint"), 44)
            tl = label(title)
            tl.setFont(font(11, QFont.Weight.Bold))
            tl.setWordWrap(True)
            if not got:
                tl.setStyleSheet(f"color:{T.hex('muted')};")
            c.lay.addLayout(hbox(badge, vbox(tl, label(desc, "muted", wrap=True), spacing=2), spacing=12))
            c.lay.addStretch(1)
            if got:
                dt = datetime.fromtimestamp(unlocked[a.id])
                c.lay.addWidget(label(f"Получено {dt.strftime('%d.%m.%Y')}", "faint"))
            elif not a.secret and a.target > 1:
                val = min(a.target, pr.achievement_progress(a))
                bar = Bar(6)
                bar.set_value(val / a.target, animate=False)
                if a.id == "hour":
                    txt = f"{int(val // 60)} / {int(a.target // 60)} мин"
                else:
                    txt = f"{int(val)} / {int(a.target)}"
                c.lay.addLayout(vbox(bar, label(txt, "faint"), spacing=4))
            cards.append(c)
        grid.set_items(cards)
        self.body_lay.addWidget(grid)
        self.body_lay.addStretch(1)
