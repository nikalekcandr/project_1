import time
from datetime import date

import pytest

from mindforge import srs
from mindforge.core import GameResult, clamp, linear_rating, plural
from mindforge.progress import Progress, game_rating_from, level_from_xp, session_xp, streaks, xp_to_next


def test_plural():
    assert plural(1, "день", "дня", "дней") == "день"
    assert plural(3, "день", "дня", "дней") == "дня"
    assert plural(5, "день", "дня", "дней") == "дней"
    assert plural(11, "день", "дня", "дней") == "дней"
    assert plural(21, "день", "дня", "дней") == "день"
    assert plural(112, "день", "дня", "дней") == "дней"


def test_linear_rating_directions():
    assert linear_rating(5, 0, 10) == 50
    assert linear_rating(20, 0, 10) == 100
    assert linear_rating(2.8, 2.8, 0.7) == 0  # «меньше — лучше»
    assert linear_rating(0.7, 2.8, 0.7) == 100
    assert clamp(-5) == 0 and clamp(150) == 100


def test_game_result_clamps():
    r = GameResult("x", score=1, rating=140, level=1, next_level=1, accuracy=1.4)
    assert r.rating == 100 and r.accuracy == 1.0


def test_levels():
    assert level_from_xp(0) == (1, 0, 100)
    assert level_from_xp(99)[0] == 1
    assert level_from_xp(100) == (2, 0, xp_to_next(2))
    total = sum(xp_to_next(level) for level in range(1, 10))
    assert level_from_xp(total)[0] == 10
    assert session_xp(100, True, True) > session_xp(0, False, False) >= 15


def test_streaks():
    today = date(2026, 9, 24)
    assert streaks(set(), today) == (0, 0)
    days = {"2026-09-24", "2026-09-23", "2026-09-22", "2026-09-10", "2026-09-11"}
    assert streaks(days, today) == (3, 3)
    # сегодня ещё не занимались — серия со вчерашнего дня не сгорела
    assert streaks({"2026-09-23", "2026-09-22"}, today) == (2, 2)
    assert streaks({"2026-09-20"}, today) == (0, 1)


def test_game_rating_top3_of_last10():
    assert game_rating_from([]) is None
    assert game_rating_from([10, 90, 50, 70]) == pytest.approx((90 + 70 + 50) / 3)
    # учитываются только последние 10 попыток (список — от новых к старым)
    assert game_rating_from([10] * 10 + [100] * 5) == 10


# ------------------------------------------------------------------- SRS
def test_srs_new_card_flow():
    now = 1_000_000.0
    card = {"ease": 2.5, "interval": 0, "reps": 0, "lapses": 0}
    again = srs.schedule(card, 1, now)
    assert again["due"] == now + 60 and again["reps"] == 0
    good = srs.schedule(card, 3, now)
    assert good["interval"] == 1 and good["reps"] == 1
    easy = srs.schedule(card, 4, now)
    assert easy["interval"] == 4 and easy["ease"] > 2.5
    second = srs.schedule(good, 3, now)
    assert second["interval"] >= 2 and second["reps"] == 2
    third = srs.schedule(second, 3, now)
    assert third["interval"] > second["interval"]


def test_srs_lapse_and_ease_floor():
    card = {"ease": 1.35, "interval": 20, "reps": 5, "lapses": 0}
    c = srs.schedule(card, 1, 0)
    assert c["lapses"] == 1 and c["reps"] == 0 and c["ease"] == srs.MIN_EASE
    with pytest.raises(ValueError):
        srs.schedule(card, 5, 0)


def test_srs_intervals_grow_monotonic_with_grade():
    card = {"ease": 2.5, "interval": 10, "reps": 3, "lapses": 0}
    ivs = [srs.schedule(card, g, 0)["due"] for g in (1, 2, 3, 4)]
    assert ivs == sorted(ivs)


def test_srs_labels_and_import():
    assert srs.format_interval(30) == "<1 мин"
    assert srs.format_interval(600) == "10 мин"
    assert srs.format_interval(3 * 86400) == "3 дн"
    pairs = srs.parse_import("apple; яблоко\n# комментарий\nСтолица Франции — Париж\nx=1\nбез разделителя\n\tпусто")
    assert pairs == [("apple", "яблоко"), ("Столица Франции", "Париж"), ("x", "1")]


