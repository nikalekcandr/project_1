"""Главное окно и запуск приложения."""
from __future__ import annotations

import os
import sys
import traceback

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QFont, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import APP_NAME, APP_TITLE, __version__
from .context import AppContext
from .progress import level_title
from .storage import Storage
from .theme import T, apply_theme, font
from .widgets import icons
from .widgets.common import Bar, Card, IconBadge, IconView, button, hbox, label, vbox
from .widgets.logo import LogoHeader, app_icon, logo_pixmap, paint_logo

NAV = [
    ("home", "Главная", "home"),
    ("library", "Упражнения", "grid"),
    ("cards", "Карточки", "cards"),
    ("stats", "Статистика", "chart"),
    ("achievements", "Достижения", "trophy"),
    ("settings", "Настройки", "settings"),
]


def nav_icon(name: str) -> QIcon:
    ic = QIcon()
    ic.addPixmap(icons.pixmap(name, T.c("muted"), 20), QIcon.Mode.Normal, QIcon.State.Off)
    ic.addPixmap(icons.pixmap(name, T.c("text"), 20), QIcon.Mode.Active, QIcon.State.Off)
    ic.addPixmap(icons.pixmap(name, T.c("accent_hover"), 20), QIcon.Mode.Normal, QIcon.State.On)
    ic.addPixmap(icons.pixmap(name, T.c("accent_hover"), 20), QIcon.Mode.Active, QIcon.State.On)
    return ic


class PlayerCard(Card):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__(padding=14, radius=14)
        self.ctx = ctx
        self.title = label("")
        self.title.setFont(font(10, QFont.Weight.Bold))
        self.sub = label("", "muted")
        self.bar = Bar(6)
        self.streak_icon = IconView("flame", T.c("warning"), 18)
        self.streak = label("")
        self.streak.setFont(font(10, QFont.Weight.Bold))
        self.xp = label("", "faint")
        self.lay.setSpacing(6)
        self.lay.addLayout(hbox(vbox(self.title, self.sub, spacing=0), "stretch", self.streak_icon, self.streak,
                                spacing=4))
        self.lay.addWidget(self.bar)
        self.lay.addWidget(self.xp)
        self.setToolTip("Уровень и серия дней подряд с тренировками")
        self.refresh()

    def refresh(self) -> None:
        pr = self.ctx.progress
        lvl, into, need = pr.level_info()
        self.title.setText(f"Уровень {lvl}")
        self.sub.setText(level_title(lvl))
        self.xp.setText(f"{into} / {need} XP до уровня {lvl + 1}")
        self.bar.set_value(into / need)
        cur, _ = pr.streak()
        self.streak.setText(str(cur))
        self.streak_icon.color = T.c("warning") if cur else T.c("faint")
        self.streak_icon.update()


class Sidebar(QWidget):
    def __init__(self, ctx: AppContext, on_nav) -> None:
        super().__init__()
        self.setObjectName("Sidebar")
        self.setFixedWidth(236)
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 18, 16, 18)
        lay.setSpacing(4)
        lay.addWidget(LogoHeader())
        lay.addSpacing(18)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        for i, (key, text, icon_name) in enumerate(NAV):
            b = QPushButton(f"  {text}")
            b.setProperty("kind", "nav")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setIcon(nav_icon(icon_name))
            b.setIconSize(QSize(20, 20))
            b.setToolTip(f"Ctrl+{i + 1}")
            b.clicked.connect(lambda _=False, k=key: on_nav(k))
            self.group.addButton(b)
            self.buttons[key] = b
            lay.addWidget(b)
        lay.addStretch(1)
        self.player = PlayerCard(ctx)
        lay.addWidget(self.player)
        self.update_style()

    def update_style(self) -> None:
        self.setStyleSheet(f"QWidget#Sidebar {{ background: {T.hex('bg2')}; border-right: 1px solid {T.hex('border')}; }}")
        for key, _, icon_name in NAV:
            self.buttons[key].setIcon(nav_icon(icon_name))

    def select(self, key: str) -> None:
        if key in self.buttons:
            self.buttons[key].setChecked(True)


