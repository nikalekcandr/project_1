"""Salary parsing and normalization for Russian and English postings.

Handles things like::

    "от 150 000 до 250 000 ₽ на руки"     -> 150000..250000 RUB / month, net
    "до 300 тыс. руб."                    -> ..300000 RUB
    "300-400к"                            -> 300000..400000 (currency from context)
    "$120k – $150k per year"              -> 120000..150000 USD / year
    "£60,000 - £70,000 a year"            -> GBP / year
    "1,2 млн ₽ в год"                     -> 1200000 RUB / year
    "$45/hr"                              -> 45 USD / hour
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Order matters: more specific tokens first (BYN before RUB, S$ before $ ...).
_CURRENCIES: list[tuple[str, str]] = [
    (r"бел\.?\s*руб|byn|byr", "BYN"),
    (r"s\$|sgd", "SGD"),
    (r"hk\$|hkd", "HKD"),
    (r"c\$|cad", "CAD"),
    (r"a\$|aud", "AUD"),
    (r"₽|руб|rub|rur|р\.(?!\w)|(?<=\d)\s?р(?![а-яa-z])|(?<=[\dкk])р(?![а-яa-z])", "RUB"),
    (r"\$|usd|долл|dollar", "USD"),
    (r"€|eur|евро|euro", "EUR"),
    (r"£|gbp|фунт|pound", "GBP"),
    (r"₸|kzt|тенге|(?<=\d)\s?тг", "KZT"),
    (r"aed|дирхам|dirham", "AED"),
    (r"chf|франк", "CHF"),
    (r"cny|rmb|юан|yuan|¥", "CNY"),
    (r"uzs|сум(?![мм])", "UZS"),
    (r"amd|драм", "AMD"),
    (r"gel|₾|лари", "GEL"),
    (r"rsd|динар", "RSD"),
    (r"₺|try(?![a-z])|лир", "TRY"),
    (r"₹|inr|rupee", "INR"),
    (r"pln|zł|злот", "PLN"),
    (r"czk|kč", "CZK"),
    (r"sar|риял", "SAR"),
]
_CURRENCY_RES = [(re.compile(p, re.IGNORECASE), c) for p, c in _CURRENCIES]

_PERIODS = [
    ("year", r"в\s+год|/\s*год|за\s+год|годов|per\s+year|a\s+year|/\s*y(?:ea)?r|annual|annum|p\.?\s?a\.?(?![a-z])|yearly|\bpa\b|year"),
    ("month", r"в\s+мес|/\s*мес|за\s+мес|мес\.|ежемес|per\s+month|a\s+month|/\s*mo(?:nth)?|monthly|month"),
    ("day", r"в\s+день|/\s*день|за\s+день|per\s+day|a\s+day|/\s*day|daily|day\s+rate|ставка\s+в\s+день"),
    ("hour", r"в\s+час|/\s*час|за\s+час|per\s+hour|an\s+hour|/\s*h(?:ou)?r|hourly|\bph\b"),
]
_PERIOD_RES = [(p, re.compile(r, re.IGNORECASE)) for p, r in _PERIODS]

_NET = re.compile(r"на\s+руки|чистыми|после\s+вычета|net(?![a-z])|нетто|after\s+tax", re.IGNORECASE)
_GROSS = re.compile(r"до\s+вычета|gross|брутто|before\s+tax|до\s+налог|до\s+ндфл|с\s+учет\w*\s+ндфл", re.IGNORECASE)

_NUM = re.compile(
    r"(?<![\w.])(\d{1,3}(?:[   ',.]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"(?:\s*(k|к|kk|кк|тыс\.?|тысяч\w*|thousand|thou|млн\.?|миллион\w*|mln|mio|million|m(?![a-zа-я])|м(?![а-яa-z])))?",
    re.IGNORECASE,
)

_MULT = {
    "k": 1e3, "к": 1e3, "тыс": 1e3, "тыс.": 1e3, "thousand": 1e3, "thou": 1e3,
    "kk": 1e6, "кк": 1e6, "млн": 1e6, "млн.": 1e6, "mln": 1e6, "mio": 1e6, "million": 1e6, "m": 1e6, "м": 1e6,
}

_UPTO = re.compile(r"(?:\bдо|up\s+to|max(?:imum)?|не\s+более|<)\s*[^\d\s]{0,3}\s*$", re.IGNORECASE)
_FROM = re.compile(r"(?:\bот|from|starting\s+(?:at|from)?|min(?:imum)?|не\s+менее|>|over|\bс)\s*[^\d\s]{0,3}\s*$", re.IGNORECASE)

SALARY_HINT = re.compile(
    r"зарплат|з/п|зп\b|оклад|вилка|доход|компенсац|вознагражд|salary|compensation|pay(?:ment)?\b|"
    r"base\b|ote\b|package|rate\b|ставк",
    re.IGNORECASE,
)

# Monthly salaries above these (in local currency) are almost certainly annual figures.
_YEARLY_THRESHOLD = {
    "RUB": 2_500_000, "KZT": 15_000_000, "UZS": 400_000_000, "BYN": 60_000, "AMD": 8_000_000,
    "AED": 150_000, "SAR": 150_000, "CNY": 150_000, "INR": 1_000_000, "TRY": 600_000,
    "RSD": 1_500_000, "GEL": 40_000, "PLN": 60_000, "CZK": 300_000,
}
_DEFAULT_YEARLY_THRESHOLD = 20_000  # USD / EUR / GBP / CHF / ...
_HOURLY_THRESHOLD = {"USD": 300, "EUR": 300, "GBP": 300, "CHF": 300, "CAD": 300, "AUD": 300, "SGD": 300}


@dataclass
class Salary:
    min: float | None
    max: float | None
    currency: str | None
    period: str | None
    gross: bool | None

    @property
    def mid(self) -> float | None:
        vals = [v for v in (self.min, self.max) if v]
        if not vals:
            return None
        return sum(vals) / len(vals)


def detect_currency(text: str) -> str | None:
    for rx, code in _CURRENCY_RES:
        if rx.search(text):
            return code
    return None


def detect_period(text: str) -> str | None:
    for period, rx in _PERIOD_RES:
        if rx.search(text):
            return period
    return None


def detect_gross(text: str) -> bool | None:
    if _NET.search(text):
        return False
    if _GROSS.search(text):
        return True
    return None


def _to_number(raw: str) -> float | None:
    s = raw.replace(" ", " ").replace(" ", " ").replace("'", " ")
    groups = re.split(r"[ ,.]", s)
    if len(groups) > 1 and all(len(g) == 3 for g in groups[1:]) and groups[0]:
        return float("".join(groups))
    if len(groups) > 2 and all(len(g) == 3 for g in groups[1:-1]):
        # 1 234 567,89
        return float("".join(groups[:-1]) + "." + groups[-1])
    try:
        return float(s.replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def _amounts(text: str) -> list[tuple[float, float, int, int]]:
    """Return (base_value, multiplier, start, end) for every number-like token."""
    out = []
    for m in _NUM.finditer(text):
        val = _to_number(m.group(1))
        if val is None:
            continue
        mult_raw = (m.group(2) or "").lower().rstrip(".")
        if mult_raw.startswith("тысяч"):
            mult = 1e3
        elif mult_raw.startswith("миллион"):
            mult = 1e6
        else:
            mult = _MULT.get(mult_raw, 1.0)
        out.append((val, mult, m.start(), m.end()))
    return out


_RANGE_SEP = {"-", "–", "—", "до", "to", "and", "и", "…", "...", "..", ""}
_SEP_NOISE = re.compile(r"[\s$€£₽¥₸]|руб\.?|usd|eur|rub|gbp|k(?![a-z])|к(?![а-я])", re.IGNORECASE)


def parse_salary(text: str | None, *, default_currency: str | None = None) -> Salary | None:
    """Parse a salary string. Returns None when there is no plausible amount."""
    if not text:
        return None
    t = text.strip()
    if not t or len(t) > 400:
        return None
    currency = detect_currency(t) or default_currency
    tokens = []
    for base, mult, s, e in _amounts(t):
        if "%" in t[e : e + 2]:
            continue
        if mult == 1 and 1990 <= base <= 2100 and re.match(r"\s*(?:год|year|г\.)", t[e : e + 8], re.IGNORECASE):
            continue
        tokens.append((base, mult, s, e))
    if not tokens:
        return None
    significant = [tk for tk in tokens if tk[0] * tk[1] >= 10]
    tokens = significant or tokens

    lo = hi = None
    if len(tokens) >= 2:
        a, b = tokens[0], tokens[1]
        sep = _SEP_NOISE.sub("", t[a[3] : b[2]]).lower()
        if sep in _RANGE_SEP:
            a_mult = a[1]
            if a_mult == 1 and b[1] > 1 and a[0] < 1000:
                a_mult = b[1]  # "300-400к": multiplier written once
            lo, hi = sorted((a[0] * a_mult, b[0] * b[1]))
    if lo is None and hi is None:
        base, mult, s, e = tokens[0]
        val = base * mult
        prefix = t[max(0, s - 14) : s]
        if _UPTO.search(prefix):
            hi = val
        elif _FROM.search(prefix) or t[e : e + 2].strip().startswith("+"):
            lo = val
        else:
            lo = hi = val

    period = detect_period(t)
    sal = Salary(min=lo, max=hi, currency=currency, period=period, gross=detect_gross(t))
    if sal.period is None:
        sal.period = infer_period(sal)
    return sal if is_plausible(sal) else None


def infer_period(sal: Salary) -> str | None:
    mid = sal.mid
    if not mid or not sal.currency:
        return None
    if mid < _HOURLY_THRESHOLD.get(sal.currency, 0):
        return "hour"
    if mid >= _YEARLY_THRESHOLD.get(sal.currency, _DEFAULT_YEARLY_THRESHOLD):
        return "year"
    return "month"


def is_plausible(sal: Salary) -> bool:
    mid = sal.mid
    if not mid or mid <= 0:
        return False
    if sal.min and sal.max and sal.max > sal.min * 10:
        return False
    if sal.currency is None:
        return mid >= 1000
    return True


_PERIOD_PER_MONTH = {"month": 1.0, "year": 1 / 12, "day": 21.0, "hour": 168.0, None: 1.0}
_PERIOD_PER_YEAR = {"month": 12.0, "year": 1.0, "day": 250.0, "hour": 2000.0, None: 12.0}

# Russian personal income tax approximation used to bring "gross" RUB salaries to
# the market convention of quoting take-home ("на руки") pay.
RU_NET_FACTOR = 0.87
_RU_NET_CURRENCIES = {"RUB"}


def normalize(sal: Salary, rates_rub: dict[str, float]) -> tuple[float | None, float | None]:
    """Return (monthly take-home RUB mid, annual gross USD mid) for analytics.

    ``rates_rub`` maps currency -> RUB per unit (RUB itself maps to 1).
    """
    mid = sal.mid
    if not mid or not sal.currency or sal.currency not in rates_rub or "USD" not in rates_rub:
        return None, None
    rub_amount = mid * rates_rub[sal.currency]
    month_rub = rub_amount * _PERIOD_PER_MONTH.get(sal.period, 1.0)
    year_rub = rub_amount * _PERIOD_PER_YEAR.get(sal.period, 12.0)
    if sal.currency in _RU_NET_CURRENCIES and sal.gross is True:
        month_rub *= RU_NET_FACTOR
    if sal.currency in _RU_NET_CURRENCIES and sal.gross is False:
        year_rub /= RU_NET_FACTOR
    year_usd = year_rub / rates_rub["USD"]
    if not (5_000 <= month_rub <= 50_000_000):
        return None, None
    return round(month_rub, -2), round(year_usd, -2)


_SALARY_LINE = re.compile(r"[^\n]{0,80}(?:\d[\d  .,]*\s*(?:k|к|тыс|млн)?\s*(?:₽|руб|\$|€|£|usd|eur|rub|gbp|aed|₸|kzt)|(?:₽|\$|€|£|usd|eur|rub|gbp|aed)\s*\d)[^\n]{0,60}", re.IGNORECASE)


def find_salary_in_text(text: str, *, default_currency: str | None = None) -> tuple[Salary | None, str | None]:
    """Find the most salary-looking line in free text (Telegram posts, descriptions)."""
    if not text:
        return None, None
    candidates: list[str] = []
    for line in text.split("\n"):
        if SALARY_HINT.search(line) and re.search(r"\d", line):
            candidates.append(line)
    candidates += [m.group(0) for m in _SALARY_LINE.finditer(text)]
    for line in candidates:
        chunk = line.strip()[:200]
        hint = SALARY_HINT.search(chunk)
        if hint:
            chunk = chunk[hint.start():]
        sal = parse_salary(chunk, default_currency=default_currency if hint else None)
        if sal and sal.currency and (sal.mid or 0) >= 100:
            return sal, line.strip()
    return None, None
