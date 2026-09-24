"""Синтез речи (буквы для «Двойного N-назад») через QtTextToSpeech.

Если движок недоступен, приложение переключает упражнение на тоны.
"""
from __future__ import annotations

import os

# Буквы с хорошо различимым звучанием. Для русского голоса произносим
# названия букв, для английского — классический набор из исследований Jaeggi.
RU_LETTERS = [("К", "ка"), ("Л", "эль"), ("М", "эм"), ("Р", "эр"), ("С", "эс"), ("Т", "тэ"), ("Х", "ха"), ("Ш", "ша")]
EN_LETTERS = [(ch, ch) for ch in "CHKLQRST"]


class Speech:
    def __init__(self) -> None:
        self._tts = None
        self._tried = False
        self._lang = "ru"
        self.voice_name: str | None = None

    def _init(self) -> None:
        if self._tried:
            return
        self._tried = True
        if os.environ.get("MINDFORGE_NO_SPEECH"):
            return
        try:
            from PySide6.QtCore import QLocale
            from PySide6.QtTextToSpeech import QTextToSpeech

            if not QTextToSpeech.availableEngines():
                return
            tts = QTextToSpeech()
            if tts.state() == QTextToSpeech.State.Error:
                return
            voices_ru = [v for v in tts.availableVoices() if v.locale().language() == QLocale.Language.Russian]
            if not voices_ru:
                for loc in tts.availableLocales():
                    if loc.language() == QLocale.Language.Russian:
                        tts.setLocale(loc)
                        voices_ru = list(tts.availableVoices())
                        break
            if voices_ru:
                tts.setVoice(voices_ru[0])
                self._lang = "ru"
            else:
                for loc in tts.availableLocales():
                    if loc.language() == QLocale.Language.English:
                        tts.setLocale(loc)
                        break
                self._lang = "en"
            if not tts.availableVoices():
                return
            tts.setRate(0.15)
            tts.setVolume(1.0)
            self.voice_name = tts.voice().name()
            self._tts = tts
        except Exception:
            self._tts = None

    @property
    def available(self) -> bool:
        self._init()
        return self._tts is not None

    def letters(self) -> list[tuple[str, str]]:
        self._init()
        return RU_LETTERS if self._lang == "ru" else EN_LETTERS

    def say(self, text: str) -> None:
        self._init()
        if self._tts is None:
            return
        try:
            self._tts.stop()
            self._tts.say(text)
        except Exception:
            self._tts = None

    def stop(self) -> None:
        if self._tts is not None:
            try:
                self._tts.stop()
            except Exception:
                pass
