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

            engines = [e for e in QTextToSpeech.availableEngines() if e != "mock"]
            order = ["winrt", "sapi", "darwin", "speechd", "flite", "android"]
            engines.sort(key=lambda e: order.index(e) if e in order else len(order))
            fallback = None
            for engine in engines:
                tts = self._create(QTextToSpeech, engine)
                if tts is None:
                    continue
                voices = list(tts.availableVoices())
                ru = [v for v in voices if v.locale().language() == QLocale.Language.Russian]
                if ru:
                    tts.setLocale(ru[0].locale())
                    tts.setVoice(ru[0])
                    self._lang = "ru"
                    self._finish(tts)
                    return
                en = [v for v in voices if v.locale().language() == QLocale.Language.English]
                if en and fallback is None:
                    fallback = (tts, en[0])
            if fallback is not None:
                tts, voice = fallback
                tts.setLocale(voice.locale())
                tts.setVoice(voice)
                self._lang = "en"
                self._finish(tts)
        except Exception:
            self._tts = None

    @staticmethod
    def _create(cls, engine: str):
        """Создаёт движок и ждёт (до ~1.5 с) его готовности."""
        from PySide6.QtCore import QEventLoop, QTimer

        try:
            tts = cls(engine)
        except Exception:
            return None
        if tts.state() == cls.State.Error:
            return None
        if tts.state() != cls.State.Ready:
            loop = QEventLoop()
            tts.stateChanged.connect(lambda *_: loop.quit())
            QTimer.singleShot(1500, loop.quit)
            loop.exec()
        if tts.state() == cls.State.Error or not tts.availableVoices():
            return None
        return tts

    def _finish(self, tts) -> None:
        tts.setRate(0.15)
        tts.setVolume(1.0)
        self.voice_name = f"{tts.voice().name()} ({tts.engine()})"
        self._tts = tts

    @property
    def checked(self) -> bool:
        return self._tried

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
