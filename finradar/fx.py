"""Exchange rates used to bring salaries to comparable units.

Rates are "RUB per 1 unit of currency". Live rates come from the Bank of Russia
daily XML (no key required); the fallback table below is only a rough default
and can be overridden in ``sources.yaml`` (``fx.rates``).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from lxml import etree

if TYPE_CHECKING:
    from finradar.http import HttpClient
    from finradar.storage import Store

log = logging.getLogger(__name__)

CBR_URL = "https://www.cbr.ru/scripts/XML_daily.asp"

# Approximate fallback values, used only when live rates are unavailable.
FALLBACK_RATES_RUB: dict[str, float] = {
    "RUB": 1.0, "USD": 82.0, "EUR": 95.0, "GBP": 110.0, "CHF": 102.0, "CNY": 11.4,
    "KZT": 0.16, "BYN": 25.0, "UZS": 0.0065, "AMD": 0.21, "GEL": 30.0, "AED": 22.3,
    "SAR": 21.9, "TRY": 2.0, "INR": 0.95, "SGD": 63.0, "HKD": 10.5, "CAD": 59.0,
    "AUD": 54.0, "PLN": 22.0, "CZK": 3.8, "RSD": 0.81,
}


def parse_cbr_xml(content: bytes) -> dict[str, float]:
    root = etree.fromstring(content)
    rates: dict[str, float] = {"RUB": 1.0}
    for valute in root.findall("Valute"):
        code = valute.findtext("CharCode")
        nominal = valute.findtext("Nominal")
        value = valute.findtext("Value")
        if not (code and nominal and value):
            continue
        rates[code] = float(value.replace(",", ".")) / float(nominal.replace(",", "."))
    return rates


def load_rates(
    http: HttpClient | None,
    store: Store | None = None,
    overrides: dict[str, float] | None = None,
    live: bool = True,
) -> dict[str, float]:
    rates = dict(FALLBACK_RATES_RUB)
    cached = store.get_meta("fx_rates", max_age_hours=24) if store else None
    if cached:
        rates.update(cached)
    elif live and http is not None:
        try:
            resp = http.get(CBR_URL)
            fresh = parse_cbr_xml(resp.content)
            rates.update(fresh)
            if store:
                store.set_meta("fx_rates", fresh)
        except Exception as exc:  # network / parse problems must not break a run
            log.warning("FX: live rates unavailable (%s), using fallback table", exc)
    if overrides:
        rates.update({k.upper(): float(v) for k, v in overrides.items()})
    return rates
