import itertools
import random
import re
from collections import Counter

import pytest

from mindforge.games import corsi, digit_span, math_sprint, matrix, nback, raven, rotation, schulte, search, series
from mindforge.games import speed_match, stroop, switch, words

SEEDS = range(40)


# ------------------------------------------------------------------ N-назад
@pytest.mark.parametrize("n", [1, 2, 3, 5])
def test_nback_block_has_exact_targets(n):
    for seed in SEEDS:
        trials = nback.generate_block(n, random.Random(seed), dual=True)
        assert len(trials) == nback.SCORED_TRIALS + n
        pos_matches = [i for i in range(n, len(trials)) if trials[i]["pos"] == trials[i - n]["pos"]]
        snd_matches = [i for i in range(n, len(trials)) if trials[i]["snd"] == trials[i - n]["snd"]]
        assert len(pos_matches) == 6 and len(snd_matches) == 6
        assert len(set(pos_matches) & set(snd_matches)) == 2
        assert all(trials[i]["pos_match"] for i in pos_matches)
        assert sum(t["pos_match"] for t in trials) == 6


def test_nback_scoring_and_levels():
    trials = nback.generate_block(2, random.Random(1), dual=False)
    perfect = [t["pos_match"] for t in trials]
    s = nback.score_channel(trials, perfect, "pos_match", 2)
    assert s["acc"] == 1.0 and s["hits"] == 6 and s["fa"] == 0
    nothing = [False] * len(trials)
    assert nback.score_channel(trials, nothing, "pos_match", 2)["acc"] == 0.0
    assert nback.next_level(3, 0.85) == 4
    assert nback.next_level(3, 0.6) == 3
    assert nback.next_level(3, 0.3) == 2
    assert nback.next_level(1, 0.1) == 1


def test_nback_rating_rewards_accuracy():
    assert nback.rating_for(5, 0.0, True) < nback.rating_for(2, 0.8, True)
    assert nback.rating_for(3, 0.9, True) > nback.rating_for(3, 0.6, True)
    assert nback.rating_for(4, 0.8, True) > nback.rating_for(3, 0.8, True)
    assert nback.rating_for(3, 0.8, False) < nback.rating_for(3, 0.8, True)


# -------------------------------------------------------------- цифры/Корси
def test_digit_sequences():
    rng = random.Random(3)
    for length in range(3, 15):
        seq = digit_span.make_sequence(length, rng)
        assert len(seq) == length and all(0 <= d <= 9 for d in seq)
        assert all(a != b for a, b in zip(seq, seq[1:]))
    assert digit_span.expected_answer([1, 2, 3], "backward") == [3, 2, 1]
    assert digit_span.span_rating(7, "forward") == 50
    assert digit_span.start_length(1, "forward") == 3 and digit_span.start_length(1, "backward") == 2


def test_corsi_layout_and_sequence():
    for seed in SEEDS:
        rng = random.Random(seed)
        for n in (9, 12):
            pts = corsi.make_layout(n, rng)
            assert len(pts) == n
            assert all(0 <= x <= 1 and 0 <= y <= 1 for x, y in pts)
            dmin = min(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 for a, b in itertools.combinations(pts, 2))
            assert dmin > 0.12
        seq = corsi.make_sequence(7, 9, rng)
        assert len(set(seq)) == 7


def test_matrix_levels():
    for level in range(1, 31):
        g = matrix.grid_size(level)
        assert 3 <= g <= 8
        assert matrix.cell_count(level) < g * g
        pat = matrix.make_pattern(level, random.Random(level))
        assert len(pat) == matrix.cell_count(level) and max(pat) < g * g


# -------------------------------------------------------------------- слова
def test_words_pick_and_match():
    rng = random.Random(5)
    ws = words.pick_words(30, rng)
    assert len(ws) == 30 and len(set(ws)) == 30
    for a, b in itertools.combinations(ws, 2):
        assert words.levenshtein(words.normalize(a), words.normalize(b)) >= 2
    targets = ["черепаха", "ёж", "кот"]
    assert words.match_word("Черепаха ", targets, set()) == "черепаха"
    assert words.match_word("черипаха", targets, set()) == "черепаха"  # одна опечатка
    assert words.match_word("еж", targets, set()) == "ёж"  # ё = е
    assert words.match_word("кит", targets, set()) is None  # короткие слова — только точно
    distractors = words.pick_words(10, rng, exclude={words.normalize(w) for w in ws})
    assert not set(distractors) & set(ws)


def test_levenshtein():
    assert words.levenshtein("kitten", "sitting") == 3
    assert words.levenshtein("", "abc") == 3
    assert words.levenshtein("same", "same") == 0


# ------------------------------------------------------------ внимание
def test_schulte_table_and_rating():
    t = schulte.make_table(5, random.Random(1))
    assert sorted(t) == list(range(1, 26))
    fast = schulte.schulte_rating(20, 0, 5, "classic")
    slow = schulte.schulte_rating(50, 0, 5, "classic")
    assert fast > slow
    assert schulte.schulte_rating(30, 3, 5, "classic") < schulte.schulte_rating(30, 0, 5, "classic")
    assert schulte.schulte_rating(30, 0, 5, "chaos") > schulte.schulte_rating(30, 0, 5, "classic")


def test_search_rounds_have_single_odd_item():
    for level in range(1, 13):
        for seed in range(10):
            rd = search.make_round(level, random.Random(seed))
            cols, rows = search.grid_dims(level)
            assert 0 <= rd["odd"] < cols * rows
            assert rd["base"] != rd["odd_glyph"] or rd["rot"] != 0


