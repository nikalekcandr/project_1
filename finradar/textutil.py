"""Text helpers: HTML to text, normalization, dates, language detection."""

from __future__ import annotations

import html
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

_WS = re.compile(r"[ \t   ]+")
_NL = re.compile(r"\n{3,}")


def clean_ws(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("\r", "")
    text = _WS.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _NL.sub("\n\n", text).strip()


def html_to_text(markup: str | None) -> str:
    """Convert an HTML fragment (possibly HTML-escaped, as Greenhouse returns it) to text."""
    if not markup:
        return ""
    if "&lt;" in markup and "<" not in markup:
        markup = html.unescape(markup)
    if "<" not in markup:
        return clean_ws(html.unescape(markup))
    soup = BeautifulSoup(markup, "lxml")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for tag in soup.find_all(["p", "li", "div", "h1", "h2", "h3", "h4", "tr"]):
        tag.insert_before("\n")
    for li in soup.find_all("li"):
        li.insert(0, "• ")
    return clean_ws(soup.get_text())


_KEY_DROP = re.compile(
    r"\((?:м/ж|ж/м|m/f|f/m|m/f/d|m/w/d|w/m/d|f/m/d|all genders)\)|\b(?:m/f/d|m/w/d)\b",
    re.IGNORECASE,
)
_NON_WORD = re.compile(r"[^\w+#&]+", re.UNICODE)


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def norm_key(text: str | None) -> str:
    """Aggressive normalization used for dedup keys and company matching."""
    if not text:
        return ""
    text = _KEY_DROP.sub(" ", text.lower().replace("ё", "е"))
    text = strip_accents(text)
    return _NON_WORD.sub(" ", text).strip()


_COMPANY_SUFFIX = re.compile(
    r"\b(?:ооо|оао|зао|пао|ао|ип|нко|llc|ltd|limited|inc|corp|corporation|plc|gmbh|ag|sa|s a|"
    r"bv|b v|nv|llp|lp|co|company|group|группа компаний|гк|holding|холдинг)\b",
    re.IGNORECASE,
)


def norm_company(name: str | None) -> str:
    key = norm_key(name)
    key = _COMPANY_SUFFIX.sub(" ", key)
    return re.sub(r"\s+", " ", key).strip()


_CYR = re.compile(r"[а-яё]", re.IGNORECASE)
_LAT = re.compile(r"[a-z]", re.IGNORECASE)


def detect_language(text: str) -> str | None:
    sample = text[:3000]
    cyr = len(_CYR.findall(sample))
    lat = len(_LAT.findall(sample))
    if cyr + lat < 10:
        return None
    return "ru" if cyr >= lat * 0.35 else "en"


_RU_MONTHS = {
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "мая": 5, "май": 5, "июн": 6,
    "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
}
_RU_DATE = re.compile(r"(\d{1,2})\s+([а-я]{3})[а-я]*\.?(?:\s+(\d{4}))?", re.IGNORECASE)
_DMY = re.compile(r"^(\d{1,2})[./](\d{1,2})[./](\d{2,4})")
_REL = re.compile(
    r"(\d+)\s*(minute|min|hour|hr|day|week|month|минут|час|дн|день|недел|месяц)",
    re.IGNORECASE,
)


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def parse_date(value, *, now: datetime | None = None) -> datetime | None:
    """Best-effort date parser for the zoo of formats job sites use."""
    if value is None or value == "":
        return None
    now = now or datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return _aware(value)
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e11:  # milliseconds
            ts /= 1000
        if ts <= 0:
            return None
        return datetime.fromtimestamp(ts, tz=timezone.utc).replace(microsecond=0)
    s = str(value).strip()
    if not s:
        return None
    if s.isdigit():
        return parse_date(int(s), now=now)
    iso = s.replace("Z", "+00:00")
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{4}$", iso):
        iso = iso[:-2] + ":" + iso[-2:]
    try:
        return _aware(datetime.fromisoformat(iso))
    except ValueError:
        pass
    try:
        return _aware(parsedate_to_datetime(s))
    except (TypeError, ValueError, IndexError):
        pass
    m = _DMY.match(s)
    if m:
        d, mo, y = (int(x) for x in m.groups())
        y = y + 2000 if y < 100 else y
        try:
            return datetime(y, mo, d, tzinfo=timezone.utc)
        except ValueError:
            return None
    low = s.lower()
    if re.search(r"\b(?:today|just now)\b|сегодня|только что", low):
        return _aware(now)
    if re.search(r"\byesterday\b|вчера", low):
        return _aware(now - timedelta(days=1))
    m = _RU_DATE.search(low)
    if m and m.group(2)[:3] in _RU_MONTHS:
        day, mon = int(m.group(1)), _RU_MONTHS[m.group(2)[:3]]
        year = int(m.group(3)) if m.group(3) else now.year
        try:
            dt = datetime(year, mon, day, tzinfo=timezone.utc)
        except ValueError:
            return None
        if not m.group(3) and dt > now + timedelta(days=2):
            dt = dt.replace(year=year - 1)
        return dt
    m = _REL.search(low)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        if unit.startswith(("min", "мин")):
            delta = timedelta(minutes=n)
        elif unit.startswith(("hour", "hr", "час")):
            delta = timedelta(hours=n)
        elif unit.startswith(("week", "недел")):
            delta = timedelta(weeks=n)
        elif unit.startswith(("month", "месяц")):
            delta = timedelta(days=30 * n)
        else:
            delta = timedelta(days=n)
        return _aware(now - delta)
    return None


def first_line(text: str, limit: int = 160) -> str:
    for line in text.split("\n"):
        line = line.strip(" -–—•*#:|")
        if line:
            return line[:limit]
    return ""


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
