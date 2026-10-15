"""МСФО (IFRS) 9: выделение встроенного дериватива и раскрытие.

Для гибридного договора определяется, отделяется ли встроенный дериватив
(п. 4.3.3) и является ли он тесно связанным с основным договором
(Приложение B, пп. B4.3.5, B4.3.8). Результат — структура для раскрытия:
описание, обоснование со ссылками на пункты, справедливая стоимость
встроенного дериватива, уровень иерархии справедливой стоимости.

Оценка «тесной связи» требует профессионального суждения; модуль формирует
обоснованный проект вывода и явно помечает пункты, требующие проверки.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..instruments.schema import BarrierMod, LeverageMod, Trade


@dataclass
class IFRS9Assessment:
    host_type: str
    separate: bool
    closely_related: bool
    rationale: list[str]
    paragraphs: list[str]
    fair_value: float
    fair_value_level: int
    valuation_technique: str
    key_inputs: list[str]
    judgement_required: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _leveraged(tr: Trade) -> bool:
    for leg in tr.legs:
        for c in leg.components:
            if c.notional_multiplier > 1.0 + 1e-12 or abs(c.gearing) > 1.0 + 1e-12:
                return True
            if any(isinstance(m, LeverageMod) and m.factor > 1 for m in c.modifiers):
                return True
    return False


def assess_embedded(derivative: Trade, host_type: str, *, fair_value: float, model_based_inputs: list[str],
                    market_rate_at_inception: float | None = None, functional_currency: str = "RUB",
                    host_goods_currency: str | None = None, engine: str = "") -> IFRS9Assessment:
    """host_type: 'financial_liability' (кредит у заёмщика), 'financial_asset' (депозит/нота у инвестора),
    'non_financial' (договор поставки), 'lease'."""
    rationale: list[str] = []
    paras: list[str] = []
    judgement: list[str] = []
    classes = derivative.asset_classes
    lev = _leveraged(derivative)
    has_option = any(c.kind in ("call", "put", "cap", "floor", "digital_call", "digital_put") for l in derivative.legs for c in l.components)
    if host_type == "financial_asset":
        rationale.append("Основной договор — финансовый актив в сфере применения МСФО 9: встроенный дериватив не "
                         "отделяется, классификация гибридного инструмента целиком определяется тестом SPPI "
                         "(как правило — ССЧПУ при наличии выплат, не являющихся только основным долгом и процентами).")
        paras += ["4.3.2", "4.1.2(b)", "B4.1.7"]
        separate, cr = False, True
    else:
        cr = True
        if "rate" in classes:
            caps = [c for l in derivative.legs for c in l.components if c.kind in ("cap", "floor")]
            if lev:
                cr = False
                rationale.append("Процентная составляющая с плечом: не тесно связана (B4.3.8(a)).")
                paras.append("B4.3.8(a)")
            for c in caps:
                if market_rate_at_inception is None:
                    judgement.append("Нужна рыночная ставка на дату заключения для сравнения со страйком кэпа/флора")
                    continue
                if c.kind == "cap" and c.position == "short" and c.strike < market_rate_at_inception:
                    pass
                if (c.kind == "cap" and c.strike >= market_rate_at_inception) or (c.kind == "floor" and c.strike <= market_rate_at_inception):
                    rationale.append(f"{'Кэп' if c.kind == 'cap' else 'Флор'} {c.strike:.2%} вне денег на дату заключения "
                                     f"(рыночная ставка {market_rate_at_inception:.2%}) и без плеча — тесно связан (B4.3.8(b)).")
                else:
                    cr = False
                    rationale.append(f"{'Кэп' if c.kind == 'cap' else 'Флор'} {c.strike:.2%} в деньгах на дату заключения "
                                     f"(рыночная ставка {market_rate_at_inception:.2%}) — не тесно связан (B4.3.8(b)).")
                paras.append("B4.3.8(b)")
            if any(isinstance(m, BarrierMod) for l in derivative.legs for c in l.components for m in c.modifiers):
                cr = False
                rationale.append("Барьерное условие (отключение защиты) изменяет денежные потоки нелинейно — "
                                 "не является простым кэпом/флором; не тесно связан.")
                judgement.append("Проверить формулировку барьерного условия в договоре")
        if "fx" in classes:
            if host_type == "non_financial":
                ccy = {u.id[:3] for u in derivative.underlyings.values() if u.asset_class == "fx"}
                if lev or has_option:
                    cr = False
                    rationale.append("Валютная оговорка содержит опционный элемент или плечо — не тесно связана (B4.3.8(d)).")
                elif ccy <= {functional_currency, host_goods_currency or ""}:
                    rationale.append("Платежи в функциональной валюте стороны или в валюте, в которой товар обычно "
                                     "номинирован в международной торговле, без плеча и опционов — тесно связана (B4.3.8(d)).")
                else:
                    cr = False
                    rationale.append("Валюта платежей не является функциональной валютой сторон и не типична для товара — "
                                     "не тесно связана (B4.3.8(d)).")
                    judgement.append("Подтвердить, является ли валюта «обычно используемой» в экономической среде (B4.3.8(d)(iii))")
                paras.append("B4.3.8(d)")
            else:
                cr = False
                rationale.append("Валютная составляющая в рублёвом финансовом обязательстве (индексация на курс) — "
                                 "не тесно связана с основным долговым договором (B4.3.5).")
                paras.append("B4.3.5")
        if "inflation" in classes:
            if lev:
                cr = False
                rationale.append("Инфляционная индексация с плечом — не тесно связана (B4.3.8(f)).")
            else:
                rationale.append("Индексация на ИПЦ собственной экономической среды без плеча — тесно связана (B4.3.8(f)).")
            paras.append("B4.3.8(f)")
        if classes & {"equity", "commodity", "credit", "volatility"}:
            cr = False
            rationale.append("Выплата зависит от цены акций/товаров/кредитного события — не тесно связана с долговым "
                             "основным договором (B4.3.5(c)–(f)).")
            paras.append("B4.3.5")
        separate = not cr
        paras.append("4.3.3")
        rationale.append("Отделение требуется, так как встроенный дериватив не тесно связан, гибридный договор не "
                         "оценивается по ССЧПУ, и отдельный инструмент с теми же условиями был бы деривативом (4.3.3)."
                         if separate else "Встроенный дериватив тесно связан с основным договором — не отделяется (4.3.3(a)).")
    level = 3 if model_based_inputs else 2
    return IFRS9Assessment(host_type, separate, cr, rationale, sorted(set(paras)), fair_value, level,
                           engine or "модель оценки", model_based_inputs, judgement)