# --------------------------------------------------------------- storage
def test_storage_roundtrip(storage):
    storage.set("a", {"x": [1, 2]})
    assert storage.get("a") == {"x": [1, 2]}
    assert storage.get("missing", 5) == 5
    rid = storage.add_result(GameResult("schulte", 10, 55.5, 1, 1, 0.9, 30, {"headline": "30 с"}))
    assert rid > 0
    rows = storage.results("schulte")
    assert rows[0]["metrics"]["headline"] == "30 с"
    assert storage.best_result("schulte", "rating")["rating"] == 55.5
    storage.set_game_level("nback", 3)
    assert storage.game_level("nback") == 3
    storage.clear_progress()
    assert storage.result_count() == 0 and storage.game_level("nback") == 1


def test_cards_due_logic(storage):
    deck = storage.create_deck("Тест")
    assert storage.add_cards(deck, [("a", "1"), ("b", "2"), ("", "x")]) == 2
    due = storage.due_cards(deck)
    assert [c["front"] for c in due] == ["a", "b"]
    card = srs.schedule(due[0], 3, storage.now())
    storage.update_card_schedule(card, 3)
    assert [c["front"] for c in storage.due_cards(deck)] == ["b"]
    d = storage.decks()[0]
    assert d["total"] == 2 and d["new"] == 1 and d["due"] == 0
    assert storage.review_count() == 1


# -------------------------------------------------------------- progress
class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def test_record_xp_best_and_levels(tmp_path):
    from mindforge.storage import Storage

    clock = Clock(time.mktime((2026, 9, 24, 12, 0, 0, 0, 0, -1)))
    st = Storage(tmp_path / "p.db", clock=clock)
    pr = Progress(st)
    r1 = GameResult("digit_span", 70, 50, 5, 6, 1.0, 60, {"span": 7, "mode": "forward"}, ts=clock())
    out1 = pr.record(r1)
    assert out1.xp > 0 and not out1.new_best
    assert st.game_level("digit_span") == 6
    assert "first" in {a.id for a in out1.achievements}
    r2 = GameResult("digit_span", 90, 70, 6, 99, 1.0, 60, {"span": 9, "mode": "forward"}, ts=clock())
    out2 = pr.record(r2)
    assert out2.new_best
    assert st.game_level("digit_span") == 20  # ограничено max_level
    assert "span8" in pr.unlocked()


def test_daily_plan_is_stable_and_diverse(tmp_path):
    from mindforge.catalog import GAME_BY_ID
    from mindforge.storage import Storage

    clock = Clock(time.mktime((2026, 9, 24, 9, 0, 0, 0, 0, -1)))
    st = Storage(tmp_path / "plan.db", clock=clock)
    pr = Progress(st)
    plan = pr.daily_plan()
    assert len(plan) == 5 and len(set(plan)) == 5
    assert len({GAME_BY_ID[g].domain for g in plan}) == 5
    assert pr.daily_plan() == plan
    new = pr.regenerate_plan()
    assert len(new) == 5 and new != plan


def test_plan_completion_bonus(tmp_path):
    from mindforge.progress import XP_DAILY_PLAN
    from mindforge.storage import Storage

    clock = Clock(time.mktime((2026, 9, 24, 9, 0, 0, 0, 0, -1)))
    st = Storage(tmp_path / "bonus.db", clock=clock)
    st.set("settings.daily_count", 3)
    pr = Progress(st)
    plan = pr.daily_plan()
    outs = [pr.record(GameResult(g, 1, 40, 1, 1, 0.8, 30, {}, ts=clock())) for g in plan]
    assert [o.plan_completed for o in outs] == [False, False, True]
    assert outs[-1].xp >= XP_DAILY_PLAN
    assert pr.plans_completed() == 1
    assert "daily1" in pr.unlocked()


def test_profile_and_index(tmp_path):
    from mindforge.storage import Storage

    st = Storage(tmp_path / "prof.db")
    pr = Progress(st)
    assert pr.index() is None
    pr.record(GameResult("schulte", 1, 60, 1, 1, 1, 30, {}))
    pr.record(GameResult("raven", 1, 80, 1, 1, 1, 30, {}))
    prof = pr.profile()
    assert prof["attention"] == 60 and prof["logic"] == 80 and prof["memory"] is None
    assert pr.index() == 700
    assert pr.index_history()[-1][1] == 700
