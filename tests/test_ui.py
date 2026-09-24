"""UI-тесты: самопроверка всех экранов и «прохождение» каждого упражнения ботом."""
import random
import time

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mindforge.catalog import GAMES


@pytest.fixture(scope="module")
def app():
    from mindforge.app import create_app

    return create_app(["test"])


def pump(app, ms):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.002)


KEYS = [Qt.Key.Key_1, Qt.Key.Key_2, Qt.Key.Key_3, Qt.Key.Key_4, Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_A,
        Qt.Key.Key_L, Qt.Key.Key_5, Qt.Key.Key_7, Qt.Key.Key_Return, Qt.Key.Key_Space]


VARIANTS = [(g.id, {}, 2) for g in GAMES] + [
    ("nback", {"stimulus": "color"}, 1),
    ("nback", {"stimulus": "none"}, 3),
    ("nback", {"stimulus": "tones"}, 2),
    ("digit_span", {"mode": "backward"}, 2),
    ("corsi", {"mode": "backward"}, 9),
    ("words", {"mode": "recognize"}, 3),
    ("schulte", {"size": "4", "mode": "chaos"}, 1),
    ("schulte", {"size": "7", "mode": "hidden"}, 1),
    ("stroop", {}, 8),
    ("switch", {}, 7),
    ("math", {}, 12),
    ("speed_match", {}, 8),
    ("rotation", {}, 9),
    ("search", {}, 11),
    ("raven", {}, 6),
    ("series", {}, 6),
]


@pytest.mark.parametrize("game_id,options,level", VARIANTS)
def test_game_plays_to_completion(app, game_id, options, level):
    from mindforge.games import GAME_WIDGETS, GameContext
    from mindforge.sound import SoundEngine
    from mindforge.speech import Speech

    ctx = GameContext(level=level, options=options, sound=SoundEngine(enabled=False), speech=Speech(),
                      rng=random.Random(1), fast=True)
    game = GAME_WIDGETS[game_id](ctx)
    game.resize(900, 700)
    game.show()
    results = []
    game.finished.connect(results.append)
    game.begin()
    rng = random.Random(2)
    deadline = time.time() + 40
    while not results and time.time() < deadline:
        if game_id == "schulte":
            board = game.board
            idx = board.numbers.index(game.next_num)
            QTest.mouseClick(board, Qt.MouseButton.LeftButton, pos=board.rects()[idx].center().toPoint())
        elif game_id == "words" and game.phase == "test" and game.mode == "recall":
            game.entry.setText(rng.choice(game.words + ["абракадабра"]))
            game.submit_word()
        else:
            QTest.keyClick(game, rng.choice(KEYS))
            target = getattr(game, "board", game)  # клики должны попадать в виджет поля
            QTest.mouseClick(target, Qt.MouseButton.LeftButton,
                             pos=QPoint(rng.randint(5, target.width() - 5), rng.randint(5, target.height() - 5)))
        pump(app, 15)
    assert results, f"{game_id} не завершилось"
    r = results[0]
    assert r.game == game_id
    assert 0 <= r.rating <= 100
    assert r.next_level >= 1
    assert "headline" in r.metrics and r.metrics.get("rows")
    game.close()


def test_selftest_passes(app, monkeypatch, tmp_path):
    from mindforge.selftest import run_selftest

    report = tmp_path / "report.json"
    code = run_selftest(str(report))
    import json

    data = json.loads(report.read_text(encoding="utf-8"))
    assert code == 0, data["errors"]
    assert data["results"] == len(GAMES)
    assert QApplication.instance() is not None
