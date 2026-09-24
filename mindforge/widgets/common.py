"""Общие элементы интерфейса: карточки, кнопки, кольца прогресса, уведомления."""
from __future__ import annotations

import math
from typing import Callable, Iterable

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..theme import T, font, mix
from . import icons


def label(text: str = "", role: str | None = None, wrap: bool = False, align=None) -> QLabel:
    lb = QLabel(text)
    if role:
        lb.setProperty("role", role)
    if role == "chip":
        lb.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    lb.setWordWrap(wrap)
    if align is not None:
        lb.setAlignment(align)
    return lb


def button(
    text: str = "",
    kind: str | None = None,
    size: str | None = None,
    icon_name: str | None = None,
    on_click: Callable | None = None,
    icon_color: str | None = None,
) -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setProperty("kind", kind)
    if size:
        b.setProperty("size", size)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if icon_name:
        col = icon_color or (T.hex("on_accent") if kind == "primary" else T.hex("text"))
        b.setIcon(icons.icon(icon_name, col, 18))
        b.setIconSize(QSize(18, 18))
    if on_click:
        b.clicked.connect(on_click)
    return b


def hbox(*items, spacing: int = 10, margins=(0, 0, 0, 0)) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for it in items:
        _add(lay, it)
    return lay


def vbox(*items, spacing: int = 10, margins=(0, 0, 0, 0)) -> QVBoxLayout:
    lay = QVBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for it in items:
        _add(lay, it)
    return lay


def _add(lay, it) -> None:
    if it is None:
        return
    if it == "stretch":
        lay.addStretch(1)
    elif isinstance(it, int):
        lay.addSpacing(it)
    elif isinstance(it, QLayout):
        lay.addLayout(it)
    else:
        lay.addWidget(it)


def clear_layout(lay: QLayout) -> None:
    while lay.count():
        item = lay.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


def shadow(widget: QWidget, blur: int = 28, dy: int = 6, alpha: int = 90) -> None:
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(0, dy)
    col = T.c("shadow")
    col.setAlpha(alpha if T.is_dark else alpha // 2)
    eff.setColor(col)
    widget.setGraphicsEffect(eff)


class Card(QFrame):
    """Скруглённая панель. При clickable=True подсвечивается и излучает clicked."""

    clicked = Signal()

    def __init__(self, parent=None, clickable: bool = False, radius: int = 16, padding: int = 20,
                 accent: QColor | None = None, tint: str | None = None) -> None:
        super().__init__(parent)
        self.clickable = clickable
        self.radius = radius
        self.accent = accent
        self.tint = tint
        self._hover = 0.0
        self._anim = QPropertyAnimation(self, b"hover", self)
        self._anim.setDuration(160)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, clickable)
        if clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(padding, padding, padding, padding)
        self.lay.setSpacing(10)

    def _get_hover(self) -> float:
        return self._hover

    def _set_hover(self, v: float) -> None:
        self._hover = v
        self.update()

    hover = Property(float, _get_hover, _set_hover)

    def enterEvent(self, e) -> None:
        if self.clickable:
            self._anim.stop()
            self._anim.setEndValue(1.0)
            self._anim.start()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        if self.clickable:
            self._anim.stop()
            self._anim.setEndValue(0.0)
            self._anim.start()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if self.clickable and e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        bg = T.c("surface")
        if self.tint:
            bg = mix(bg, QColor(self.tint), 0.10)
        bg = mix(bg, T.c("surface2"), self._hover * 0.8)
        border = mix(T.c("border"), self.accent or T.c("accent"), self._hover * 0.7)
        p.setPen(QPen(border, 1))
        p.setBrush(bg)
        p.drawRoundedRect(r, self.radius, self.radius)
        if self.accent is not None:
            glow = QColor(self.accent)
            glow.setAlpha(int(22 + 30 * self._hover))
            g = QLinearGradient(r.topLeft(), r.bottomRight())
            g.setColorAt(0, glow)
            glow.setAlpha(0)
            g.setColorAt(0.6, glow)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawRoundedRect(r, self.radius, self.radius)


