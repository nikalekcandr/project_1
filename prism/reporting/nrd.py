"""Поля для сверки с записью в репозитарии НРД.

Набор полей, достаточный для сверки параметров сделки с репозитарной
записью. Это не официальный формат сообщения репозитарию — только данные
для сопоставления.
"""
from __future__ import annotations

from typing import Any

from ..instruments.schema import Trade


def _product_class(tr: Trade) -> str:
    kinds = {c.kind for l in tr.legs for c in l.components}
    classes = tr.asset_classes
    mods = tr.modifier_types()
    if "rate" in classes:
        if kinds <= {"fixed", "float"}:
            return "Процентный своп" if "exercise" not in mods else "Свопцион"
        if kinds & {"cap", "floor"}:
            return "Процентный опцион (кэп/флор)"
        return "Процентный ПФИ (структура)"
    if "fx" in classes:
        if kinds <= {"forward"} and not mods:
            return "Валютный форвард"
        if kinds & {"call", "put", "digital_call", "digital_put", "cash"}:
            return "Валютный опцион / структура"
        return "Валютный ПФИ (структура)"
    if "commodity" in classes:
        return "Товарный своп" if kinds <= {"forward"} else "Товарный опцион / структура"
    if "inflation" in classes:
        return "Инфляционный своп"
    if "credit" in classes:
        return "Кредитный дефолтный своп / CLN"
    if "equity" in classes:
        return "ПФИ на акции / индекс"
    return "Иной ПФИ"


def nrd_fields(tr: Trade, valuation: float | None = None, valuation_date: str | None = None) -> dict[str, Any]:
    idn = tr.identification
    leg = max(tr.legs, key=lambda l: len(l.components))
    strikes = sorted({c.strike for l in tr.legs for c in l.components if c.strike is not None})
    rates = sorted({c.rate for l in tr.legs for c in l.components if c.rate is not None})
    return {
        "UTI": idn.uti or "",
        "Тип ПФИ": _product_class(tr),
        "Наименование": tr.product,
        "Дата заключения": idn.trade_date.isoformat(),
        "Дата начала": (idn.effective_date or idn.trade_date).isoformat(),
        "Дата окончания": tr.maturity.isoformat(),
        "Сторона 1 (клиент)": idn.client + (f", ИНН {idn.client_inn}" if idn.client_inn else ""),
        "Сторона 2 (банк)": idn.bank + (f", ИНН {idn.bank_inn}" if idn.bank_inn else ""),
        "Генеральное соглашение": idn.master_agreement.type,
        "Регистрация в репозитарии (для неттинга)": "да" if idn.master_agreement.registered_in_repository else "нет",
        "Базисный актив": ", ".join(f"{u.id} ({u.asset_class})" for u in tr.underlyings.values()),
        "Источник фиксинга": ", ".join(sorted({u.fixing.source for u in tr.underlyings.values()})),
        "Номинал": f"{leg.notional.amount:,.2f} {leg.notional.currency}" if leg.notional else "",
        "Страйк(и)": ", ".join(f"{s:g}" for s in strikes),
        "Фиксированная ставка": ", ".join(f"{r:.4%}" for r in rates),
        "Тип расчётов": tr.settlement.type,
        "Валюта расчётов": tr.settlement.currency,
        "Режим обеспечения": tr.collateral.regime,
        "Число периодов": sum(1 for l in tr.legs for _ in (l.schedule.dates or [0])),
        "Оценка (клиент), руб.": None if valuation is None else round(valuation, 2),
        "Дата оценки": valuation_date,
        "_примечание": "набор полей для сверки с репозитарной записью; не является форматом сообщения НРД",
    }
