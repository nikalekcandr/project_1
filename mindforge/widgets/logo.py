"""Логотип приложения и иконка окна."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget

from ..theme import T, font
from . import icons


def paint_logo(p: QPainter, r: QRectF) -> None:
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    g = QLinearGradient(r.topLeft(), r.bottomRight())
    g.setColorAt(0.0, QColor("#8B5CF6"))
    g.setColorAt(0.55, QColor("#6366F1"))
    g.setColorAt(1.0, QColor("#06B6D4"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    rad = r.width() * 0.26
    p.drawRoundedRect(r, rad, rad)
    hl = QRadialGradient(r.left() + r.width() * 0.3, r.top() + r.height() * 0.2, r.width() * 0.8)
    hl.setColorAt(0, QColor(255, 255, 255, 70))
    hl.setColorAt(1, QColor(255, 255, 255, 0))
    p.setBrush(hl)
    p.drawRoundedRect(r, rad, rad)
    s = r.width() * 0.64
    icons.paint_icon(p, "brain", QRectF(r.center().x() - s / 2, r.center().y() - s / 2, s, s), "#FFFFFF",
                     stroke=2.1)
    p.restore()


def logo_pixmap(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    paint_logo(p, QRectF(0, 0, size, size).adjusted(size * 0.03, size * 0.03, -size * 0.03, -size * 0.03))
    p.end()
    return pm


def app_icon() -> QIcon:
    ic = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(logo_pixmap(s))
    return ic


class LogoHeader(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(52)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_logo(p, QRectF(4, 6, 40, 40))
        p.setPen(T.c("text"))
        p.setFont(font(14.5, QFont.Weight.Bold))
        p.drawText(QRectF(56, 4, 200, 26), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "MindForge")
        p.setPen(T.c("muted"))
        p.setFont(font(8.5, QFont.Weight.DemiBold))
        p.drawText(QRectF(57, 28, 200, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "тренажёр для мозга")
