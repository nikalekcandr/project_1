"""Графики, нарисованные вручную: линия, радар, календарь активности."""
from __future__ import annotations

import math
from datetime import date, timedelta

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from ..theme import T, font, mix

MONTHS_SHORT = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


def nice_bounds(lo: float, hi: float, fixed_lo: float | None = None, fixed_hi: float | None = None,
                ticks: int = 4) -> tuple[float, float]:
    """Подбирает границы оси с «красивым» шагом (1, 2, 2.5, 5 × 10^k)."""
    if fixed_lo is not None:
        lo = fixed_lo
    if fixed_hi is not None:
        hi = fixed_hi
    if hi - lo < 1e-9:
        lo, hi = lo - 10, hi + 10
    raw = (hi - lo) / ticks
    mag = 10 ** math.floor(math.log10(raw))
    steps = [m * mag * k for k in (1, 10, 100) for m in (1, 2, 2.5, 5)]
    for step in steps:
        if step < raw:
            continue
        nlo = fixed_lo if fixed_lo is not None else math.floor(lo / step) * step
        if fixed_lo is None and lo >= 0 > nlo:
            nlo = 0.0
        nhi = nlo + step * ticks
        if nhi >= hi - 1e-9:
            return nlo, (fixed_hi if fixed_hi is not None else nhi)
    return lo, hi


