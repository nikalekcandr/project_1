"""Цветовые темы, шрифты и глобальная таблица стилей."""
from __future__ import annotations

import sys

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

DARK = {
    "bg": "#0E1120",
    "bg2": "#12162A",
    "surface": "#171C33",
    "surface2": "#1E2440",
    "surface3": "#272E52",
    "border": "#2B3358",
    "text": "#ECEEFB",
    "muted": "#98A0C8",
    "faint": "#5D6591",
    "accent": "#7C5CFF",
    "accent_hover": "#8F74FF",
    "accent2": "#22D3EE",
    "success": "#22C55E",
    "danger": "#F05252",
    "warning": "#F5A524",
    "on_accent": "#FFFFFF",
    "shadow": "#05060D",
    "cell": "#232A4A",
    "cell_hover": "#2E3660",
}

LIGHT = {
    "bg": "#F3F4FA",
    "bg2": "#ECEEF7",
    "surface": "#FFFFFF",
    "surface2": "#F1F2F9",
    "surface3": "#E4E6F3",
    "border": "#DCDFEE",
    "text": "#171A2E",
    "muted": "#5E6485",
    "faint": "#A3A8C4",
    "accent": "#6A45FF",
    "accent_hover": "#7B5BFF",
    "accent2": "#0EA5C6",
    "success": "#16A34A",
    "danger": "#DC2626",
    "warning": "#D97706",
    "on_accent": "#FFFFFF",
    "shadow": "#B8BCD6",
    "cell": "#E9EBF6",
    "cell_hover": "#DDE0F2",
}

# Цвета когнитивных доменов (одинаковые в обеих темах, подобраны под оба фона).
DOMAIN_COLORS = {
    "memory": "#A78BFA",
    "attention": "#F5A524",
    "speed": "#22D3EE",
    "logic": "#34D399",
    "flexibility": "#F472B6",
    "spatial": "#60A5FA",
}


class _Theme:
    """Текущая тема. Цвета читаются в момент отрисовки, поэтому смена темы
    применяется ко всем нарисованным вручную виджетам после update()."""

    def __init__(self) -> None:
        self.name = "dark"
        self._tokens = dict(DARK)

    def set(self, name: str) -> None:
        self.name = "light" if name == "light" else "dark"
        self._tokens = dict(LIGHT if self.name == "light" else DARK)

    @property
    def is_dark(self) -> bool:
        return self.name == "dark"

    def hex(self, key: str) -> str:
        return self._tokens[key]

    def c(self, key: str, alpha: int | None = None) -> QColor:
        col = QColor(self._tokens[key])
        if alpha is not None:
            col.setAlpha(alpha)
        return col

    def domain(self, domain: str, alpha: int | None = None) -> QColor:
        col = QColor(DOMAIN_COLORS.get(domain, self._tokens["accent"]))
        if alpha is not None:
            col.setAlpha(alpha)
        return col


T = _Theme()


def ui_font_family() -> str:
    if sys.platform == "win32":
        return "Segoe UI"
    if sys.platform == "darwin":
        return "SF Pro Text"
    return "DejaVu Sans"


def font(size: float = 10, weight: QFont.Weight = QFont.Weight.Normal, family: str | None = None) -> QFont:
    f = QFont(family or ui_font_family())
    f.setPointSizeF(size)
    f.setWeight(weight)
    return f


def mono_font(size: float = 12, weight: QFont.Weight = QFont.Weight.DemiBold) -> QFont:
    fam = "Consolas" if sys.platform == "win32" else "DejaVu Sans Mono"
    return font(size, weight, fam)


def mix(c1: QColor, c2: QColor, t: float) -> QColor:
    """Линейное смешивание двух цветов (t=0 → c1, t=1 → c2)."""
    t = max(0.0, min(1.0, t))
    return QColor(
        round(c1.red() + (c2.red() - c1.red()) * t),
        round(c1.green() + (c2.green() - c1.green()) * t),
        round(c1.blue() + (c2.blue() - c1.blue()) * t),
        round(c1.alpha() + (c2.alpha() - c1.alpha()) * t),
    )


