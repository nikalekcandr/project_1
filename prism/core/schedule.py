"""Генерация расписаний: периоды начисления, фиксинги, наблюдения, платежи."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from .calendars import BusinessCalendar
from .dates import BDC, Tenor, add_months
from .daycount import DayCount


@dataclass(frozen=True)
class Period:
    accrual_start: date
    accrual_end: date
    fixing_date: date
    payment_date: date
    accrual_fraction: float
    observation_dates: tuple[date, ...] = ()
    observation_weights: tuple[float, ...] = ()
    notional: float = 1.0

    def with_notional(self, n: float) -> "Period":
        return replace(self, notional=n)


@dataclass
class Schedule:
    periods: list[Period]
    flags: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.periods)

    def __iter__(self):
        return iter(self.periods)

    @property
    def payment_dates(self) -> list[date]:
        return [p.payment_date for p in self.periods]

    @property
    def fixing_dates(self) -> list[date]:
        return [p.fixing_date for p in self.periods]

    @property
    def all_observation_dates(self) -> list[date]:
        s: set[date] = set()
        for p in self.periods:
            s.add(p.fixing_date)
            s.update(p.observation_dates)
        return sorted(s)


def roll_dates(start: date, end: date, frequency: str | Tenor, backward: bool = True, eom: bool = False) -> list[date]:
    """Невыровненные даты ролла от start до end (включительно)."""
    if isinstance(frequency, str) and frequency.lower() in ("once", "bullet", "zero", "term"):
        return [start, end]
    t = Tenor.parse(frequency)
    out: list[date]
    if t.unit in ("M", "Y"):
        months = t.months
        if backward:
            out = [end]
            k = 1
            while True:
                d = add_months(end, -months * k, eom)
                if d <= start:
                    break
                out.append(d)
                k += 1
            out.append(start)
            out.reverse()
        else:
            out = [start]
            k = 1
            while True:
                d = add_months(start, months * k, eom)
                if d >= end:
                    break
                out.append(d)
                k += 1
            out.append(end)
    else:
        step = timedelta(days=t.n * (7 if t.unit == "W" else 1))
        out = [start]
        d = start + step
        while d < end:
            out.append(d)
            d += step
        out.append(end)
    # убрать вырожденный короткий стаб длиной < 4 дней
    if len(out) > 2 and (out[1] - out[0]).days < 4 and backward:
        out.pop(1)
    if len(out) > 2 and (out[-1] - out[-2]).days < 4 and not backward:
        out.pop(-2)
    return out


def generate_periods(
    start: date,
    end: date,
    frequency: str | Tenor,
    calendar: BusinessCalendar,
    daycount: DayCount = DayCount.ACT_365F,
    bdc: BDC = BDC.MODIFIED_FOLLOWING,
    *,
    backward: bool = True,
    eom: bool = False,
    adjust_accrual: bool = True,
    fixing_lag: int = 0,
    fixing_in_arrears: bool = True,
    fixing_calendar: BusinessCalendar | None = None,
    payment_lag: int = 0,
    payment_calendar: BusinessCalendar | None = None,
    observation: str | None = None,
    observation_calendar: BusinessCalendar | None = None,
) -> Schedule:
    """Сгенерировать периоды.

    ``fixing_in_arrears=True`` — фиксинг в конце периода (валютные стрипы,
    средние ставки); ``False`` — в начале (классический IRS/FRA).
    ``fixing_lag`` — сдвиг фиксинга назад на N рабочих дней.
    ``observation`` — подрасписание наблюдений внутри периода ('daily',
    'weekly', '1W'...) для усреднения и накопления.
    """
    fix_cal = fixing_calendar or calendar
    pay_cal = payment_calendar or calendar
    obs_cal = observation_calendar or fix_cal
    if isinstance(frequency, str) and frequency.lower() == "daily":
        # каждый рабочий день — отдельный период (аккумуляторы с ежедневной выплатой)
        days = calendar.business_days(start, end)
        raw = days
    else:
        raw = roll_dates(start, end, frequency, backward=backward, eom=eom)
    adj = [calendar.adjust(d, bdc) for d in raw] if adjust_accrual else list(raw)
    periods: list[Period] = []
    for a, b in zip(adj[:-1], adj[1:]):
        if b <= a:
            continue
        anchor = b if fixing_in_arrears else a
        fix = fix_cal.advance_business_days(anchor, -fixing_lag) if fixing_lag else fix_cal.adjust(anchor, BDC.PRECEDING)
        pay = pay_cal.advance_business_days(b, payment_lag) if payment_lag else pay_cal.adjust(b, BDC.FOLLOWING)
        obs: tuple[date, ...] = ()
        w: tuple[float, ...] = ()
        if observation:
            if observation.lower() == "daily":
                ods = obs_cal.business_days(a + timedelta(days=1), b) if periods else obs_cal.business_days(a, b)
            else:
                ods = [obs_cal.adjust(d, BDC.PRECEDING) for d in roll_dates(a, b, observation)[1:]]
            if fixing_lag:
                ods = [obs_cal.advance_business_days(d, -fixing_lag) for d in ods]
            ods = sorted(set(ods))
            obs = tuple(ods)
            w = tuple(1.0 / len(ods) for _ in ods) if ods else ()
        periods.append(Period(a, b, fix, pay, daycount.year_fraction(a, b), obs, w))
    flags = calendar.coverage_flags(adj)
    for c in (fix_cal, pay_cal):
        if c is not calendar:
            for f in c.coverage_flags(adj):
                if f not in flags:
                    flags.append(f)
    return Schedule(periods, flags)


def explicit_periods(
    fixing_dates: list[date],
    payment_dates: list[date] | None,
    daycount: DayCount = DayCount.ACT_365F,
    start: date | None = None,
) -> Schedule:
    """Расписание из явного списка дат (как в термшите)."""
    payment_dates = payment_dates or fixing_dates
    if len(payment_dates) != len(fixing_dates):
        raise ValueError("число дат платежей не совпадает с числом фиксингов")
    periods = []
    prev = start or fixing_dates[0]
    for f, p in zip(fixing_dates, payment_dates):
        a = prev
        b = f if f > a else p
        periods.append(Period(a, b, f, p, max(daycount.year_fraction(a, b), 0.0)))
        prev = b
    return Schedule(periods)
