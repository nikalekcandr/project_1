"""Рисует иконку приложения (assets/icon.ico и assets/icon.png) из векторного логотипа."""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from mindforge.widgets.logo import logo_pixmap  # noqa: E402

SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def to_pil(size: int) -> Image.Image:
    pm = logo_pixmap(size)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pm.save(buf, "PNG")
    return Image.open(io.BytesIO(bytes(buf.data()))).convert("RGBA")


def main() -> None:
    _app = QGuiApplication(sys.argv)
    out = Path(__file__).resolve().parents[1] / "assets"
    out.mkdir(exist_ok=True)
    images = [to_pil(s) for s in SIZES]
    images[-1].save(out / "icon.png")
    images[-1].save(out / "icon.ico", format="ICO", sizes=[(s, s) for s in SIZES], append_images=images[:-1])
    print("icon written:", out / "icon.ico")


if __name__ == "__main__":
    main()