class IconBadge(QWidget):
    """Иконка на скруглённой подложке цвета домена."""

    def __init__(self, name: str, color: QColor | None = None, size: int = 44, parent=None) -> None:
        super().__init__(parent)
        self.name = name
        self.color = color
        self.setFixedSize(size, size)

    def set_icon(self, name: str, color: QColor | None = None) -> None:
        self.name = name
        if color is not None:
            self.color = color
        self.update()

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = QColor(self.color or T.c("accent"))
        r = QRectF(self.rect())
        bg = QColor(col)
        bg.setAlpha(40 if T.is_dark else 34)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, r.width() * 0.3, r.width() * 0.3)
        s = r.width() * 0.52
        icons.paint_icon(p, self.name, QRectF(r.center().x() - s / 2, r.center().y() - s / 2, s, s), col)


class IconView(QWidget):
    def __init__(self, name: str, color: QColor | str | None = None, size: int = 20, parent=None) -> None:
        super().__init__(parent)
        self.name = name
        self.color = color
        self.setFixedSize(size, size)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        icons.paint_icon(p, self.name, QRectF(self.rect()), self.color or T.c("text"))


class ProgressRing(QWidget):
    """Круговой индикатор со значением в центре. Анимирует изменения."""

    def __init__(self, size: int = 120, thickness: int = 10, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.thickness = thickness
        self._value = 0.0
        self.text = ""
        self.subtext = ""
        self.color: QColor | None = None
        self.color2: QColor | None = None
        self.text_size = size / 5.2
        self._anim = QPropertyAnimation(self, b"value", self)
        self._anim.setDuration(900)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _get(self) -> float:
        return self._value

    def _set(self, v: float) -> None:
        self._value = v
        self.update()

    value = Property(float, _get, _set)

    def set_value(self, v: float, animate: bool = True) -> None:
        v = max(0.0, min(1.0, v))
        if animate:
            self._anim.stop()
            self._anim.setStartValue(self._value)
            self._anim.setEndValue(v)
            self._anim.start()
        else:
            self._set(v)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self.thickness
        r = QRectF(self.rect()).adjusted(t / 2 + 1, t / 2 + 1, -t / 2 - 1, -t / 2 - 1)
        pen = QPen(T.c("surface3"), t)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(r, 0, 360 * 16)
        if self._value > 0.001:
            c1 = QColor(self.color or T.c("accent"))
            c2 = QColor(self.color2 or T.c("accent2"))
            g = QLinearGradient(r.topLeft(), r.bottomRight())
            g.setColorAt(0, c1)
            g.setColorAt(1, c2)
            pen = QPen(g, t)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawArc(r, 90 * 16, -int(360 * 16 * self._value))
        p.setPen(T.c("text"))
        f = font(self.text_size * 0.75, QFont.Weight.Bold)
        f.setPixelSize(int(self.text_size))
        p.setFont(f)
        tr = QRectF(self.rect())
        if self.subtext:
            p.drawText(tr.adjusted(0, -self.text_size * 0.35, 0, -self.text_size * 0.35), Qt.AlignmentFlag.AlignCenter, self.text)
            f2 = font(9, QFont.Weight.DemiBold)
            f2.setPixelSize(max(10, int(self.text_size * 0.42)))
            p.setFont(f2)
            p.setPen(T.c("muted"))
            p.drawText(tr.adjusted(0, self.text_size * 0.95, 0, self.text_size * 0.95), Qt.AlignmentFlag.AlignCenter, self.subtext)
        else:
            p.drawText(tr, Qt.AlignmentFlag.AlignCenter, self.text)


class Bar(QWidget):
    """Тонкая полоса прогресса с градиентом."""

    def __init__(self, height: int = 8, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._value = 0.0
        self.color: QColor | None = None
        self.color2: QColor | None = None
        self._anim = QPropertyAnimation(self, b"value", self)
        self._anim.setDuration(600)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _get(self) -> float:
        return self._value

    def _set(self, v: float) -> None:
        self._value = v
        self.update()

    value = Property(float, _get, _set)

    def set_value(self, v: float, animate: bool = True) -> None:
        v = max(0.0, min(1.0, v))
        if animate:
            self._anim.stop()
            self._anim.setStartValue(self._value)
            self._anim.setEndValue(v)
            self._anim.start()
        else:
            self._set(v)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        rad = r.height() / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(T.c("surface3"))
        p.drawRoundedRect(r, rad, rad)
        if self._value > 0:
            w = max(r.height(), r.width() * self._value)
            fr = QRectF(r.x(), r.y(), w, r.height())
            g = QLinearGradient(fr.topLeft(), fr.topRight())
            g.setColorAt(0, QColor(self.color or T.c("accent")))
            g.setColorAt(1, QColor(self.color2 or self.color or T.c("accent2")))
            p.setBrush(g)
            p.drawRoundedRect(fr, rad, rad)


class Segmented(QWidget):
    """Сегментированный переключатель вариантов."""

    changed = Signal(str)

    def __init__(self, choices: Iterable[tuple[str, str]], value: str | None = None, parent=None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        for val, text in choices:
            b = QPushButton(text)
            b.setProperty("kind", "seg")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, v=val: self._on(v))
            self.group.addButton(b)
            lay.addWidget(b)
            self.buttons[val] = b
        lay.addStretch(1)
        self._value = None
        if value is not None:
            self.set_value(value)
        elif self.buttons:
            self.set_value(next(iter(self.buttons)))

    def _on(self, v: str) -> None:
        if v != self._value:
            self._value = v
            self.changed.emit(v)

    def set_value(self, v: str) -> None:
        if v in self.buttons:
            self.buttons[v].setChecked(True)
            self._value = v

    def value(self) -> str | None:
        return self._value


class StatTile(Card):
    def __init__(self, icon_name: str, title: str, value: str = "—", sub: str = "", color: QColor | None = None) -> None:
        super().__init__(padding=16)
        self.badge = IconBadge(icon_name, color, 40)
        self.value_lbl = label(value)
        self.value_lbl.setFont(font(17, QFont.Weight.Bold))
        self.title_lbl = label(title, "muted")
        self.sub_lbl = label(sub, "faint")
        self.sub_lbl.setVisible(bool(sub))
        col = vbox(self.value_lbl, self.title_lbl, self.sub_lbl, spacing=1)
        self.lay.addLayout(hbox(self.badge, col, "stretch", spacing=14))

    def set(self, value: str, sub: str | None = None) -> None:
        self.value_lbl.setText(value)
        if sub is not None:
            self.sub_lbl.setText(sub)
            self.sub_lbl.setVisible(bool(sub))


class Toast(QFrame):
    """Всплывающее уведомление в правом верхнем углу окна."""

    active: list["Toast"] = []

    def __init__(self, parent: QWidget, title: str, text: str, icon_name: str = "award",
                 color: QColor | None = None, msec: int = 4200) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.color = color or T.c("warning")
        self.setFixedWidth(340)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 14, 18, 14)
        lay.setSpacing(12)
        lay.addWidget(IconBadge(icon_name, self.color, 42))
        t = label(title)
        t.setFont(font(10.5, QFont.Weight.Bold))
        d = label(text, "muted", wrap=True)
        lay.addLayout(vbox(t, d, spacing=2), 1)
        self.adjustSize()
        self.eff = QGraphicsOpacityEffect(self)
        self.eff.setOpacity(0.0)
        self.setGraphicsEffect(self.eff)
        Toast.active.append(self)
        self._reposition()
        self.show()
        self.raise_()
        self._fade(1.0)
        QTimer.singleShot(msec, self._close)

    def _reposition(self) -> None:
        par = self.parentWidget()
        y = 20
        for t in Toast.active:
            if t is self:
                break
            if t.parentWidget() is par:
                y += t.height() + 10
        self.move(par.width() - self.width() - 24, y)

    def _fade(self, to: float) -> None:
        a = QPropertyAnimation(self.eff, b"opacity", self)
        a.setDuration(250)
        a.setEndValue(to)
        a.start()
        self._a = a

    def _close(self) -> None:
        self._fade(0.0)
        QTimer.singleShot(260, self._remove)

    def _remove(self) -> None:
        if self in Toast.active:
            Toast.active.remove(self)
        self.deleteLater()

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(mix(T.c("border"), self.color, 0.5), 1.2))
        p.setBrush(T.c("surface2"))
        p.drawRoundedRect(r, 14, 14)


