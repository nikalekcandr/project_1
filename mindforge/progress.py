"""Прогресс игрока: опыт, уровни, серии, когнитивный профиль, достижения, план дня."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable

from .catalog import GAME_BY_ID, GAMES, games_in_domain
from .core import DOMAINS, GameResult
from .storage import Storage, day_of

LEVEL_TITLES = [
    (1, "Новичок"),
    (3, "Ученик"),
    (5, "Практик"),
    (8, "Знаток"),
    (12, "Эрудит"),
    (16, "Аналитик"),
    (20, "Стратег"),
    (25, "Мастер"),
    (30, "Гроссмейстер"),
    (40, "Гений"),
    (50, "Легенда"),
]

XP_ACHIEVEMENT = 30
XP_DAILY_PLAN = 60


def xp_to_next(level: int) -> int:
    return 100 + 35 * (level - 1)


def level_from_xp(xp: int) -> tuple[int, int, int]:
    """(уровень, опыт внутри уровня, опыт до следующего уровня)."""
    level = 1
    rest = max(0, int(xp))
    while rest >= xp_to_next(level):
        rest -= xp_to_next(level)
        level += 1
    return level, rest, xp_to_next(level)


def level_title(level: int) -> str:
    title = LEVEL_TITLES[0][1]
    for lvl, name in LEVEL_TITLES:
        if level >= lvl:
            title = name
    return title


def session_xp(rating: float, new_best: bool, level_up: bool) -> int:
    return int(15 + round(rating * 0.35) + (10 if new_best else 0) + (5 if level_up else 0))


def streaks(active_days: set[str], today: date) -> tuple[int, int]:
    """(текущая серия, лучшая серия). Серия не сгорает, пока не закончился сегодняшний день."""
    if not active_days:
        return 0, 0
    days = sorted(date.fromisoformat(d) for d in active_days)
    best = run = 1
    for a, b in zip(days, days[1:]):
        if (b - a).days == 1:
            run += 1
        elif (b - a).days > 1:
            run = 1
        best = max(best, run)
    cur_day = today if today.isoformat() in active_days else today - timedelta(days=1)
    current = 0
    while cur_day.isoformat() in active_days:
        current += 1
        cur_day -= timedelta(days=1)
    return current, max(best, current)


def game_rating_from(ratings_newest_first: list[float]) -> float | None:
    """Оценка по упражнению: среднее трёх лучших из последних десяти попыток."""
    recent = ratings_newest_first[:10]
    if not recent:
        return None
    top = sorted(recent, reverse=True)[:3]
    return sum(top) / len(top)


@dataclass
class Achievement:
    id: str
    title: str
    description: str
    icon: str
    target: float
    value: Callable[["Progress", GameResult | None], float]
    secret: bool = False


@dataclass
class RecordOutcome:
    xp: int = 0
    new_best: bool = False
    prev_best_rating: float | None = None
    game_level_before: int = 1
    game_level_after: int = 1
    achievements: list[Achievement] = field(default_factory=list)
    plan_completed: bool = False
    player_level_before: int = 1
    player_level_after: int = 1


def _max_metric(p: "Progress", game: str, key: str, cond: Callable[[dict], bool] | None = None) -> float:
    best = 0.0
    for r in p.storage.results(game):
        if cond is None or cond(r):
            val = r["metrics"].get(key)
            if isinstance(val, (int, float)):
                best = max(best, float(val))
    return best


def _any(p: "Progress", game: str, cond: Callable[[dict], bool]) -> float:
    return 1.0 if any(cond(r) for r in p.storage.results(game)) else 0.0


def _hour_of(r: dict) -> int:
    return datetime.fromtimestamp(r["ts"]).hour


ACHIEVEMENTS: list[Achievement] = [
    Achievement("first", "Первый шаг", "Завершите первое упражнение", "flag", 1,
                lambda p, r: min(1, p.storage.result_count())),
    Achievement("daily1", "Режим дня", "Выполните тренировку дня", "calendar", 1,
                lambda p, r: p.plans_completed()),
    Achievement("daily10", "Дисциплина", "Выполните тренировку дня 10 раз", "calendar", 10,
                lambda p, r: p.plans_completed()),
    Achievement("streak3", "Разогрев", "Тренируйтесь 3 дня подряд", "flame", 3,
                lambda p, r: p.streak()[1]),
    Achievement("streak7", "Неделя силы", "Тренируйтесь 7 дней подряд", "flame", 7,
                lambda p, r: p.streak()[1]),
    Achievement("streak30", "Месяц без пропусков", "Тренируйтесь 30 дней подряд", "flame", 30,
                lambda p, r: p.streak()[1]),
    Achievement("sessions50", "Упорство", "Завершите 50 упражнений", "target", 50,
                lambda p, r: p.storage.result_count()),
    Achievement("sessions300", "Железная воля", "Завершите 300 упражнений", "target", 300,
                lambda p, r: p.storage.result_count()),
    Achievement("explorer", "Исследователь", "Попробуйте все упражнения", "compass", len(GAMES),
                lambda p, r: len(p.storage.games_played() & set(GAME_BY_ID))),
    Achievement("hour", "Первый час", "Проведите в тренировках 1 час", "clock", 3600,
                lambda p, r: p.storage.total_duration()),
    Achievement("nback3", "Три шага назад", "Пройдите 3-назад с точностью от 80%", "brain", 3,
                lambda p, r: _max_metric(p, "nback", "n", lambda x: (x["accuracy"] or 0) >= 0.8)),
    Achievement("nback5", "Рабочая память PRO", "Пройдите 5-назад с точностью от 80%", "brain", 5,
                lambda p, r: _max_metric(p, "nback", "n", lambda x: (x["accuracy"] or 0) >= 0.8)),
    Achievement("span8", "Цифровой гигант", "Запомните ряд из 8 цифр", "hash", 8,
                lambda p, r: _max_metric(p, "digit_span", "span", lambda x: x["metrics"].get("mode") == "forward")),
    Achievement("span6b", "Задом наперёд", "Воспроизведите 6 цифр в обратном порядке", "hash", 6,
                lambda p, r: _max_metric(p, "digit_span", "span", lambda x: x["metrics"].get("mode") == "backward")),
    Achievement("words15", "Мнемонист", "Вспомните 15 слов за одну попытку", "book", 15,
                lambda p, r: _max_metric(p, "words", "correct")),
    Achievement("matrix10", "Фотографическая память", "Дойдите до 10-го уровня визуальной памяти", "grid", 10,
                lambda p, r: _max_metric(p, "matrix", "reached")),
    Achievement("corsi7", "Навигатор", "Повторите последовательность из 7 блоков", "cube", 7,
                lambda p, r: _max_metric(p, "corsi", "span")),
    Achievement("schulte30", "Орлиный глаз", "Пройдите таблицу 5×5 быстрее 30 секунд", "eye", 1,
                lambda p, r: _any(p, "schulte", lambda x: x["metrics"].get("size") == 5 and x["metrics"].get("time", 999) < 30)),
    Achievement("schulte20", "Молниеносный взгляд", "Пройдите таблицу 5×5 быстрее 20 секунд", "eye", 1,
                lambda p, r: _any(p, "schulte", lambda x: x["metrics"].get("size") == 5 and x["metrics"].get("time", 999) < 20)),
    Achievement("math30", "Калькулятор", "Решите 30 примеров за одну сессию", "calc", 30,
                lambda p, r: _max_metric(p, "math", "correct")),
    Achievement("series10", "Безупречная логика", "Решите 10 из 10 числовых рядов", "trend", 10,
                lambda p, r: _max_metric(p, "series", "correct")),
    Achievement("raven6", "Равен бы одобрил", "Решите матрицу высшей сложности", "puzzle", 6,
                lambda p, r: _max_metric(p, "raven", "max_solved")),
    Achievement("stroop40", "Стальные нервы", "Дайте 40 верных ответов в тесте Струпа", "shield", 40,
                lambda p, r: _max_metric(p, "stroop", "correct")),
    Achievement("perfect", "Перфекционист", "Пройдите упражнение с 20+ ответами без ошибок", "star", 1,
                lambda p, r: 1.0 if any((x["accuracy"] or 0) >= 0.9999 and x["metrics"].get("trials", 0) >= 20
                                        for x in p.storage.results()) else 0.0),
    Achievement("index500", "Острый ум", "Достигните индекса MindForge 500", "bolt", 500,
                lambda p, r: p.index() or 0),
    Achievement("index750", "Выдающийся интеллект", "Достигните индекса MindForge 750", "bolt", 750,
                lambda p, r: p.index() or 0),
    Achievement("cards100", "Интервальный мастер", "Повторите 100 карточек", "cards", 100,
                lambda p, r: p.storage.review_count()),
    Achievement("owl", "Ночная сова", "Тренируйтесь после 23:00", "moon", 1,
                lambda p, r: 1.0 if any(_hour_of(x) >= 23 for x in p.storage.results()) else 0.0, secret=True),
    Achievement("lark", "Ранняя пташка", "Тренируйтесь до 7:00 утра", "sun", 1,
                lambda p, r: 1.0 if any(_hour_of(x) < 7 for x in p.storage.results()) else 0.0, secret=True),
]

ACH_BY_ID = {a.id: a for a in ACHIEVEMENTS}

DOMAIN_ORDER = ["attention", "speed", "memory", "spatial", "flexibility", "logic"]


class Progress:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    # -------------------------------------------------------------- опыт
    @property
    def xp(self) -> int:
        return int(self.storage.get("xp", 0))

    def add_xp(self, amount: int) -> None:
        self.storage.set("xp", self.xp + int(amount))

    def level_info(self) -> tuple[int, int, int]:
        return level_from_xp(self.xp)

    # ------------------------------------------------------------- серии
    def active_days(self) -> set[str]:
        return set(self.storage.activity_by_day().keys())

    def streak(self) -> tuple[int, int]:
        return streaks(self.active_days(), self.storage.today())

    # ---------------------------------------------------------- профиль
    def game_rating(self, game: str, results: list[dict] | None = None) -> float | None:
        rows = results if results is not None else self.storage.results(game, limit=10)
        return game_rating_from([r["rating"] for r in rows if r["game"] == game])

    def profile(self, results: list[dict] | None = None) -> dict[str, float | None]:
        prof: dict[str, float | None] = {}
        for domain in DOMAINS:
            vals = []
            for g in games_in_domain(domain):
                rows = [r for r in results if r["game"] == g.id] if results is not None else None
                gr = self.game_rating(g.id, rows)
                if gr is not None:
                    vals.append(gr)
            prof[domain] = sum(vals) / len(vals) if vals else None
        return prof

    def index(self, results: list[dict] | None = None) -> int | None:
        vals = [v for v in self.profile(results).values() if v is not None]
        if not vals:
            return None
        return int(round(sum(vals) / len(vals) * 10))

    def index_history(self, days: int = 60) -> list[tuple[str, int]]:
        """Индекс на конец каждого дня с активностью (для графика)."""
        rows = list(reversed(self.storage.results()))  # от старых к новым
        if not rows:
            return []
        start = (self.storage.today() - timedelta(days=days - 1)).isoformat()
        out: list[tuple[str, int]] = []
        seen: list[dict] = []
        by_day: dict[str, list[dict]] = {}
        for r in rows:
            by_day.setdefault(r["day"], []).append(r)
        for day in sorted(by_day):
            seen.extend(by_day[day])
            if day >= start:
                idx = self.index(list(reversed(seen)))
                if idx is not None:
                    out.append((day, idx))
        return out

    # --------------------------------------------------------- план дня
    def daily_count(self) -> int:
        return int(self.storage.get("settings.daily_count", 5))

    def daily_plan(self) -> list[str]:
        today = self.storage.today()
        key = f"plan.{today.isoformat()}"
        plan = self.storage.get(key)
        if isinstance(plan, list) and plan and all(g in GAME_BY_ID for g in plan):
            return plan
        plan = self._make_plan(today, self.daily_count())
        self.storage.set(key, plan)
        return plan

    def regenerate_plan(self) -> list[str]:
        day = self.storage.today().isoformat()
        old = self.storage.get(f"plan.{day}")
        salt_key = f"plansalt.{day}"
        for _ in range(8):
            self.storage.set(salt_key, int(self.storage.get(salt_key, 0)) + 1)
            self.storage.delete_prefix(f"plan.{day}")
            plan = self.daily_plan()
            if plan != old:
                break
        return plan

    def _make_plan(self, today: date, count: int) -> list[str]:
        salt = int(self.storage.get(f"plansalt.{today.isoformat()}", 0))
        rng = random.Random(today.toordinal() * 7919 + self.storage.result_count() * 31 + salt * 104729)
        prof = self.profile()
        last_played: dict[str, float] = {}
        for r in self.storage.results(limit=400):
            last_played.setdefault(r["game"], r["ts"])
        # Сначала слабые и ещё не опробованные области.
        domains = list(DOMAINS)
        rng.shuffle(domains)
        if salt == 0:
            domains.sort(key=lambda d: -1 if prof[d] is None else prof[d])
        chosen: list[str] = []
        count = max(1, min(count, len(GAMES)))
        while len(chosen) < count:
            added = False
            for d in domains:
                if len(chosen) >= count:
                    break
                cands = [g.id for g in games_in_domain(d) if g.id not in chosen]
                if not cands:
                    continue
                rng.shuffle(cands)
                if salt == 0:
                    cands.sort(key=lambda g: last_played.get(g, 0.0))
                chosen.append(cands[0])
                added = True
            if not added:
                break
        chosen.sort(key=lambda g: DOMAIN_ORDER.index(GAME_BY_ID[g].domain))
        return chosen

    def plan_status(self) -> list[tuple[str, bool]]:
        done = self.storage.games_on_day(self.storage.today().isoformat())
        return [(g, g in done) for g in self.daily_plan()]

    def plans_completed(self) -> int:
        return len(self.storage.keys("planbonus."))

    # ------------------------------------------------------ достижения
    def unlocked(self) -> dict[str, float]:
        out = {}
        for key in self.storage.keys("ach."):
            out[key[4:]] = float(self.storage.get(key, 0))
        return out

    def achievement_progress(self, ach: Achievement) -> float:
        try:
            return float(ach.value(self, None))
        except Exception:
            return 0.0

    def check_achievements(self, result: GameResult | None = None) -> list[Achievement]:
        unlocked = self.unlocked()
        new = []
        for ach in ACHIEVEMENTS:
            if ach.id in unlocked:
                continue
            try:
                val = ach.value(self, result)
            except Exception:
                continue
            if val >= ach.target:
                self.storage.set(f"ach.{ach.id}", self.storage.now())
                self.add_xp(XP_ACHIEVEMENT)
                new.append(ach)
        return new

    # ------------------------------------------------ запись результата
    def record(self, result: GameResult) -> RecordOutcome:
        out = RecordOutcome()
        out.player_level_before = self.level_info()[0]
        prev = self.storage.results(result.game)
        out.prev_best_rating = max((r["rating"] for r in prev), default=None)
        out.new_best = out.prev_best_rating is not None and result.rating > out.prev_best_rating
        out.game_level_before = self.storage.game_level(result.game)
        meta = GAME_BY_ID.get(result.game)
        max_level = meta.max_level if meta else 99
        out.game_level_after = max(1, min(max_level, int(result.next_level)))
        self.storage.set_game_level(result.game, out.game_level_after)
        self.storage.add_result(result)

        out.xp = session_xp(result.rating, out.new_best, out.game_level_after > out.game_level_before)
        self.add_xp(out.xp)

        today = day_of(result.ts)
        if today == self.storage.today().isoformat() and not self.storage.get(f"planbonus.{today}"):
            if all(done for _, done in self.plan_status()):
                self.storage.set(f"planbonus.{today}", True)
                self.add_xp(XP_DAILY_PLAN)
                out.xp += XP_DAILY_PLAN
                out.plan_completed = True

        out.achievements = self.check_achievements(result)
        out.xp += XP_ACHIEVEMENT * len(out.achievements)
        out.player_level_after = self.level_info()[0]
        return out

    def record_review(self) -> list[Achievement]:
        self.add_xp(1)
        return self.check_achievements()
