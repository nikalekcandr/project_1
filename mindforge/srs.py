"""Интервальные повторения: вариант алгоритма SM-2 с четырьмя оценками.

1 — «Снова» (не вспомнил), 2 — «Трудно», 3 — «Хорошо», 4 — «Легко».
"""
from __future__ import annotations

DAY = 86400.0
MIN_EASE = 1.3
MAX_EASE = 3.2

GRADE_LABELS = {1: "Снова", 2: "Трудно", 3: "Хорошо", 4: "Легко"}


def schedule(card: dict, grade: int, now: float) -> dict:
    """Возвращает копию карточки с новыми ease/interval/reps/lapses/due."""
    if grade not in (1, 2, 3, 4):
        raise ValueError("grade must be 1..4")
    c = dict(card)
    ease = float(c.get("ease", 2.5))
    interval = float(c.get("interval", 0.0))  # в днях
    reps = int(c.get("reps", 0))
    lapses = int(c.get("lapses", 0))

    if grade == 1:
        if reps > 0:
            lapses += 1
        reps = 0
        ease = max(MIN_EASE, ease - 0.2)
        interval = 0.0
        due = now + 60
    elif reps == 0:
        if grade == 2:
            interval = 0.0
            due = now + 10 * 60
        else:
            interval = 1.0 if grade == 3 else 4.0
            if grade == 4:
                ease = min(MAX_EASE, ease + 0.15)
            reps = 1
            due = now + interval * DAY
    else:
        if grade == 2:
            interval = max(1.0, interval * 1.2)
            ease = max(MIN_EASE, ease - 0.15)
        elif grade == 3:
            interval = max(interval + 1, interval * ease)
        else:
            interval = max(interval + 1, interval * ease * 1.3)
            ease = min(MAX_EASE, ease + 0.15)
        interval = float(round(interval))
        reps += 1
        due = now + interval * DAY

    c.update(ease=round(ease, 3), interval=interval, reps=reps, lapses=lapses, due=due)
    return c


def format_interval(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 90:
        return "<1 мин"
    if seconds < 3600:
        return f"{round(seconds / 60)} мин"
    if seconds < DAY:
        return f"{round(seconds / 3600)} ч"
    days = seconds / DAY
    if days < 30:
        return f"{round(days)} дн"
    if days < 365:
        return f"{days / 30:.1f} мес".replace(".0 ", " ")
    return f"{days / 365:.1f} г"


def preview(card: dict, now: float) -> dict[int, str]:
    """Подписи с интервалом для каждой кнопки оценки."""
    return {g: format_interval(schedule(card, g, now)["due"] - now) for g in (1, 2, 3, 4)}


def parse_import(text: str) -> list[tuple[str, str]]:
    """Разбирает строки вида «вопрос ; ответ» (разделители: TAB, ;, —, =, :)."""
    pairs: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        for sep in ("\t", ";", " — ", " - ", "=", ":"):
            if sep in line:
                front, back = line.split(sep, 1)
                if front.strip() and back.strip():
                    pairs.append((front.strip(), back.strip()))
                break
    return pairs