def stylesheet() -> str:
    t = T.hex
    return f"""
* {{
    font-family: "{ui_font_family()}";
    color: {t('text')};
    outline: none;
}}
QMainWindow, QDialog {{ background: {t('bg')}; }}
QWidget#Page, QWidget#Content, QScrollArea#PageScroll > QWidget > QWidget {{ background: {t('bg')}; }}
QScrollArea {{ background: transparent; border: none; }}
QToolTip {{
    background: {t('surface2')}; color: {t('text')};
    border: 1px solid {t('border')}; padding: 6px 8px; border-radius: 6px;
}}
QLabel {{ background: transparent; }}
QLabel[role="h1"] {{ font-size: 22pt; font-weight: 700; }}
QLabel[role="h2"] {{ font-size: 15pt; font-weight: 700; }}
QLabel[role="h3"] {{ font-size: 12pt; font-weight: 600; }}
QLabel[role="muted"] {{ color: {t('muted')}; }}
QLabel[role="faint"] {{ color: {t('faint')}; }}
QLabel[role="chip"] {{
    color: {t('muted')}; background: {t('surface2')};
    border-radius: 9px; padding: 2px 9px; font-size: 8.5pt; font-weight: 600;
}}

QPushButton {{
    background: {t('surface2')}; border: 1px solid {t('border')};
    border-radius: 10px; padding: 9px 18px; font-size: 10.5pt; font-weight: 600;
}}
QPushButton:hover {{ background: {t('surface3')}; }}
QPushButton:pressed {{ background: {t('border')}; }}
QPushButton:disabled {{ color: {t('faint')}; background: {t('surface')}; }}
QPushButton[kind="primary"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {t('accent')}, stop:1 #5B8CFF);
    color: {t('on_accent')}; border: none;
}}
QPushButton[kind="primary"]:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {t('accent_hover')}, stop:1 #6F9BFF);
}}
QPushButton[kind="primary"]:disabled {{ background: {t('surface3')}; color: {t('faint')}; }}
QPushButton[kind="ghost"] {{ background: transparent; border: 1px solid transparent; color: {t('muted')}; }}
QPushButton[kind="ghost"]:hover {{ background: {t('surface2')}; color: {t('text')}; }}
QPushButton[kind="danger"] {{ background: transparent; border: 1px solid {t('danger')}; color: {t('danger')}; }}
QPushButton[kind="danger"]:hover {{ background: {t('danger')}; color: white; }}
QPushButton[size="lg"] {{ padding: 13px 28px; font-size: 12pt; border-radius: 12px; }}
QPushButton[size="sm"] {{ padding: 5px 12px; font-size: 9.5pt; border-radius: 8px; }}

QPushButton[kind="seg"] {{
    background: {t('surface')}; border: 1px solid {t('border')}; border-radius: 9px;
    padding: 7px 14px; font-weight: 600; color: {t('muted')};
}}
QPushButton[kind="seg"]:hover {{ color: {t('text')}; background: {t('surface2')}; }}
QPushButton[kind="seg"]:checked {{
    background: {t('accent')}; border-color: {t('accent')}; color: {t('on_accent')};
}}

QPushButton[kind="nav"] {{
    text-align: left; padding: 10px 14px; border-radius: 10px; border: none;
    background: transparent; color: {t('muted')}; font-size: 10.5pt; font-weight: 600;
}}
QPushButton[kind="nav"]:hover {{ background: {t('surface2')}; color: {t('text')}; }}
QPushButton[kind="nav"]:checked {{ background: {t('surface3')}; color: {t('text')}; }}

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox {{
    background: {t('surface')}; border: 1px solid {t('border')}; border-radius: 9px;
    padding: 8px 10px; selection-background-color: {t('accent')}; font-size: 10.5pt;
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 1px solid {t('accent')};
}}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox QAbstractItemView {{
    background: {t('surface')}; border: 1px solid {t('border')};
    selection-background-color: {t('surface3')}; padding: 4px;
}}

QCheckBox {{ spacing: 8px; font-size: 10.5pt; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 5px;
    border: 1px solid {t('border')}; background: {t('surface')};
}}
QCheckBox::indicator:checked {{ background: {t('accent')}; border-color: {t('accent')}; }}

QSlider::groove:horizontal {{ height: 6px; background: {t('surface3')}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {t('accent')}; border-radius: 3px; }}
QSlider::handle:horizontal {{
    background: {t('text')}; width: 16px; height: 16px; margin: -5px 0; border-radius: 8px;
}}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t('surface3')}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {t('faint')}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t('surface3')}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

QTableWidget, QListWidget, QTreeWidget {{
    background: {t('surface')}; border: 1px solid {t('border')}; border-radius: 10px;
    gridline-color: {t('border')}; alternate-background-color: {t('surface2')};
}}
QTableWidget::item, QListWidget::item {{ padding: 6px; }}
QTableWidget::item:selected, QListWidget::item:selected {{ background: {t('surface3')}; color: {t('text')}; }}
QHeaderView::section {{
    background: {t('surface2')}; color: {t('muted')}; border: none;
    border-bottom: 1px solid {t('border')}; padding: 8px; font-weight: 600;
}}
QTableCornerButton::section {{ background: {t('surface2')}; border: none; }}

QMessageBox {{ background: {t('surface')}; }}
QMessageBox QLabel {{ font-size: 10.5pt; }}
QMenu {{ background: {t('surface')}; border: 1px solid {t('border')}; padding: 6px; border-radius: 8px; }}
QMenu::item {{ padding: 7px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t('surface3')}; }}
"""


def apply_theme(app: QApplication, name: str) -> None:
    T.set(name)
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, T.c("bg"))
    pal.setColor(QPalette.ColorRole.WindowText, T.c("text"))
    pal.setColor(QPalette.ColorRole.Base, T.c("surface"))
    pal.setColor(QPalette.ColorRole.AlternateBase, T.c("surface2"))
    pal.setColor(QPalette.ColorRole.Text, T.c("text"))
    pal.setColor(QPalette.ColorRole.Button, T.c("surface2"))
    pal.setColor(QPalette.ColorRole.ButtonText, T.c("text"))
    pal.setColor(QPalette.ColorRole.Highlight, T.c("accent"))
    pal.setColor(QPalette.ColorRole.HighlightedText, T.c("on_accent"))
    pal.setColor(QPalette.ColorRole.ToolTipBase, T.c("surface2"))
    pal.setColor(QPalette.ColorRole.ToolTipText, T.c("text"))
    pal.setColor(QPalette.ColorRole.PlaceholderText, T.c("faint"))
    app.setPalette(pal)
    app.setStyleSheet(stylesheet())
    for w in app.allWidgets():
        w.update()
