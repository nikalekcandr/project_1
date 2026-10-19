from datetime import date

import pytest

from prism.core.calendars import get_calendar
from prism.core.dates import BDC, Tenor, add_tenor
from prism.core.daycount import DayCount
from prism.core.schedule import generate_periods


def test_ru_production_calendar_transfers():
    ru = get_calendar("RU")
    assert not ru.is_business_day(date(2026, 1, 9))       # перенос с 4 января
    assert ru.is_business_day(date(2025, 11, 1))          # рабочая суббота 2025
    assert not ru.is_business_day(date(2025, 11, 3))
    assert not ru.is_business_day(date(2026, 3, 9))       # 8 марта в воскресенье → 9 марта
    assert ru.coverage_flags([date(2026, 6, 1)]) == []
    assert ru.coverage_flags([date(2027, 6, 1)])          # 2027 не загружен — экстраполяция с флагом


def test_joint_calendar_cny_new_year():
    j = get_calendar("RUB+CNY")
    assert not j.is_business_day(date(2026, 2, 17))       # китайский Новый год
    assert get_calendar("RU").is_business_day(date(2026, 2, 17))
    assert j.adjust(date(2026, 2, 16), BDC.FOLLOWING) == date(2026, 2, 24)


def test_modified_following_month_end():
    ru = get_calendar("RU")
    assert ru.adjust(date(2026, 5, 31), BDC.MODIFIED_FOLLOWING) == date(2026, 5, 29)
    assert add_tenor(date(2026, 1, 30), "1M", ru) == date(2026, 2, 27)


def test_daycounts():
    assert DayCount.ACT_365F.year_fraction(date(2026, 1, 1), date(2027, 1, 1)) == 1.0
    assert abs(DayCount.ACT_360.year_fraction(date(2026, 1, 1), date(2026, 7, 1)) - 181 / 360) < 1e-15
    assert DayCount.THIRTY_360.year_fraction(date(2026, 1, 31), date(2026, 2, 28)) == pytest.approx(28 / 360)
    assert Tenor.parse("ON").n == 1 and Tenor.parse("18M").months == 18


def test_schedule_daily_observations():
    s = generate_periods(date(2026, 10, 15), date(2027, 1, 15), "1M", get_calendar("RU"), observation="daily")
    assert len(s) == 3
    assert all(p.observation_dates for p in s)
    assert abs(sum(s.periods[0].observation_weights) - 1) < 1e-12
