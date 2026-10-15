"""Банк России: официальные курсы, ключевая ставка, RUONIA.

Официальный курс ЦБ устанавливается на следующий календарный день: курс
«на дату D» публикуется накануне. Это хранится в ``meta`` котировки и
учитывается при моделировании фиксингов.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, datetime

from ...core.provenance import DataKind, Provenance
from ..snapshot import Quote
from . import MSK, fetch

DAILY_URL = "https://www.cbr.ru/scripts/XML_daily.asp?date_req={d:%d/%m/%Y}"


def _num(s: str) -> float:
    return float(s.replace("\xa0", "").replace(" ", "").replace(",", "."))


def parse_xml_daily(xml: bytes | str, published_at: datetime | None = None) -> list[Quote]:
    root = ET.fromstring(xml)
    eff = datetime.strptime(root.attrib["Date"], "%d.%m.%Y").date()
    ts = published_at or datetime(eff.year, eff.month, eff.day, 0, 0, tzinfo=MSK)
    url = DAILY_URL.format(d=eff)
    out = []
    for v in root.findall("Valute"):
        code = v.findtext("CharCode")
        nominal = _num(v.findtext("Nominal") or "1")
        value = _num(v.findtext("Value")) / nominal
        out.append(Quote(f"FX.{code}RUB.FIX.CBR", value,
                         Provenance("Банк России: официальный курс", ts, DataKind.MARKET, url,
                                    note=f"курс установлен на {eff.isoformat()}"),
                         unit="price", meta={"effective_date": eff.isoformat(), "nominal": nominal}))
    return out


def fetch_official_rates(d: date) -> list[Quote]:
    return parse_xml_daily(fetch(DAILY_URL.format(d=d)))


def parse_key_rate_xml(xml: bytes | str) -> list[tuple[date, float]]:
    """Ответ DailyInfo.KeyRateXML: <KR><DT>…</DT><Rate>…</Rate></KR>."""
    root = ET.fromstring(xml)
    out = []
    for kr in root.iter("KR"):
        dt = datetime.fromisoformat(kr.findtext("DT")).date()
        out.append((dt, _num(kr.findtext("Rate")) / 100.0))
    return sorted(out)


def parse_ruonia_xml(xml: bytes | str) -> list[tuple[date, float]]:
    """Ответ DailyInfo.RuoniaXML: <ro><D0>…</D0><ruo>…</ruo></ro>."""
    root = ET.fromstring(xml)
    out = []
    for ro in root.iter("ro"):
        dt = datetime.fromisoformat(ro.findtext("D0")).date()
        out.append((dt, _num(ro.findtext("ruo")) / 100.0))
    return sorted(out)


def key_rate_quote(history: list[tuple[date, float]], as_of: datetime) -> Quote:
    d, r = [x for x in history if x[0] <= as_of.date()][-1]
    return Quote("RATE.RUB.KEYRATE", r,
                 Provenance("Банк России: ключевая ставка", datetime(d.year, d.month, d.day, tzinfo=MSK), DataKind.MARKET,
                            "https://www.cbr.ru/hd_base/KeyRate/"), unit="rate", meta={"effective_date": d.isoformat()})
