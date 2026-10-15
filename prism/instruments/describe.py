"""Человекочитаемое описание сделки (для отчёта финансовому директору)."""
from __future__ import annotations

from ..instruments.schema import (AccrualMod, AutocallMod, AveragingMod, BarrierMod, CapFloorMod, Component,
                                  EarlyTerminationMod, ExerciseMod, LeverageMod, MemoryMod, StrikeResetMod, TargetMod, Trade)

KIND_RU = {
    "forward": "форвард", "call": "колл", "put": "пут", "digital_call": "цифровой колл", "digital_put": "цифровой пут",
    "range_digital": "диапазонный цифровой", "asset": "актив", "cash": "фиксированная выплата", "fixed": "фиксированная ставка",
    "fixed_compounded": "фиксированная ставка (сложный процент)", "float": "плавающая ставка", "cap": "кэп", "floor": "флор",
    "coupon": "купон", "redemption": "погашение номинала", "variance": "реализованная дисперсия", "volatility": "реализованная волатильность",
    "premium": "кредитная премия", "protection": "кредитная защита", "recovery": "восстановление", "index_ratio": "индексация",
}

PURPOSE_RU = {
    "buy_fx": "защита от роста курса (покупка валюты, импортёр)",
    "sell_fx": "защита от падения курса (продажа валюты, экспортёр)",
    "pay_floating": "защита заёмщика от роста плавающей ставки",
    "receive_floating": "защита от снижения плавающей ставки",
    "buy_commodity": "защита от роста цены товара (покупатель)",
    "sell_commodity": "защита от падения цены товара (производитель)",
    "investment": "инвестиционный продукт",
    "funding": "привлечение финансирования",
    "other": "не указано",
}


def _num(x) -> str:
    if x is None:
        return "—"
    if abs(x) < 1:
        return f"{x:.4%}" if abs(x) < 0.5 else f"{x:.4f}"
    return f"{x:,.4f}".rstrip("0").rstrip(".").replace(",", " ")


def _mod(m) -> str:
    if isinstance(m, BarrierMod):
        if m.lower is not None or m.upper is not None:
            lv = f"коридор {_num(m.lower)}–{_num(m.upper)}"
        else:
            lv = f"{'выше' if m.direction == 'up' else 'ниже'} {_num(m.level)}"
        mon = {"continuous": "непрерывное наблюдение", "discrete": f"дискретное наблюдение ({m.observation})",
               "terminal": "наблюдение только в дату фиксинга"}[m.monitoring]
        kind = "отключается (knock-out)" if m.kind == "out" else "включается (knock-in)"
        reb = f", ребейт {_num(m.rebate.amount)} ({'при касании' if m.rebate.timing == 'at_hit' else 'в конце'})" if m.rebate and m.rebate.amount else ""
        win = f", окно {m.window_start}–{m.window_end}" if m.window_start or m.window_end else ""
        soft = f", soft-полоса {m.soft_width}" if m.soft_width else ""
        return f"барьер: {kind} при касании уровня {lv}; {mon}{win}{reb}{soft}"
    if isinstance(m, AveragingMod):
        return f"усреднение ({'арифм.' if m.method == 'arithmetic' else 'геом.'}, по {'цене' if m.average_of == 'price' else 'страйку'})"
    if isinstance(m, TargetMod):
        lp = {"full": "полный последний платёж", "partial": "последний платёж до цели", "none": "без последнего платежа"}[m.last_payment]
        return f"целевое погашение при накопленной выгоде {m.level:g} ({lp})"
    if isinstance(m, LeverageMod):
        cond = {"always": "всегда", "below": f"если ниже {_num(m.threshold)}", "above": f"если выше {_num(m.threshold)}"}[m.when]
        return f"плечо ×{m.factor:g} ({cond})"
    if isinstance(m, AccrualMod):
        return f"начисление за дни в диапазоне {_num(m.lower)}–{_num(m.upper)}"
    if isinstance(m, AutocallMod):
        return f"автоколл при уровне ≥ {m.level if not isinstance(m.level, list) else m.level[0]:g}"
    if isinstance(m, CapFloorMod):
        parts = []
        for k, lbl in (("local_cap", "локальный кэп"), ("local_floor", "локальный флор"), ("global_cap", "глобальный кэп"),
                       ("global_floor", "глобальный флор")):
            v = getattr(m, k)
            if v is not None:
                parts.append(f"{lbl} {_num(v)}")
        return ", ".join(parts)
    if isinstance(m, StrikeResetMod):
        return f"переустановка страйка: {m.pct:.0%} от {'спота' if m.base == 'spot' else 'предыдущего фиксинга'} на начало периода"
    if isinstance(m, EarlyTerminationMod):
        return f"право досрочного прекращения у {'клиента' if m.holder == 'client' else 'банка'} ({len(m.dates)} дат)"
    if isinstance(m, ExerciseMod):
        return f"опцион на вход у {'клиента' if m.holder == 'client' else 'банка'} ({len(m.dates)} дат исполнения)"
    if isinstance(m, MemoryMod):
        return "купон с памятью"
    return m.type


def _comp(c: Component, unit: str) -> str:
    side = "клиент получает" if c.position == "long" else "клиент платит"
    s = f"{side}: {KIND_RU.get(c.kind, c.kind)}"
    if c.strike is not None:
        s += f", страйк {_num(c.strike)}"
    if c.rate is not None:
        s += f", ставка {_num(c.rate)}"
    if c.payout is not None and c.kind in ("cash", "digital_call", "digital_put", "range_digital", "redemption"):
        s += f", выплата {_num(c.payout)}{unit}"
    if c.notional_multiplier != 1:
        s += f", номинал ×{c.notional_multiplier:g}"
    if c.spread:
        s += f", спред {_num(c.spread)}"
    if c.modifiers:
        s += "; " + "; ".join(_mod(m) for m in c.modifiers)
    return s


def describe_trade(tr: Trade) -> dict:
    lines = []
    for leg in tr.legs:
        sched = leg.schedule
        if sched.dates:
            n = len(sched.dates)
            when = f"{n} фиксинг(ов) с {min(sched.dates)} по {max(sched.dates)}"
        else:
            when = f"с {sched.start or tr.start} по {sched.end}, частота {sched.frequency}"
        notional = f"{leg.notional.amount:,.0f} {leg.notional.currency}".replace(",", " ") if leg.notional else ""
        und = leg.underlying or ""
        uid = tr.underlyings[und].id if und in tr.underlyings else ""
        head = f"Нога «{leg.name}»: базис {uid or '—'}, {when}" + (f", номинал {notional} на период" if notional else "")
        comps = [_comp(c, "") for c in leg.components]
        mods = [_mod(m) for m in leg.modifiers]
        lines.append({"head": head, "components": comps, "modifiers": mods})
    struct = [_mod(m) for m in tr.modifiers]
    return {"product": tr.product, "purpose": PURPOSE_RU.get(tr.purpose.type, tr.purpose.type),
            "purpose_note": tr.purpose.description, "legs": lines, "structure": struct, "text": tr.description}
