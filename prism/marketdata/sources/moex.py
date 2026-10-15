"""Мосбиржа: ISS API (iss.moex.com).

Парсеры принимают JSON ответа ISS (формат «columns/data») и возвращают
котировки с происхождением. Сетевые функции ``fetch_*`` — тонкие обёртки.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ...core.provenance import DataKind, Provenance
from ..snapshot import Quote
from . import MSK, fetch

ISS = "https://iss.moex.com/iss"


def iss_table(payload: dict | str | bytes, block: str) -> list[dict[str, Any]]:
    if isinstance(payload, (str, bytes)):
        payload = json.loads(payload)
    b = payload[block]
    cols = b["columns"]
    return [dict(zip(cols, row)) for row in b["data"]]


def _ts(date_s: str, time_s: str | None) -> datetime:
    t = (time_s or "18:45:00")[:8]
    return datetime.fromisoformat(f"{date_s[:10]}T{t}").replace(tzinfo=MSK)


# --------------------------------------------------------------- КБД (ZCYC)
ZCYC_URL = ISS + "/engines/stock/zcyc.json?iss.only=params"


def parse_zcyc_params(payload) -> Quote:
    """Параметры кривой бескупонной доходности ОФЗ (Нельсон-Сигель-Свенссон + G-поправки)."""
    rows = iss_table(payload, "params")
    if not rows:
        raise ValueError("ISS zcyc: пустой блок params")
    r = rows[-1]
    params = {k: float(r[k]) for k in ("B1", "B2", "B3", "T1") if r.get(k) is not None}
    params.update({f"G{i}": float(r.get(f"G{i}") or 0.0) for i in range(1, 10)})
    ts = _ts(r["tradedate"], r.get("tradetime"))
    return Quote("CURVE.RUB.KBD", params, Provenance("Мосбиржа: КБД ОФЗ (параметры NSS)", ts, DataKind.MARKET, ZCYC_URL),
                 unit="nss_params_bp")


def fetch_zcyc() -> Quote:
    return parse_zcyc_params(fetch(ZCYC_URL))


# --------------------------------------------------------------- RUSFAR
RUSFAR_CODES = {"RUSFAR": "ON", "RUSFAR1W": "1W", "RUSFAR2W": "2W", "RUSFAR1M": "1M", "RUSFAR3M": "3M"}
RUSFAR_URL = ISS + "/engines/stock/markets/index/securities.json?securities=" + ",".join(RUSFAR_CODES)


def parse_rusfar(payload) -> list[Quote]:
    rows = iss_table(payload, "marketdata")
    out = []
    for r in rows:
        code = r.get("SECID")
        if code not in RUSFAR_CODES or r.get("CURRENTVALUE") is None:
            continue
        ts = _ts(r.get("TRADEDATE") or r.get("SYSTIME", "")[:10], r.get("TIME"))
        tenor = RUSFAR_CODES[code]
        out.append(Quote(f"RATE.RUB.RUSFAR.{tenor}", float(r["CURRENTVALUE"]) / 100.0,
                         Provenance(f"Мосбиржа: индикатор {code}", ts, DataKind.MARKET, RUSFAR_URL),
                         unit="rate", meta={"tenor": tenor, "daycount": "ACT/365F"}))
    return out


# --------------------------------------------------------------- валюта TOM
def fx_tom_url(secid: str) -> str:
    return f"{ISS}/engines/currency/markets/selt/boards/CETS/securities/{secid}.json?iss.only=marketdata"


def parse_fx_tom(payload, pair: str, secid: str) -> Quote:
    r = iss_table(payload, "marketdata")[0]
    last = r.get("LAST") or r.get("WAPRICE")
    ts = _ts(r.get("TRADEDATE") or r.get("SYSTIME", "")[:10], r.get("UPDATETIME") or r.get("TIME"))
    return Quote(f"FX.{pair}.SPOT", float(last), Provenance(f"Мосбиржа: {secid}, режим CETS", ts, DataKind.MARKET, fx_tom_url(secid)),
                 unit="price", bid=r.get("BID"), ask=r.get("OFFER"), meta={"settlement": "TOM"})


# --------------------------------------------------------------- фиксинги
FIXING_URL = ISS + "/statistics/engines/currency/markets/fixing.json"


def parse_fixings(payload) -> list[Quote]:
    """Валютные фиксинги Мосбиржи (USDFIXME, EURFIXME, CNYFIXME...)."""
    out = []
    for r in iss_table(payload, "history" if "history" in (json.loads(payload) if isinstance(payload, (str, bytes)) else payload) else "securities"):
        sec = r.get("SECID", "")
        if not sec.endswith("FIXME") or r.get("RATE") is None:
            continue
        pair = sec[:3] + "RUB"
        ts = _ts(r["TRADEDATE"], r.get("TRADETIME"))
        out.append(Quote(f"FX.{pair}.FIX.MOEX", float(r["RATE"]), Provenance(f"Мосбиржа: фиксинг {sec}", ts, DataKind.MARKET, FIXING_URL),
                         unit="price", meta={"fixing_date": r["TRADEDATE"]}))
    return out
