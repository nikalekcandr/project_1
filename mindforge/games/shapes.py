"""Отрисовка простых фигур (для «Совпадения» и «Логических матриц»)."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath, QPolygonF

SHAPES = ["circle", "square", "triangle", "diamond", "star", "hexagon", "cross", "heart"]


def polygon(cx: float, cy: float, r: float, sides: int, rotation: float = -math.pi / 2) -> QPolygonF:
    return QPolygonF(
        [QPointF(cx + r * math.cos(rotation + 2 * math.pi * i / sides),
                 cy + r * math.sin(rotation + 2 * math.pi * i / sides)) for i in range(sides)]
    )


def shape_path(kind: str, rect: QRectF) -> QPainterPath:
    cx, cy = rect.center().x(), rect.center().y()
    r = min(rect.width(), rect.height()) / 2
    path = QPainterPath()
    if kind == "circle":
        path.addEllipse(QPointF(cx, cy), r * 0.92, r * 0.92)
    elif kind == "square":
        s = r * 1.62
        path.addRoundedRect(QRectF(cx - s / 2, cy - s / 2, s, s), r * 0.14, r * 0.14)
    elif kind == "triangle":
        path.addPolygon(polygon(cx, cy + r * 0.12, r * 1.05, 3))
        path.closeSubpath()
    elif kind == "diamond":
        path.addPolygon(QPolygonF([QPointF(cx, cy - r), QPointF(cx + r * 0.75, cy), QPointF(cx, cy + r),
                                   QPointF(cx - r * 0.75, cy)]))
        path.closeSubpath()
    elif kind == "pentagon":
        path.addPolygon(polygon(cx, cy + r * 0.05, r * 0.98, 5))
        path.closeSubpath()
    elif kind == "hexagon":
        path.addPolygon(polygon(cx, cy, r * 0.95, 6, 0))
        path.closeSubpath()
    elif kind == "star":
        pts = []
        for i in range(10):
            ang = -math.pi / 2 + i * math.pi / 5
            rad = r if i % 2 == 0 else r * 0.45
            pts.append(QPointF(cx + rad * math.cos(ang), cy + rad * math.sin(ang) + r * 0.06))
        path.addPolygon(QPolygonF(pts))
        path.closeSubpath()
    elif kind == "cross":
        w = r * 0.62
        path.addRoundedRect(QRectF(cx - w / 2, cy - r * 0.92, w, r * 1.84), r * 0.1, r * 0.1)
        path.addRoundedRect(QRectF(cx - r * 0.92, cy - w / 2, r * 1.84, w), r * 0.1, r * 0.1)
        path = path.simplified()
    elif kind == "heart":
        path.moveTo(cx, cy + r * 0.85)
        path.cubicTo(cx - r * 1.25, cy + r * 0.05, cx - r * 0.75, cy - r * 1.05, cx, cy - r * 0.35)
        path.cubicTo(cx + r * 0.75, cy - r * 1.05, cx + r * 1.25, cy + r * 0.05, cx, cy + r * 0.85)
        path.closeSubpath()
    else:
        path.addEllipse(QPointF(cx, cy), r, r)
    return path