class ScrollPage(QScrollArea):
    """Прокручиваемая страница с центрированным контентом ограниченной ширины."""

    def __init__(self, max_width: int = 1180, margins=(36, 28, 36, 36), parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("PageScroll")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer = QWidget()
        outer.setObjectName("Page")
        ol = QHBoxLayout(outer)
        ol.setContentsMargins(*margins)
        self.body = QWidget()
        self.body.setMaximumWidth(max_width)
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 0, 0)
        self.body_lay.setSpacing(18)
        ol.addStretch(0)
        ol.addWidget(self.body, 1)
        ol.addStretch(0)
        self.setWidget(outer)


class ResponsiveGrid(QWidget):
    """Сетка, меняющая число колонок в зависимости от ширины."""

    def __init__(self, min_col_width: int = 260, spacing: int = 16, parent=None) -> None:
        super().__init__(parent)
        self.min_col_width = min_col_width
        self.spacing = spacing
        self.items: list[QWidget] = []
        from PySide6.QtWidgets import QGridLayout

        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(spacing)
        self._cols = 0

    def set_items(self, widgets: list[QWidget]) -> None:
        for w in self.items:
            self.grid.removeWidget(w)
            w.setParent(None)
            w.deleteLater()
        self.items = list(widgets)
        self._cols = 0
        self._relayout()

    def _relayout(self) -> None:
        w = max(1, self.width())
        col_w = max([self.min_col_width] + [it.minimumSizeHint().width() for it in self.items])
        cols = max(1, (w + self.spacing) // (col_w + self.spacing))
        if cols == self._cols and all(self.grid.indexOf(it) >= 0 for it in self.items):
            return
        self._cols = cols
        for it in self.items:
            self.grid.removeWidget(it)
        for i, it in enumerate(self.items):
            self.grid.addWidget(it, i // cols, i % cols)
        for c in range(self.grid.columnCount()):
            self.grid.setColumnStretch(c, 1 if c < cols else 0)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._relayout()


class FeedbackFlash(QWidget):
    """Полупрозрачная вспышка поверх виджета (зелёная/красная)."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._alpha = 0.0
        self.color = T.c("success")
        self._anim = QPropertyAnimation(self, b"alpha", self)
        self._anim.setDuration(380)
        self._anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        self.hide()

    def _get(self) -> float:
        return self._alpha

    def _set(self, v: float) -> None:
        self._alpha = v
        self.setVisible(v > 0.01)
        self.update()

    alpha = Property(float, _get, _set)

    def flash(self, good: bool) -> None:
        self.color = T.c("success" if good else "danger")
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self._anim.stop()
        self._anim.setStartValue(0.22)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QColor(self.color)
        c.setAlphaF(self._alpha)
        pen = QPen(c, 6)
        p.setPen(pen)
        c2 = QColor(self.color)
        c2.setAlphaF(self._alpha * 0.35)
        p.setBrush(c2)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(3, 3, -3, -3), 18, 18)


class Hearts(QWidget):
    """Индикатор жизней."""

    def __init__(self, total: int = 3, parent=None) -> None:
        super().__init__(parent)
        self.total = total
        self.left = total
        self.setFixedSize(total * 26, 24)

    def set_left(self, n: int) -> None:
        self.left = n
        self.update()

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i in range(self.total):
            r = QRectF(i * 26 + 1, 1, 22, 22)
            if i < self.left:
                icons.paint_icon(p, "heart_fill", r, T.c("danger"))
            else:
                icons.paint_icon(p, "heart", r, T.c("faint"))


def rounded_path(r: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(r, radius, radius)
    return path


def star_path(cx: float, cy: float, r_out: float, r_in: float, points: int = 5) -> QPainterPath:
    path = QPainterPath()
    for i in range(points * 2):
        ang = -math.pi / 2 + i * math.pi / points
        rad = r_out if i % 2 == 0 else r_in
        pt = QPointF(cx + rad * math.cos(ang), cy + rad * math.sin(ang))
        if i == 0:
            path.moveTo(pt)
        else:
            path.lineTo(pt)
    path.closeSubpath()
    return path


__all__ = [
    "label", "button", "hbox", "vbox", "clear_layout", "shadow", "Card", "IconBadge", "IconView",
    "ProgressRing", "Bar", "Segmented", "StatTile", "Toast", "ScrollPage", "ResponsiveGrid",
    "FeedbackFlash", "Hearts", "rounded_path", "star_path", "QPoint", "QRect",
]
