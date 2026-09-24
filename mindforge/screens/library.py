"""Библиотека упражнений с фильтром по когнитивным областям."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from ..catalog import GAMES, GameMeta
from ..context import AppContext
from ..core import DOMAINS
from ..games import GAME_ICONS
from ..theme import T, font
from ..widgets.common import Card, IconBadge, ResponsiveGrid, ScrollPage, Segmented, hbox, label, vbox
from .game_host import domain_chip


class GameCard(Card):
    def __init__(self, meta: GameMeta, ctx: AppContext) -> None:
        super().__init__(clickable=True, padding=20, accent=T.domain(meta.domain))
        self.meta = meta
        self.setMinimumHeight(196)
        badge = IconBadge(GAME_ICONS.get(meta.id, "brain"), T.domain(meta.domain), 48)
        self.lay.addLayout(hbox(badge, "stretch", domain_chip(meta.domain)))
        title = label(meta.title)
        title.setFont(font(13, QFont.Weight.Bold))
        tag = label(meta.tagline, "muted", wrap=True)
        self.lay.addLayout(vbox(title, tag, spacing=3))
        self.lay.addStretch(1)
        st = ctx.storage
        chips = []
        if meta.leveled:
            chips.append(label(f"Ур. {st.game_level(meta.id)}", "chip"))
        best = st.best_result(meta.id, "rating")
        if best:
            chips.append(label(f"★ {best['metrics'].get('headline', round(best['rating']))}", "chip"))
        else:
            chips.append(label("Новое", "chip"))
        chips.append(label(f"{meta.minutes:g} мин", "chip"))
        self.lay.addLayout(hbox(*chips, "stretch", spacing=6))


class LibraryPage(ScrollPage):
    game_selected = Signal(str)

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.filter = "all"
        head = label("Упражнения", "h1")
        sub = label("14 тренажёров для шести когнитивных способностей. Уровень сложности подстраивается под вас.",
                    "muted", wrap=True)
        self.body_lay.addLayout(vbox(head, sub, spacing=4))
        choices = [("all", "Все")] + list(DOMAINS.items())
        self.seg = Segmented(choices, "all")
        self.seg.changed.connect(self._on_filter)
        self.body_lay.addWidget(self.seg)
        self.domain_hint = label("", "muted", wrap=True)
        self.body_lay.addWidget(self.domain_hint)
        self.grid = ResponsiveGrid(270, 16)
        self.body_lay.addWidget(self.grid)
        self.body_lay.addStretch(1)
        ctx.data_changed.connect(self.refresh)
        self.refresh()

    def _on_filter(self, v: str) -> None:
        self.filter = v
        self.refresh()

    def refresh(self) -> None:
        from ..core import DOMAIN_HINTS

        self.domain_hint.setText(DOMAIN_HINTS.get(self.filter, ""))
        self.domain_hint.setVisible(self.filter != "all")
        cards = []
        for meta in GAMES:
            if self.filter != "all" and meta.domain != self.filter:
                continue
            c = GameCard(meta, self.ctx)
            c.clicked.connect(lambda m=meta: self.game_selected.emit(m.id))
            cards.append(c)
        self.grid.set_items(cards)


__all__ = ["LibraryPage", "Qt"]