class LineChart(QWidget):
    def __init__(self, parent=None, height: int = 220) -> None:
        super().__init__(parent)
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMouseTracking(True)
        self.points: list[tuple[str, float]] = []
        self.y_min: float | None = 0
        self.y_max: float | None = 100
        self.color: QColor | None = None
        self.value_fmt = lambda v: f"{v:.0f}"
        self.empty_text = "Пока нет данных — выполните упражнение"
        self._hover = -1
        self._xy: list[QPointF] = []

    def set_data(self, points: list[tuple[str, float]], y_min: float | None = 0, y_max: float | None = 100,
                 color: QColor | None = None) -> None:
        self.points = points
        self.y_min, self.y_max = y_min, y_max
        self.color = color
        self._hover = -1
        self.update()

    def _range(self) -> tuple[float, float]:
        vals = [v for _, v in self.points]
        lo = self.y_min if self.y_min is not None else min(vals)
        hi = self.y_max if self.y_max is not None else max(vals)
        if self.y_min is not None and self.y_max is not None:
            return lo, hi if hi > lo else lo + 1
        return nice_bounds(lo, hi, self.y_min, self.y_max)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(44, 14, -16, -30)
        col = QColor(self.color or T.c("accent"))
        p.setFont(font(8.5))
        if not self.points:
            p.setPen(T.c("faint"))
            p.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, self.empty_text)
            return
        lo, hi = self._range()
        # сетка
        for i in range(5):
            y = r.bottom() - r.height() * i / 4
            p.setPen(QPen(T.c("border"), 1, Qt.PenStyle.DashLine if i else Qt.PenStyle.SolidLine))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(T.c("faint"))
            val = lo + (hi - lo) * i / 4
            p.drawText(QRectF(0, y - 9, r.left() - 8, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       self.value_fmt(val))
        n = len(self.points)
        xs = [r.left() + (r.width() * i / (n - 1) if n > 1 else r.width() / 2) for i in range(n)]
        ys = [r.bottom() - (v - lo) / (hi - lo) * r.height() for _, v in self.points]
        self._xy = [QPointF(x, y) for x, y in zip(xs, ys)]
        # подписи оси X (не больше ~7)
        p.setPen(T.c("faint"))
        step = max(1, math.ceil(n / 7))
        for i in range(0, n, step):
            p.drawText(QRectF(xs[i] - 40, r.bottom() + 8, 80, 16), Qt.AlignmentFlag.AlignCenter, self.points[i][0])
        # заливка
        path = QPainterPath()
        path.moveTo(self._xy[0])
        for i in range(1, n):
            a, b = self._xy[i - 1], self._xy[i]
            mx = (a.x() + b.x()) / 2
            path.cubicTo(QPointF(mx, a.y()), QPointF(mx, b.y()), b)
        area = QPainterPath(path)
        area.lineTo(QPointF(xs[-1], r.bottom()))
        area.lineTo(QPointF(xs[0], r.bottom()))
        area.closeSubpath()
        g = QLinearGradient(0, r.top(), 0, r.bottom())
        c1 = QColor(col)
        c1.setAlpha(90)
        c2 = QColor(col)
        c2.setAlpha(0)
        g.setColorAt(0, c1)
        g.setColorAt(1, c2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawPath(area)
        pen = QPen(col, 2.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        for i, pt in enumerate(self._xy):
            big = i == self._hover or i == n - 1
            p.setPen(QPen(col, 2))
            p.setBrush(T.c("surface") if not big else col)
            rad = 5 if big else 3.2
            if n <= 40 or big:
                p.drawEllipse(pt, rad, rad)
        if 0 <= self._hover < n:
            pt = self._xy[self._hover]
            p.setPen(QPen(T.c("faint"), 1, Qt.PenStyle.DotLine))
            p.drawLine(QPointF(pt.x(), r.top()), QPointF(pt.x(), r.bottom()))

    def mouseMoveEvent(self, e) -> None:
        if not self._xy:
            return
        x = e.position().x()
        idx = min(range(len(self._xy)), key=lambda i: abs(self._xy[i].x() - x))
        if idx != self._hover:
            self._hover = idx
            lbl, val = self.points[idx]
            QToolTip.showText(e.globalPosition().toPoint(), f"{lbl}: {self.value_fmt(val)}", self)
            self.update()

    def leaveEvent(self, e) -> None:
        self._hover = -1
        self.update()


class RadarChart(QWidget):
    def __init__(self, parent=None, size: int = 300) -> None:
        super().__init__(parent)
        self.setMinimumSize(size, size)
        self.axes: list[tuple[str, float | None, QColor]] = []
        self.show_values = True
        self.compact = False

    def set_data(self, axes: list[tuple[str, float | None, QColor]]) -> None:
        self.axes = axes
        self.update()

    def heightForWidth(self, w: int) -> int:
        return w

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        n = len(self.axes)
        if n < 3:
            return
        side = min(self.width(), self.height())
        cx, cy = self.width() / 2, self.height() / 2
        label_pad = 38 if self.compact else 50
        rad = side / 2 - label_pad
        ang = [(-math.pi / 2) + 2 * math.pi * i / n for i in range(n)]

        def pt(i: int, frac: float) -> QPointF:
            return QPointF(cx + rad * frac * math.cos(ang[i]), cy + rad * frac * math.sin(ang[i]))

        # сетка
        for k in range(1, 5):
            poly = QPolygonF([pt(i, k / 4) for i in range(n)])
            p.setPen(QPen(T.c("border"), 1))
            p.setBrush(Qt.BrushStyle.NoBrush if k < 4 else T.c("surface2", 90))
            p.drawPolygon(poly)
        for i in range(n):
            p.setPen(QPen(T.c("border"), 1))
            p.drawLine(QPointF(cx, cy), pt(i, 1))
        # значения
        vals = [(v if v is not None else 0) / 100 for _, v, _ in self.axes]
        if any(v > 0 for v in vals):
            poly = QPolygonF([pt(i, max(0.03, vals[i])) for i in range(n)])
            g = QLinearGradient(cx - rad, cy - rad, cx + rad, cy + rad)
            c1 = T.c("accent", 120)
            c2 = T.c("accent2", 90)
            g.setColorAt(0, c1)
            g.setColorAt(1, c2)
            p.setBrush(g)
            p.setPen(QPen(T.c("accent"), 2.2))
            p.drawPolygon(poly)
            for i in range(n):
                if self.axes[i][1] is not None:
                    p.setPen(QPen(T.c("surface"), 2))
                    p.setBrush(self.axes[i][2])
                    p.drawEllipse(pt(i, max(0.03, vals[i])), 5, 5)
        # подписи
        f = font(8.5 if self.compact else 9.5, QFont.Weight.DemiBold)
        p.setFont(f)
        for i, (name, v, col) in enumerate(self.axes):
            lp = pt(i, 1.0)
            dx, dy = math.cos(ang[i]), math.sin(ang[i])
            box = QRectF(0, 0, 110, 34)
            box.moveCenter(QPointF(lp.x() + dx * (label_pad - 6), lp.y() + dy * (label_pad - 14)))
            if box.left() < 0:
                box.moveLeft(0)
            if box.right() > self.width():
                box.moveRight(self.width())
            p.setPen(col)
            text = name
            if self.show_values:
                text += "\n" + (f"{v:.0f}" if v is not None else "—")
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)


class Heatmap(QWidget):
    """Календарь активности за последние недели (как на GitHub)."""

    def __init__(self, weeks: int = 20, parent=None) -> None:
        super().__init__(parent)
        self.weeks = weeks
        self.data: dict[str, dict] = {}
        self.today = date.today()
        self.setMouseTracking(True)
        self.setMinimumHeight(18 + 7 * 19 + 4)
        self._cells: list[tuple[QRectF, date]] = []

    def set_data(self, data: dict[str, dict], today: date) -> None:
        self.data = data
        self.today = today
        self.update()

    def _level(self, d: date) -> int:
        info = self.data.get(d.isoformat())
        if not info:
            return 0
        n = info.get("sessions", 0) + info.get("reviews", 0) / 10
        if n <= 0:
            return 0
        if n < 2:
            return 1
        if n < 4:
            return 2
        if n < 7:
            return 3
        return 4

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        left = 26
        avail_w = self.width() - left
        cell = min(16.0, max(9.0, avail_w / self.weeks - 3))
        gap = 3.0
        weeks = max(4, min(self.weeks, int((avail_w + gap) // (cell + gap))))
        start = self.today - timedelta(days=self.today.weekday()) - timedelta(weeks=weeks - 1)
        self._cells = []
        p.setFont(font(7.5))
        p.setPen(T.c("faint"))
        for row, name in ((0, "пн"), (2, "ср"), (4, "пт")):
            p.drawText(QRectF(0, 18 + row * (cell + gap), left - 4, cell),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, name)
        accent = T.c("accent")
        base = T.c("surface3")
        last_month = None
        last_label_x = -100.0
        for w in range(weeks):
            for d in range(7):
                day = start + timedelta(weeks=w, days=d)
                if day > self.today:
                    continue
                x = left + w * (cell + gap)
                y = 18 + d * (cell + gap)
                lvl = self._level(day)
                col = base if lvl == 0 else mix(mix(base, accent, 0.35), T.c("accent2") if lvl == 4 else accent, lvl / 4)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(col)
                r = QRectF(x, y, cell, cell)
                p.drawRoundedRect(r, 3.5, 3.5)
                if day == self.today:
                    p.setPen(QPen(T.c("text"), 1.3))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRoundedRect(r.adjusted(-1, -1, 1, 1), 4, 4)
                self._cells.append((r, day))
                if d == 0 and day.month != last_month:
                    last_month = day.month
                    if x - last_label_x >= 30:
                        last_label_x = x
                        p.setPen(T.c("faint"))
                        p.drawText(QRectF(x, 0, 40, 14), Qt.AlignmentFlag.AlignLeft, MONTHS_SHORT[day.month - 1])

    def mouseMoveEvent(self, e) -> None:
        pos = e.position()
        for r, day in self._cells:
            if r.contains(pos):
                info = self.data.get(day.isoformat(), {})
                s = info.get("sessions", 0)
                rv = info.get("reviews", 0)
                txt = f"{day.day} {MONTHS_SHORT[day.month - 1]} {day.year}\nУпражнений: {s}"
                if rv:
                    txt += f"\nКарточек повторено: {rv}"
                QToolTip.showText(e.globalPosition().toPoint(), txt, self)
                return
        QToolTip.hideText()


class Sparkline(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.values: list[float] = []
        self.color: QColor | None = None
        self.setMinimumHeight(28)

    def set_values(self, values: list[float], color: QColor | None = None) -> None:
        self.values = values
        self.color = color
        self.update()

    def paintEvent(self, e) -> None:
        if len(self.values) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        lo, hi = min(self.values), max(self.values)
        if hi - lo < 1e-6:
            hi = lo + 1
        pts = [
            QPointF(r.left() + r.width() * i / (len(self.values) - 1), r.bottom() - (v - lo) / (hi - lo) * r.height())
            for i, v in enumerate(self.values)
        ]
        col = QColor(self.color or T.c("accent"))
        p.setPen(QPen(col, 2))
        p.drawPolyline(QPolygonF(pts))
        p.setBrush(col)
        p.drawEllipse(pts[-1], 3, 3)