class WelcomeDialog(QWidget):
    """Экран первого запуска (встроенный в окно, без отдельного диалога)."""

    def __init__(self, on_done) -> None:
        super().__init__()
        self.setObjectName("Page")
        self.on_done = on_done
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        card = Card(padding=40, accent=T.c("accent"))
        card.setMaximumWidth(760)
        logo = QLabel()
        logo.setPixmap(logo_pixmap(84))
        card.lay.addWidget(logo, 0, Qt.AlignmentFlag.AlignHCenter)
        card.lay.addWidget(label("Добро пожаловать в MindForge", "h1", align=Qt.AlignmentFlag.AlignCenter))
        card.lay.addWidget(label("Ежедневные 10–15 минут для памяти, внимания и интеллекта.", "muted",
                                 align=Qt.AlignmentFlag.AlignCenter))
        card.lay.addSpacing(10)
        feats = [
            ("brain", "14 упражнений", "N-назад, Шульте, Струп, Корси, матрицы Равена и другие научные методики."),
            ("trend", "Адаптивная сложность", "Уровень подстраивается так, чтобы вы тренировались на пределе возможностей."),
            ("calendar", "План на каждый день", "Сбалансированная тренировка с упором на ваши слабые стороны."),
            ("cards", "Карточки навсегда", "Интервальные повторения для слов, дат, формул — чего угодно."),
        ]
        grid = QGridLayout()
        grid.setSpacing(16)
        for i, (ic, t, d) in enumerate(feats):
            tl = label(t)
            tl.setFont(font(11, QFont.Weight.Bold))
            grid.addLayout(hbox(IconBadge(ic, T.c("accent"), 40), vbox(tl, label(d, "muted", wrap=True), spacing=2),
                                spacing=12), i // 2, i % 2)
        card.lay.addLayout(grid)
        card.lay.addSpacing(10)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Как вас зовут? (необязательно)")
        self.name.setMaximumWidth(320)
        self.name.returnPressed.connect(self._done)
        go = button("Начать", "primary", "lg", icon_name="arrow_right", on_click=self._done)
        card.lay.addLayout(hbox("stretch", self.name, go, "stretch", spacing=12))
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(card, 10)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)

    def _done(self) -> None:
        self.on_done(self.name.text().strip())


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        from .screens.achievements import AchievementsPage
        from .screens.flashcards import FlashcardsPage
        from .screens.game_host import GameHost
        from .screens.home import HomePage
        from .screens.library import LibraryPage
        from .screens.settings import SettingsPage
        from .screens.stats import StatsPage

        self.ctx = ctx
        ctx.window = self
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(app_icon())
        self.resize(1320, 860)
        self.setMinimumSize(1060, 700)

        central = QWidget()
        central.setObjectName("Content")
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.sidebar = Sidebar(ctx, self.go)
        root.addWidget(self.sidebar)
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self.pages = {
            "home": HomePage(ctx),
            "library": LibraryPage(ctx),
            "cards": FlashcardsPage(ctx),
            "stats": StatsPage(ctx),
            "achievements": AchievementsPage(ctx),
            "settings": SettingsPage(ctx),
        }
        for p in self.pages.values():
            self.stack.addWidget(p)
        self.host = GameHost(ctx)
        self.stack.addWidget(self.host)
        self.host.closed.connect(self.close_game)
        self.welcome: WelcomeDialog | None = None

        self.pages["home"].start_plan.connect(self.start_plan)
        self.pages["home"].open_game.connect(self.open_game)
        self.pages["home"].goto.connect(self.go)
        self.pages["library"].game_selected.connect(self.open_game)
        ctx.data_changed.connect(self.sidebar.player.refresh)
        ctx.theme_changed.connect(self.on_theme_changed)
        self.return_page = "home"

        for i, (key, _, _) in enumerate(NAV):
            sc = QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self)
            sc.activated.connect(lambda k=key: self.go(k) if self.stack.currentWidget() is not self.host else None)

        if not ctx.setting("onboarded", False):
            self.show_welcome()
        else:
            self.go("home")

    # ------------------------------------------------------------ навигация
    def go(self, key: str) -> None:
        if key not in self.pages:
            return
        self.sidebar.setVisible(True)
        self.sidebar.select(key)
        self.stack.setCurrentWidget(self.pages[key])
        self.return_page = key

    def open_game(self, game_id: str) -> None:
        self.sidebar.setVisible(False)
        self.stack.setCurrentWidget(self.host)
        self.host.open(game_id)

    def start_plan(self, queue: list, pos: int) -> None:
        self.sidebar.setVisible(False)
        self.stack.setCurrentWidget(self.host)
        self.host.open(queue[pos], queue, pos)

    def close_game(self) -> None:
        self.go(self.return_page if self.return_page in self.pages else "home")

    def show_welcome(self) -> None:
        self.sidebar.setVisible(False)
        self.welcome = WelcomeDialog(self._finish_welcome)
        self.stack.addWidget(self.welcome)
        self.stack.setCurrentWidget(self.welcome)

    def _finish_welcome(self, name: str) -> None:
        self.ctx.set_setting("name", name)
        self.ctx.set_setting("onboarded", True)
        if self.welcome is not None:
            self.stack.removeWidget(self.welcome)
            self.welcome.deleteLater()
            self.welcome = None
        self.ctx.data_changed.emit()
        self.pages["settings"].build()
        self.go("home")

    def on_theme_changed(self) -> None:
        self.sidebar.update_style()
        self.ctx.data_changed.emit()
        QTimer.singleShot(0, self.pages["settings"].build)
        set_dark_titlebar(self, T.is_dark)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        set_dark_titlebar(self, T.is_dark)

    def closeEvent(self, e) -> None:
        self.host._teardown()
        super().closeEvent(e)


def set_dark_titlebar(window: QWidget, dark: bool) -> None:
    """Тёмный заголовок окна в Windows 10/11."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = int(window.winId())
        value = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (новый и старый номер)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass


def _install_excepthook() -> None:
    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        sys.stderr.write(text)
        app = QApplication.instance()
        if app is not None and not os.environ.get("MINDFORGE_SELFTEST"):
            box = QMessageBox()
            box.setWindowTitle("MindForge — ошибка")
            box.setText("Произошла непредвиденная ошибка. Приложение продолжит работу.")
            box.setDetailedText(text)
            box.exec()

    sys.excepthook = hook


def create_app(argv: list[str] | None = None) -> QApplication:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"MindForge.App.{__version__}")
        except Exception:
            pass
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setWindowIcon(app_icon())
    app.setFont(font(10))
    return app


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    selftest = next((a for a in argv if a.startswith("--selftest")), None)
    if selftest:
        from .selftest import run_selftest

        return run_selftest(selftest.partition("=")[2] or None)
    app = create_app(argv)
    _install_excepthook()
    storage = Storage()
    ctx = AppContext(storage)
    apply_theme(app, ctx.setting("theme", "dark"))
    win = MainWindow(ctx)
    win.show()
    QTimer.singleShot(400, lambda: ctx.sound._prepare())
    return app.exec()


__all__ = ["main", "create_app", "MainWindow", "paint_logo"]
