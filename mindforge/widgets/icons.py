"""Векторные иконки в стиле «line icons», отрисовываемые через QtSvg."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# «C» внутри fill/stroke заменяется на цвет иконки.
_ICONS: dict[str, str] = {
    "home": '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V20h5v-6h4v6h5V9.5"/>',
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1.8"/><rect x="14" y="3" width="7" height="7" rx="1.8"/>'
            '<rect x="3" y="14" width="7" height="7" rx="1.8"/><rect x="14" y="14" width="7" height="7" rx="1.8"/>',
    "chart": '<path d="M3 21h18"/><rect x="5" y="11" width="3" height="7" rx="1"/>'
             '<rect x="10.5" y="5" width="3" height="13" rx="1"/><rect x="16" y="8" width="3" height="10" rx="1"/>',
    "cards": '<rect x="3" y="6.5" width="13.5" height="14.5" rx="2"/><path d="M7.5 3H18a3 3 0 0 1 3 3v10.5"/>',
    "trophy": '<path d="M8 21h8"/><path d="M12 16.5V21"/><path d="M7 3.5h10V9a5 5 0 0 1-10 0z"/>'
              '<path d="M17 5h3v1.5a3.5 3.5 0 0 1-3.2 3.5"/><path d="M7 5H4v1.5A3.5 3.5 0 0 0 7.2 10"/>',
    "settings": '<path d="M4 6h9"/><path d="M19 6h1"/><circle cx="16" cy="6" r="2.5"/><path d="M4 12h2"/>'
                '<path d="M12 12h8"/><circle cx="9" cy="12" r="2.5"/><path d="M4 18h10"/><path d="M20 18h0"/>'
                '<circle cx="17" cy="18" r="2.5"/>',
    "play": '<path d="M7.5 4.5v15l12-7.5z" fill="C"/>',
    "flame": '<path d="M12 22c4.2 0 7-2.9 7-7 0-3.6-2.4-6.4-4.2-8.2-.3 2.4-1.6 4-3.2 4.6C12.2 8 11.2 4.9 8.6 2 8.8 6.2 5 9.2 5 14.6 5 19 7.9 22 12 22z"/>',
    "bolt": '<path d="M13.5 2 4.5 13.5h7L10.5 22l9-11.5h-7z"/>',
    "brain": '<path d="M9.5 4.2A2.7 2.7 0 0 0 5 5.5a2.8 2.8 0 0 0-1.6 4.3 3 3 0 0 0 .3 4.9A3.2 3.2 0 0 0 7 19.4a2.8 2.8 0 0 0 5 .9V6.3a2.4 2.4 0 0 0-2.5-2.1z"/>'
             '<path d="M14.5 4.2A2.7 2.7 0 0 1 19 5.5a2.8 2.8 0 0 1 1.6 4.3 3 3 0 0 1-.3 4.9 3.2 3.2 0 0 1-3.3 4.7 2.8 2.8 0 0 1-5 .9V6.3a2.4 2.4 0 0 1 2.5-2.1z"/>'
             '<path d="M8 10.5c1 .2 1.8 1 2 2M16 10.5c-1 .2-1.8 1-2 2M7.5 15.5c1-.8 2.2-.9 3-.5M16.5 15.5c-1-.8-2.2-.9-3-.5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.2 2"/>',
    "close": '<path d="M6 6l12 12M18 6 6 18"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "arrow_left": '<path d="M19 12H5M11 6l-6 6 6 6"/>',
    "arrow_right": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "star": '<path d="M12 3l2.8 5.7 6.2.9-4.5 4.4 1.1 6.2L12 17.3l-5.6 2.9 1.1-6.2L3 9.6l6.2-.9z"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7.5a4 4 0 0 1 8 0V11"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "trash": '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/><path d="M10 11v5.5M14 11v5.5"/>',
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
    "upload": '<path d="M12 15V3.5"/><path d="M7 8.5l5-5 5 5"/><path d="M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4"/>',
    "refresh": '<path d="M20 11a8 8 0 0 0-14.6-4.4L4 8"/><path d="M4 3v5h5"/><path d="M4 13a8 8 0 0 0 14.6 4.4L20 16"/><path d="M20 21v-5h-5"/>',
    "volume": '<path d="M4 9v6h4l5 4V5L8 9z"/><path d="M16.5 8.5a5 5 0 0 1 0 7"/><path d="M19 6a8.5 8.5 0 0 1 0 12"/>',
    "eye": '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.3" fill="C" stroke="none"/>',
    "flag": '<path d="M5 21V4"/><path d="M5 4h12l-2.5 4.5L17 13H5"/>',
    "compass": '<circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/>',
    "hash": '<path d="M5 9h15M4 15h15M10 3.5 8 20.5M16 3.5l-2 17"/>',
    "book": '<path d="M4 19V5a2 2 0 0 1 2-2h14v18H6a2 2 0 0 1-2-2z"/><path d="M4 19a2 2 0 0 1 2-2h14"/><path d="M9 7.5h6"/>',
    "cube": '<path d="M12 2.5l8.5 4.75v9.5L12 21.5l-8.5-4.75v-9.5z"/><path d="M3.5 7.25 12 12l8.5-4.75"/><path d="M12 12v9.5"/>',
    "calc": '<rect x="5" y="2.5" width="14" height="19" rx="2.2"/><rect x="8" y="5.5" width="8" height="4" rx="1"/>'
            '<circle cx="8.7" cy="13.2" r="1" fill="C" stroke="none"/><circle cx="12" cy="13.2" r="1" fill="C" stroke="none"/>'
            '<circle cx="15.3" cy="13.2" r="1" fill="C" stroke="none"/><circle cx="8.7" cy="17.3" r="1" fill="C" stroke="none"/>'
            '<circle cx="12" cy="17.3" r="1" fill="C" stroke="none"/><circle cx="15.3" cy="17.3" r="1" fill="C" stroke="none"/>',
    "trend": '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    "puzzle": '<path d="M4 7H8A2 2 0 1 1 12 7H16V11A2 2 0 1 1 16 15V19H12A2 2 0 1 0 8 19H4V15A2 2 0 1 0 4 11Z"/>',
    "shield": '<path d="M12 2.5l8 3v6c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10v-6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
    "moon": '<path d="M20 14.5A8.2 8.2 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "sparkles": '<path d="M11 3l1.9 5.1L18 10l-5.1 1.9L11 17l-1.9-5.1L4 10l5.1-1.9z"/><path d="M18.5 14.5l.9 2.1 2.1.9-2.1.9-.9 2.1-.9-2.1-2.1-.9 2.1-.9z"/>',
    "heart": '<path d="M12 20s-7.5-4.5-9-9.5C2 7 4.5 4 7.5 4c2 0 3.5 1 4.5 2.5C13 5 14.5 4 16.5 4 19.5 4 22 7 21 10.5 19.5 15.5 12 20 12 20z"/>',
    "heart_fill": '<path fill="C" d="M12 20s-7.5-4.5-9-9.5C2 7 4.5 4 7.5 4c2 0 3.5 1 4.5 2.5C13 5 14.5 4 16.5 4 19.5 4 22 7 21 10.5 19.5 15.5 12 20 12 20z"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><circle cx="12" cy="7.6" r="1.1" fill="C" stroke="none"/>',
    "calendar": '<rect x="3" y="4.5" width="18" height="16.5" rx="2.2"/><path d="M3 9.5h18M8 2.5v4M16 2.5v4"/>',
    "rotate": '<path d="M20 12a8 8 0 1 1-2.4-5.7"/><path d="M20 3.5V8.5h-5"/>',
    "table": '<rect x="3" y="3" width="18" height="18" rx="2.2"/><path d="M9 3v18M15 3v18M3 9h18M3 15h18"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M20.5 20.5 16 16"/>',
    "palette": '<path d="M12 3a9 9 0 1 0 0 18c1.2 0 2-.8 2-1.8 0-.5-.2-.9-.5-1.2-.3-.3-.5-.7-.5-1.2 0-1 .8-1.8 1.8-1.8H17a4 4 0 0 0 4-4c0-4.4-4-8-9-8z"/>'
               '<circle cx="7.5" cy="11.5" r="1.3" fill="C" stroke="none"/><circle cx="10" cy="7.3" r="1.3" fill="C" stroke="none"/>'
               '<circle cx="15" cy="7.5" r="1.3" fill="C" stroke="none"/>',
    "shuffle": '<path d="M16 3.5h4.5V8"/><path d="M4 20 20.5 3.5"/><path d="M20.5 16v4.5H16"/><path d="M14.5 14.5l6 6"/><path d="M4 4l5 5"/>',
    "keyboard": '<rect x="2" y="6" width="20" height="12" rx="2.2"/><path d="M6 10h1M10 10h1M14 10h1M17.5 10h1M7 14h10"/>',
    "cards_stack": '<rect x="4" y="8" width="16" height="12" rx="2"/><path d="M6 5h12M8 2.5h8"/>',
    "pause": '<path d="M8 5v14M16 5v14"/>',
    "list": '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1" fill="C" stroke="none"/>'
            '<circle cx="4.5" cy="12" r="1" fill="C" stroke="none"/><circle cx="4.5" cy="18" r="1" fill="C" stroke="none"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    "award": '<circle cx="12" cy="9" r="6"/><path d="M8.5 14 7 22l5-3 5 3-1.5-8"/>',
}


def icon_svg(name: str, color: str, stroke: float = 2.0) -> str:
    body = _ICONS.get(name, _ICONS["info"]).replace('"C"', f'"{color}"')
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">'
        f"{body}</svg>"
    )


@lru_cache(maxsize=512)
def _renderer(name: str, color: str, stroke: float) -> QSvgRenderer:
    return QSvgRenderer(QByteArray(icon_svg(name, color, stroke).encode("utf-8")))


def paint_icon(p: QPainter, name: str, rect: QRectF, color: QColor | str, stroke: float = 2.0) -> None:
    col = color.name(QColor.NameFormat.HexArgb) if isinstance(color, QColor) else color
    if isinstance(color, QColor) and color.alpha() == 255:
        col = color.name()
    _renderer(name, col, stroke).render(p, rect)


def pixmap(name: str, color: QColor | str, size: int = 20, dpr: float = 2.0, stroke: float = 2.0) -> QPixmap:
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    paint_icon(p, name, QRectF(0, 0, size, size), color, stroke)
    p.end()
    return pm


def icon(name: str, color: QColor | str, size: int = 20) -> QIcon:
    return QIcon(pixmap(name, color, size))


def names() -> list[str]:
    return list(_ICONS)


__all__ = ["icon", "pixmap", "paint_icon", "names", "QSize"]
