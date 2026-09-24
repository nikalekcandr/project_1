"""Самопроверка собранного приложения: `MindForge.exe --selftest=report.json`.

Создаёт все экраны, запускает каждое упражнение в ускоренном режиме и
записывает отчёт. Используется в CI, чтобы убедиться, что .exe работает.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import traceback


def _pump(app, ms: int) -> None:
    from PySide6.QtCore import QEventLoop

    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        time.sleep(0.005)


def run_selftest(report_path: str | None = None) -> int:
    report: dict = {"ok": False, "steps": [], "errors": []}
    tmp = tempfile.mkdtemp(prefix="mindforge-selftest-")
    os.environ["MINDFORGE_DATA_DIR"] = tmp
    os.environ["MINDFORGE_SELFTEST"] = "1"

    def step(name: str, fn):
        try:
            out = fn()
            info = out if isinstance(out, (dict, list, str, int, float, bool, type(None))) else type(out).__name__
            report["steps"].append({"name": name, "ok": True, "info": info})
            return out
        except Exception:
            report["errors"].append({"name": name, "trace": traceback.format_exc()})
            report["steps"].append({"name": name, "ok": False})
            return None

    try:
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        from . import __version__
        from .app import MainWindow, create_app
        from .catalog import GAMES
        from .context import AppContext
        from .storage import Storage
        from .theme import apply_theme

        report["version"] = __version__
        report["platform"] = sys.platform
        report["frozen"] = bool(getattr(sys, "frozen", False))
        app = create_app([sys.argv[0]])
        report["translations_ru"] = bool(getattr(app, "_mf_translator", None))
        storage = Storage()
        ctx = AppContext(storage)
        ctx.set_setting("onboarded", True)
        ctx.sound.set_volume(0.0)
        apply_theme(app, "dark")

        def sound_check():
            from .sound import SoundEngine

            eng = SoundEngine(enabled=True, volume=0.5)
            eng._prepare()
            return {"backend": eng._backend, "files": len(eng._files) or len(eng._effects)}

        step("sound", sound_check)

        def speech_check():
            info = {"available": ctx.speech.available, "voice": ctx.speech.voice_name}
            try:
                from PySide6.QtTextToSpeech import QTextToSpeech

                info["engines"] = list(QTextToSpeech.availableEngines())
            except Exception as exc:  # noqa: BLE001
                info["engines_error"] = repr(exc)
            return info

        step("speech", speech_check)

        win = step("main_window", lambda: MainWindow(ctx))
        if win is None:
            raise RuntimeError("MainWindow failed")
        win.resize(1320, 860)
        win.show()
        _pump(app, 300)

        for key in ("home", "library", "cards", "stats", "achievements", "settings"):
            def show_page(key=key):
                win.go(key)
                _pump(app, 80)
                img = win.grab()
                return {"w": img.width(), "h": img.height()}

            step(f"page:{key}", show_page)

        host = win.host
        host.fast = True
        for meta in GAMES:
            def play(meta=meta):
                win.open_game(meta.id)
                _pump(app, 60)
                host.start_game()
                _pump(app, 400)
                game = host.game
                assert game is not None, "game not created"
                for k in (Qt.Key.Key_1, Qt.Key.Key_Right, Qt.Key.Key_A, Qt.Key.Key_5, Qt.Key.Key_Return):
                    QTest.keyClick(game, k)
                    _pump(app, 20)
                win.grab()
                if not game._done:
                    game.force_finish()
                _pump(app, 150)
                assert host.last_result is not None and host.last_result.game == meta.id, "no result"
                res = host.last_result
                host.close_host()
                _pump(app, 30)
                return {"rating": res.rating, "headline": res.metrics.get("headline")}

            step(f"game:{meta.id}", play)

        def cards():
            from .data.decks import STARTER_DECKS
            from .srs import parse_import

            page = win.pages["cards"]
            for name, text in STARTER_DECKS.items():
                deck = storage.create_deck(name)
                storage.add_cards(deck, parse_import(text))
            page.refresh()
            d = storage.decks()[0]
            page.study(d)
            _pump(app, 50)
            page.review.reveal()
            page.review.grade(3)
            page.review.finish()
            _pump(app, 50)
            return {"decks": len(storage.decks()), "reviews": storage.review_count()}

        step("flashcards", cards)

        def light_theme():
            ctx.set_setting("theme", "light")
            apply_theme(app, "light")
            ctx.theme_changed.emit()
            _pump(app, 100)
            win.go("home")
            _pump(app, 50)
            win.grab()
            return True

        step("theme:light", light_theme)
        report["results"] = storage.result_count()
        win.close()
        _pump(app, 50)
        report["ok"] = not report["errors"]
    except Exception:
        report["errors"].append({"name": "fatal", "trace": traceback.format_exc()})

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if report_path:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        try:
            print(text)
        except Exception:
            pass
    return 0 if report["ok"] else 1
