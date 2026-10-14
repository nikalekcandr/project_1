import pytest

from finradar.salary import find_salary_in_text, normalize, parse_salary

RATES = {"RUB": 1.0, "USD": 80.0, "EUR": 90.0, "GBP": 100.0, "KZT": 0.16, "AED": 21.8}


@pytest.mark.parametrize(
    "text, lo, hi, cur, period, gross",
    [
        ("от 150 000 до 250 000 ₽ на руки", 150_000, 250_000, "RUB", "month", False),
        ("до 300 тыс. руб.", None, 300_000, "RUB", "month", None),
        ("300-400к ₽", 300_000, 400_000, "RUB", "month", None),
        ("$120k – $150k per year", 120_000, 150_000, "USD", "year", None),
        ("£60,000 - £70,000 a year", 60_000, 70_000, "GBP", "year", None),
        ("1,2 млн ₽ в год", 1_200_000, 1_200_000, "RUB", "year", None),
        ("$45/hr", 45, 45, "USD", "hour", None),
        ("от 3 000 $", 3_000, None, "USD", "month", None),
        ("150 000 – 200 000 ₽ за месяц, до вычета налогов", 150_000, 200_000, "RUB", "month", True),
        ("€80K–100K", 80_000, 100_000, "EUR", "year", None),
        ("USD 100-120k", 100_000, 120_000, "USD", "year", None),
        ("from $90,000", 90_000, None, "USD", "year", None),
        ("up to €5,000 per month", None, 5_000, "EUR", "month", None),
        ("ЗП: 180-220 тыс. руб. gross", 180_000, 220_000, "RUB", "month", True),
        ("AED 25,000 - 35,000 monthly", 25_000, 35_000, "AED", "month", None),
        ("3 600 000 ₽", 3_600_000, 3_600_000, "RUB", "year", None),
    ],
)
def test_parse_salary(text, lo, hi, cur, period, gross):
    s = parse_salary(text)
    assert s is not None
    assert (s.min, s.max, s.currency, s.period, s.gross) == (lo, hi, cur, period, gross)


@pytest.mark.parametrize("text", ["", "по договорённости", "опыт от 3 лет", "Компания основана в 2015 году"])
def test_parse_salary_rejects_noise(text):
    s = parse_salary(text)
    assert s is None or s.currency is None


def test_normalize_net_and_annual():
    month_rub, year_usd = normalize(parse_salary("200 000 ₽ до вычета налогов"), RATES)
    assert month_rub == 174_000  # gross -> take-home at 13%
    month_rub, year_usd = normalize(parse_salary("$120,000 per year"), RATES)
    assert year_usd == 120_000
    assert month_rub == 800_000


def test_find_salary_in_free_text():
    text = "Вакансия: FP&A аналитик\nКомпания: Сбер\nЗП: 250-300к ₽ на руки\nОпыт от 3 лет"
    sal, line = find_salary_in_text(text)
    assert sal.min == 250_000 and sal.max == 300_000 and sal.currency == "RUB" and sal.gross is False
    assert "250-300" in line
    assert find_salary_in_text("Опыт работы от 3 лет, 2024 год")[0] is None
