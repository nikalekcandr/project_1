"""Адаптеры публичных источников: Мосбиржа (ISS), Банк России, Росстат, раскрытие эмитентов.

Ограничение проекта: в систему попадают только данные публичных источников.
Каждый адаптер возвращает :class:`~prism.marketdata.snapshot.Quote` с
заполненным происхождением (источник, URL, время снятия).
"""
from __future__ import annotations

import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")

ALLOWED_PUBLIC_HOSTS = ("iss.moex.com", "www.moex.com", "moex.com", "www.cbr.ru", "cbr.ru", "rosstat.gov.ru",
                        "www.e-disclosure.ru", "e-disclosure.ru", "nfa.ru", "www.nfa.ru")


def fetch(url: str, timeout: float = 20.0) -> bytes:
    """Загрузка из публичного источника. Непубличные хосты запрещены на уровне кода."""
    host = url.split("/")[2].split(":")[0]
    if host not in ALLOWED_PUBLIC_HOSTS:
        raise PermissionError(f"источник {host} не входит в перечень публичных источников проекта")
    req = urllib.request.Request(url, headers={"User-Agent": "prism-otc/0.1 (independent valuation)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — хост проверен выше
        return r.read()


def now_msk() -> datetime:
    return datetime.now(MSK)
