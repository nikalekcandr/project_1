"""Генерирует скриншоты интерфейса с демонстрационными данными.

    python tools/screenshots.py [папка] [--theme light]

Используется для README и визуальной проверки дизайна.
"""
from __future__ import annotations

import os
import random
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MINDFORGE_NO_SOUND", "1")
os.environ.setdefault("MINDFORGE_NO_SPEECH", "1")


def pump(app, ms: int) -> None:
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def seed(storage, days: int = 40) -> None:
    from mindforge.catalog import GAMES
    from mindforge.core import GameResult
    from mindforge.data.decks import STARTER_DECKS
    from mindforge.srs import parse_import

    rng = random.Random(7)
    now = time.time()
    headlines = {
        "nback": lambda r: f"{2 + int(r > 50)}-назад · {60 + int(r / 3)}%",
        "digit_span": lambda r: f"{5 + int(r / 25)} цифр",
        "words": lambda r: f"{6 + int(r / 10)} из 14",
        "matrix": lambda r: f"Уровень {3 + int(r / 12)}",
        "corsi": lambda r: f"{4 + int(r / 30)} блоков",
        "rotation": lambda r: f"{10 + int(r / 5)} верных · 92%",
        "schulte": lambda r: f"{40 - r / 4:.1f} с · 5×5",
        "search": lambda r: f"{10 + int(r / 5)} находок",
        "stroop": lambda r: f"{25 + int(r / 3)} верных ответов",
        "switch": lambda r: f"{20 + int(r / 3)} верных ответов",
        "math": lambda r: f"{15 + int(r / 4)} примеров",
        "speed_match": lambda r: f"{400 + int(r * 8)} очков",
        "series": lambda r: f"{5 + int(r / 20)} из 10",
        "raven": lambda r: f"{3 + int(r / 25)} из 8",
    }
    base = {g.id: rng.uniform(30, 55) for g in GAMES}
    for d in range(days, 0, -1):
        if rng.random() < 0.18 and d > 2:
            continue
        for g in rng.sample(GAMES, rng.randint(3, 6)):
            prog = (days - d) / days
            rating = max(5, min(97, base[g.id] + prog * 22 + rng.gauss(0, 6)))
            ts = now - d * 86400 + rng.randint(0, 3600 * 4)
            storage.add_result(GameResult(
                game=g.id, score=round(rating * 10), rating=rating, level=1 + int(rating / 20),
                next_level=1 + int(rating / 20), accuracy=0.7 + rating / 400, duration=rng.uniform(50, 180),
                metrics={"headline": headlines[g.id](rating), "rows": []}, ts=ts,
            ))
    for g in GAMES:
        storage.set_game_level(g.id, rng.randint(2, 6) if g.leveled else 1)
    storage.set("xp", 5400)
    for name in list(STARTER_DECKS)[:2]:
        deck = storage.create_deck(name)
        storage.add_cards(deck, parse_import(STARTER_DECKS[name]))


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "docs/screenshots")
    theme = "light" if "--theme" in sys.argv and sys.argv[sys.argv.index("--theme") + 1] == "light" else "dark"
    out.mkdir(parents=True, exist_ok=True)
    os.environ["MINDFORGE_DATA_DIR"] = tempfile.mkdtemp()

    from mindforge.app import MainWindow, create_app
    from mindforge.context import AppContext
    from mindforge.progress import ACHIEVEMENTS
    from mindforge.storage import Storage
    from mindforge.theme import apply_theme

    app = create_app([sys.argv[0]])
    storage = Storage()
    seed(storage)
    ctx = AppContext(storage)
    ctx.set_setting("onboarded", True)
    ctx.set_setting("name", "Александр")
    for a in ACHIEVEMENTS[:9]:
        storage.set(f"ach.{a.id}", time.time() - 86400 * 3)
    apply_theme(app, theme)
    win = MainWindow(ctx)
    win.resize(1360, 880)
    win.show()
    pump(app, 400)
    sfx = "" if theme == "dark" else "-light"
    for key in ("home", "library", "stats", "achievements", "cards", "settings"):
        win.go(key)
        pump(app, 250)
        win.grab().save(str(out / f"{key}{sfx}.png"))

    shots = {
        "nback": 3600, "schulte": 600, "stroop": 400, "raven": 400, "rotation": 400, "series": 400,
        "corsi": 1700, "matrix": 900, "math": 400, "switch": 400, "speed_match": 400, "search": 400,
        "digit_span": 1500, "words": 400,
    }
    only = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--games=")]
    games = only[0].split(",") if only else list(shots)
    for gid in games:
        win.open_game(gid)
        pump(app, 200)
        if gid == games[0]:
            win.grab().save(str(out / f"intro-{gid}{sfx}.png"))
        win.host.start_game()
        pump(app, 2900 + shots[gid])
        game = win.host.game
        if gid == "nback" and game is not None:
            game.respond("pos")
            pump(app, 50)
        win.grab().save(str(out / f"game-{gid}{sfx}.png"))
        if gid == games[0] and game is not None:
            if gid == "nback":  # правдоподобный результат: почти все совпадения найдены
                game.resp_pos = [t["pos_match"] for t in game.trials]
                game.resp_snd = [t["snd_match"] for t in game.trials]
                miss = next(i for i, t in enumerate(game.trials) if t["snd_match"])
                game.resp_snd[miss] = False
            game.force_finish()
            pump(app, 5200)  # ждём, пока исчезнут всплывающие уведомления
            win.grab().save(str(out / f"result-{gid}{sfx}.png"))
        win.host.close_host()
        pump(app, 100)
    print("saved to", out)


if __name__ == "__main__":
    main()
