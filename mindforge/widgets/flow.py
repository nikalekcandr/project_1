"""FlowLayout — раскладка «по строкам с переносом» (порт примера из документации Qt)."""
from __future__ import annotations

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QSizePolicy


class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing: int = 8, center: bool = False) -> None:
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self._center = center
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m: QMargins = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y = eff.x(), eff.y()
        line_h = 0
        lines: list[list[tuple]] = [[]]
        for item in self._items:
            w = item.widget()
            if w is not None and not w.isVisible() and not test_only:
                pass
            hint = item.sizeHint()
            next_x = x + hint.width() + self._spacing
            if next_x - self._spacing > eff.right() + 1 and line_h > 0:
                x = eff.x()
                y = y + line_h + self._spacing
                next_x = x + hint.width() + self._spacing
                line_h = 0
                lines.append([])
            lines[-1].append((item, QPoint(x, y), hint))
            x = next_x
            line_h = max(line_h, hint.height())
        if not test_only:
            for line in lines:
                if not line:
                    continue
                shift = 0
                if self._center:
                    last_item, last_pt, last_hint = line[-1]
                    used = last_pt.x() + last_hint.width() - eff.x()
                    shift = max(0, (eff.width() - used) // 2)
                for item, pt, hint in line:
                    item.setGeometry(QRect(pt + QPoint(shift, 0), hint))
        return y + line_h - rect.y() + m.bottom()


__all__ = ["FlowLayout", "QSizePolicy"]