# --------------------------------------------------------------- гибкость
def test_stroop_trials():
    rng = random.Random(2)
    prev = None
    for level in (1, 5, 9):
        for _ in range(200):
            t = stroop.make_trial(level, rng, prev)
            assert t["answer"] == (t["word"] if t["framed"] else t["ink"])
            assert t["congruent"] == (t["word"] == t["ink"])
            if level < 4:
                assert not t["framed"]
            prev = t


def test_switch_cards():
    rng = random.Random(4)
    for _ in range(300):
        c = switch.make_card(rng.choice(["top", "bottom"]), rng)
        if c["pos"] == "top":
            assert c["answer"] == (c["digit"] % 2 == 0)
        else:
            assert c["answer"] == (c["letter"] in switch.VOWELS)
    # уровень 1: смена правила строго каждые 4 карточки
    pos, seq = None, []
    for i in range(12):
        pos = switch.next_position(1, i, pos, rng)
        seq.append(pos)
    assert seq[1:4] == [seq[1]] * 3 and seq[4] != seq[3]


# ---------------------------------------------------------------- скорость
def _eval_problem(text: str) -> int:
    t = text.replace("×", "*").replace("÷", "//").replace("−", "-")
    m = re.fullmatch(r"(\d+)% от (\d+)", t)
    if m:
        return int(m.group(2)) * int(m.group(1)) // 100
    m = re.fullmatch(r"(\d+)²", t)
    if m:
        return int(m.group(1)) ** 2
    assert re.fullmatch(r"-?\d+ [-+*/]{1,2} -?\d+", t), text
    return int(eval(t))  # noqa: S307 — только цифры и операторы, проверено регуляркой


@pytest.mark.parametrize("level", range(1, 13))
def test_math_problems_are_correct(level):
    rng = random.Random(level)
    for _ in range(300):
        text, ans, weight = math_sprint.make_problem(level, rng)
        assert _eval_problem(text) == ans, text
        assert 1 <= weight <= 4
        if "÷" in text:
            a, b = text.split(" ÷ ")
            assert int(a) % int(b) == 0


def test_speed_match():
    rng = random.Random(9)
    hist: list[dict] = []
    matches = 0
    for _ in range(400):
        hist.append(speed_match.make_sequence_item(hist, 3, rng))
        m = speed_match.is_match(hist, 3)
        matches += bool(m)
    assert 0.25 < matches / 400 < 0.55
    assert speed_match.is_match(hist[:1], 3) is None
    assert speed_match.is_match(hist[:2], 8) is None


# ------------------------------------------------------------ пространство
def test_rotation_shapes_are_chiral():
    for seed in SEEDS:
        rng = random.Random(seed)
        for k in (5, 6, 7, 8):
            shape = rotation.make_polyomino(k, rng)
            assert len(shape) == k
            assert rotation.mirror(shape) not in rotation.rotations(shape)


def test_rotation_trials_consistent():
    for seed in SEEDS:
        t = rotation.make_trial(1 + seed % 10, random.Random(seed))
        is_same = t["right"] in rotation.rotations(t["left"])
        assert is_same != t["mirrored"]


# ----------------------------------------------------------------- логика
@pytest.mark.parametrize("tier", range(1, 7))
def test_series_problems(tier):
    for seed in range(60):
        p = series.make_problem(tier, random.Random(seed * 7 + tier))
        assert len(p["options"]) == 4 and len(set(p["options"])) == 4
        assert p["options"].count(p["answer"]) == 1
        assert len(p["shown"]) >= 5
        assert p["rule"]


def _check_rule(rule: str, attr: str, grid: list[list[int]]) -> None:
    size = raven.DOMAIN_SIZE[attr]
    assert all(0 <= v < size for row in grid for v in row)
    if rule == "global":
        assert len({v for row in grid for v in row}) == 1
    elif rule == "row":
        assert all(len(set(row)) == 1 for row in grid)
    elif rule == "progression":
        steps = {row[1] - row[0] for row in grid} | {row[2] - row[1] for row in grid}
        assert len(steps) == 1 and 0 not in steps
    elif rule == "distribute":
        sets = [tuple(sorted(row)) for row in grid]
        assert len(set(sets)) == 1 and len(set(grid[0])) == 3
        assert len({tuple(row) for row in grid}) == 3
    elif rule == "arithmetic":
        assert all(row[2] + 1 == (row[0] + 1) + (row[1] + 1) for row in grid)


@pytest.mark.parametrize("difficulty", range(1, 7))
def test_raven_matrices_valid_and_balanced(difficulty):
    for seed in range(50):
        m = raven.make_matrix(difficulty, random.Random(seed * 13 + difficulty))
        panels, answer, options = m["panels"], m["answer"], m["options"]
        assert panels[2][2] == answer
        for attr, rule in m["rules"].items():
            _check_rule(rule, attr, [[panels[r][c][attr] for c in range(3)] for r in range(3)])
        assert len(options) == 8
        keys = [tuple(o[a] for a in raven.ATTRS) for o in options]
        assert len(set(keys)) == 8
        assert options.count(answer) == 1
        # сбалансированность: каждый атрибут либо одинаков у всех, либо делится 4/4
        for a in raven.ATTRS:
            counts = sorted(Counter(o[a] for o in options).values())
            assert counts in ([8], [4, 4])
        varying = sum(r in ("progression", "distribute", "arithmetic") for r in m["rules"].values())
        assert varying == {1: 1, 2: 2, 3: 2, 4: 3, 5: 3, 6: 4}[difficulty]
        assert raven.explain(m["rules"])
