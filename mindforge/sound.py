"""Звуковые эффекты, синтезируемые на лету (без внешних файлов).

В Windows используется стандартный модуль winsound — он есть в любой сборке
Python и не требует дополнительных библиотек. На других системах пробуем
QtMultimedia, иначе приложение работает без звука.
"""
from __future__ import annotations

import array
import io
import math
import os
import sys
import tempfile
import wave
from pathlib import Path

RATE = 22050

# Восемь хорошо различимых нот (пентатоника в двух октавах) для «звукового» N-назад.
TONE_FREQS = [261.63, 293.66, 329.63, 392.00, 440.00, 523.25, 587.33, 659.25]


def _envelope(i: int, n: int, attack: float = 0.01, release: float = 0.08) -> float:
    t = i / RATE
    total = n / RATE
    if t < attack:
        return t / attack
    if t > total - release:
        return max(0.0, (total - t) / release)
    return 1.0


def _synth(parts: list[tuple[float, float, float]], volume: float, shape: str = "soft") -> array.array:
    """parts: список (частота, длительность, пауза_после)."""
    out = array.array("h")
    amp = 32767 * 0.55 * volume
    for freq, dur, gap in parts:
        n = int(RATE * dur)
        for i in range(n):
            t = i / RATE
            if shape == "soft":
                s = math.sin(2 * math.pi * freq * t) + 0.25 * math.sin(4 * math.pi * freq * t)
                s /= 1.25
                env = _envelope(i, n, 0.006, dur * 0.6) * math.exp(-3.0 * t)
            elif shape == "bell":
                s = (
                    math.sin(2 * math.pi * freq * t)
                    + 0.4 * math.sin(2 * math.pi * freq * 2.01 * t) * math.exp(-6 * t)
                    + 0.15 * math.sin(2 * math.pi * freq * 3.0 * t) * math.exp(-9 * t)
                ) / 1.55
                env = _envelope(i, n, 0.004, 0.05) * math.exp(-4.0 * t)
            elif shape == "buzz":
                s = math.sin(2 * math.pi * freq * t)
                s = 0.7 * s + 0.3 * (1.0 if s > 0 else -1.0)
                env = _envelope(i, n, 0.005, 0.06) * 0.6
            else:  # click
                s = math.sin(2 * math.pi * freq * t)
                env = math.exp(-60 * t)
            out.append(int(max(-32767, min(32767, amp * s * env))))
        out.extend([0] * int(RATE * gap))
    return out


def _wav_bytes(samples: array.array) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        if sys.byteorder == "big":
            samples = array.array("h", samples)
            samples.byteswap()
        w.writeframes(samples.tobytes())
    return buf.getvalue()


def sound_bank(volume: float) -> dict[str, bytes]:
    v = max(0.0, min(1.0, volume))
    bank = {
        "click": _synth([(1400, 0.04, 0)], v * 0.5, "click"),
        "tick": _synth([(880, 0.09, 0)], v * 0.7, "bell"),
        "go": _synth([(1318.5, 0.22, 0)], v * 0.8, "bell"),
        "correct": _synth([(784, 0.07, 0.0), (1175, 0.16, 0)], v * 0.6, "bell"),
        "wrong": _synth([(196, 0.16, 0)], v * 0.55, "buzz"),
        "levelup": _synth([(523, 0.09, 0), (659, 0.09, 0), (784, 0.09, 0), (1047, 0.3, 0)], v * 0.7, "bell"),
        "finish": _synth([(659, 0.1, 0), (784, 0.1, 0), (988, 0.28, 0)], v * 0.7, "bell"),
        "flip": _synth([(620, 0.06, 0)], v * 0.45, "soft"),
    }
    for i, f in enumerate(TONE_FREQS):
        bank[f"tone{i}"] = _synth([(f, 0.42, 0)], v * 0.85, "soft")
    return {k: _wav_bytes(s) for k, s in bank.items()}


class SoundEngine:
    def __init__(self, enabled: bool = True, volume: float = 0.7) -> None:
        self.enabled = enabled
        self.volume = volume
        self._backend = None
        self._files: dict[str, str] = {}
        self._effects: dict = {}
        self._ready_volume: float | None = None
        if os.environ.get("MINDFORGE_NO_SOUND"):
            self._backend = "none"

    # Ленивая инициализация, чтобы не задерживать старт приложения.
    def _prepare(self) -> None:
        if self._ready_volume == self.volume and self._backend is not None:
            return
        bank = sound_bank(self.volume)
        if self._backend == "none":
            self._ready_volume = self.volume
            return
        if sys.platform == "win32":
            try:
                import winsound  # noqa: F401

                base = Path(tempfile.gettempdir()) / "MindForge-sfx" / f"v{int(self.volume * 100)}"
                base.mkdir(parents=True, exist_ok=True)
                files = {}
                for name, data in bank.items():
                    p = base / f"{name}.wav"
                    if not p.exists() or p.stat().st_size != len(data):
                        p.write_bytes(data)
                    files[name] = str(p)
                self._files = files
                self._backend = "winsound"
            except Exception:
                self._backend = "none"
        else:
            try:
                from PySide6.QtCore import QUrl
                from PySide6.QtMultimedia import QSoundEffect

                base = Path(tempfile.gettempdir()) / "MindForge-sfx" / f"v{int(self.volume * 100)}"
                base.mkdir(parents=True, exist_ok=True)
                self._effects = {}
                for name, data in bank.items():
                    p = base / f"{name}.wav"
                    p.write_bytes(data)
                    eff = QSoundEffect()
                    eff.setSource(QUrl.fromLocalFile(str(p)))
                    self._effects[name] = eff
                self._backend = "qt"
            except Exception:
                self._backend = "none"
        self._ready_volume = self.volume

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def set_volume(self, volume: float) -> None:
        self.volume = round(max(0.0, min(1.0, volume)), 2)

    def play(self, name: str) -> None:
        if not self.enabled or self.volume <= 0:
            return
        try:
            self._prepare()
            if self._backend == "winsound":
                import winsound

                path = self._files.get(name)
                if path:
                    winsound.PlaySound(
                        path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
                    )
            elif self._backend == "qt":
                eff = self._effects.get(name)
                if eff is not None:
                    eff.play()
        except Exception:
            # Звук — не критичная функция: любые сбои просто отключают его.
            self._backend = "none"
