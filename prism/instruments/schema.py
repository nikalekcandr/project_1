"""Схема представления сделки (версионируемая, сериализуемая, самодостаточная).

Единая модель данных для всех классов активов. По ней одной вместе со
снапшотом рынка оценка воспроизводится полностью.

Покрытие задаётся произведением трёх измерений:
**базовый актив × форма выплаты × модификаторы**. Сделка — набор ног; нога —
расписание периодов, наблюдаемая величина и компоненты выплаты; к
компоненту, ноге или всей сделке применяются модификаторы. Новая структура
из термшита собирается конфигурацией, без нового кода движка.

Все потоки — с точки зрения КЛИЕНТА: ``position: long`` — клиент получает
выплату компонента, ``short`` — платит.

Ссылки на термшит: любое скалярное поле в YAML/JSON можно задать как
``{value: 95.5, ref: "п. 4.1, стр. 3"}`` — значение подставится, а ссылка
сохранится в ``termsheet_refs`` по JSON-пути поля.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import date
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

TRADE_SCHEMA_VERSION = "1.1"


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# --------------------------------------------------------------------------- идентификация
class MasterAgreement(_M):
    """Генеральное соглашение. Российские (НФА, НАУФОР, АРБ) отличаются от ISDA
    процедурой ликвидационного неттинга и определением сумм при досрочном
    прекращении."""
    type: Literal["RU_NFA", "RU_NAUFOR", "RU_ARB", "ISDA", "NONE"] = "RU_NFA"
    version: str | None = None
    close_out_netting: bool = True
    registered_in_repository: bool = True   # ст. 4.1 127-ФЗ: ликвидационный неттинг — при информации в репозитарии
    close_out_method: Literal["market_quotation", "loss", "close_out_amount", "ru_standard"] = "ru_standard"
    set_off_unpaid: bool = True


class Identification(_M):
    trade_id: str
    client: str                      # id контрагента-клиента (карточка в датасете credit_entities)
    bank: str = "BANK"
    trade_date: date
    effective_date: date | None = None
    master_agreement: MasterAgreement = Field(default_factory=MasterAgreement)
    netting_set: str | None = None
    termsheet: str | None = None
    confirmation: str | None = None
    uti: str | None = None           # идентификатор в репозитарии НРД
    client_inn: str | None = None
    bank_inn: str | None = None


class Purpose(_M):
    """Экономическое назначение — нужно для подбора ванильной альтернативы и
    профиля «защищает / не защищает»."""
    type: Literal["buy_fx", "sell_fx", "pay_floating", "receive_floating", "buy_commodity", "sell_commodity",
                  "investment", "funding", "other"] = "other"
    underlying: str | None = None
    exposure_notional: float | None = None     # объём реальной позиции клиента (в единицах базиса)
    horizon: date | None = None
    budget_rate: float | None = None           # бюджетный курс/ставка клиента
    description: str = ""


# --------------------------------------------------------------------------- базис
class FixingSpec(_M):
    source: str = "MARKET"           # CBR, MOEX, LME, PLATTS, ... — в контракте, не взаимозаменяемы
    time: str | None = None
    lag_days: int = 0                # лаг публикации (курс ЦБ на дату D устанавливается накануне: −1)
    calendar: str | None = None


class DividendSpec(_M):
    ex_date: date
    amount: float


class UnderlyingSpec(_M):
    asset_class: Literal["fx", "rate", "inflation", "commodity", "equity", "credit", "volatility"]
    id: str                          # USDRUB, KEYRATE, RU.CPI, BRENT, SBER, ...
    price_source: str | None = None
    fixing: FixingSpec = Field(default_factory=FixingSpec)
    unit: str | None = None
    unit_conversion: float | None = None    # множитель пересчёта единиц из термшита (например, bbl/t)
    dividends_override: list[DividendSpec] | None = None
    contract_month: str | None = None       # для товаров: конкретный месяц поставки 'YYYY-MM'
    tradeable_hedge: bool | None = None     # переопределение признака наличия хеджа


# --------------------------------------------------------------------------- номинал и расписания
class NotionalStep(_M):
    date: date
    amount: float


class NotionalSpec(_M):
    currency: str = "RUB"
    amount: float
    schedule: list[NotionalStep] | None = None   # амортизация/accreting/roller-coaster: номинал с даты


class ScheduleSpec(_M):
    start: date | None = None
    end: date | None = None
    frequency: str = "once"          # 'once', '1M', '3M', '1Y', 'daily', '1W'
    calendar: str = "RU"
    bdc: Literal["following", "modified_following", "preceding", "modified_preceding", "unadjusted"] = "modified_following"
    backward: bool = True
    eom: bool = False
    daycount: str = "ACT/365F"
    fixing_lag: int = 0
    fixing_in_arrears: bool = True
    fixing_calendar: str | None = None
    payment_lag: int = 0
    payment_calendar: str | None = None
    observation: str | None = None   # подрасписание наблюдений: 'daily', '1W'
    dates: list[date] | None = None          # явные даты фиксингов
    payment_dates: list[date] | None = None  # явные даты платежей
    weights: list[float] | None = None       # веса периодов (например, для неравных объёмов)


# --------------------------------------------------------------------------- наблюдаемые
class AssetObs(_M):
    type: Literal["asset"] = "asset"
    name: str


class PerformanceObs(_M):
    type: Literal["performance"] = "performance"
    name: str
    initial: float | None = None     # начальный уровень; None — фиксинг на дату начала


class BasketObs(_M):
    type: Literal["basket"] = "basket"
    names: list[str]
    weights: list[float] | None = None
    rule: Literal["sum", "worst_of", "best_of", "rainbow"] = "sum"
    rank_weights: list[float] | None = None    # для rainbow: веса по рангу
    performance: bool = True                   # нормировать на начальные уровни
    initials: list[float] | None = None


class SpreadObs(_M):
    """Линейная комбинация базисов: Σ coef_i·X_i (Urals − Brent, crack spread)."""
    type: Literal["spread"] = "spread"
    terms: list[dict[str, Any]]          # [{name: A, coef: 1.0}, {name: B, coef: -1.0}]


class RateObs(_M):
    type: Literal["rate"] = "rate"
    index: str                           # KEYRATE, RUONIA, RUSFAR3M, SOFR, ...
    compounding: Literal["compounded", "simple_average", "term", "point", "default"] = "default"
    lookback_days: int = 0
    lockout_days: int = 0
    tenor: str | None = None             # для CMS: срок свопа
    cms: bool = False


class CPIObs(_M):
    type: Literal["cpi"] = "cpi"
    name: str = "RU.CPI"
    lag_months: int = 3
    interpolate: bool = False
    version: Literal["first", "revised"] = "revised"
    measure: Literal["ratio_to_base", "yoy"] = "ratio_to_base"
    base_index: float | None = None


class RealizedVarObs(_M):
    type: Literal["realized_variance", "realized_vol"] = "realized_variance"
    name: str
    annualization: float = 252.0


class CreditObs(_M):
    type: Literal["credit"] = "credit"
    entity: str
    recovery: float | None = None


class WeatherObs(_M):
    """Погодный индекс (HDD/CDD) — оценка актуарная, по исторической статистике."""
    type: Literal["weather"] = "weather"
    dataset: str
    detrend: bool = True


Observable = Annotated[Union[AssetObs, PerformanceObs, BasketObs, SpreadObs, RateObs, CPIObs, RealizedVarObs,
                             CreditObs, WeatherObs], Field(discriminator="type")]


# --------------------------------------------------------------------------- модификаторы
class Rebate(_M):
    amount: float = 0.0
    timing: Literal["at_hit", "at_expiry"] = "at_expiry"


class BarrierMod(_M):
    """Барьер. Режим наблюдения обязателен: дискретное наблюдение без сдвига
    барьера завышает цену."""
    type: Literal["barrier"] = "barrier"
    kind: Literal["in", "out"] = "out"
    direction: Literal["up", "down"] | None = None    # для одиночного
    level: float | None = None
    lower: float | None = None                         # для двойного
    upper: float | None = None
    monitoring: Literal["continuous", "discrete", "terminal"] = "continuous"
    observation: str = "daily"                         # для discrete: 'daily', '1W', 'fixings'
    window_start: date | None = None
    window_end: date | None = None
    scope: Literal["trade", "period"] = "trade"        # окно по умолчанию: с начала сделки / с начала периода
    rebate: Rebate | None = None
    soft_width: float | None = None                    # soft barrier: линейное частичное срабатывание в полосе
    observable: Observable | None = None               # наблюдаемая для барьера (по умолчанию — наблюдаемая ноги)


class AveragingMod(_M):
    type: Literal["averaging"] = "averaging"
    method: Literal["arithmetic", "geometric"] = "arithmetic"
    average_of: Literal["price", "strike"] = "price"   # (не «on»: в YAML 1.1 это булево значение)
    frequency: str | None = None       # если не задано — наблюдения расписания ноги
    weights: list[float] | None = None
    missing: Literal["skip", "previous", "next"] = "previous"


class AutocallMod(_M):
    type: Literal["autocall"] = "autocall"
    dates: list[date] | None = None     # по умолчанию — даты фиксингов ноги
    level: float | list[float] = 1.0     # барьер автоколла (в единицах наблюдаемой, обычно доля от начального)
    redemption: float = 1.0              # выплата при автоколле, доля номинала
    leg: str | None = None               # нога, по наблюдаемой которой проверяется условие
    first_date_index: int = 0            # с какого наблюдения возможен автоколл


class AccrualMod(_M):
    """Накопление: доля дней наблюдения в диапазоне."""
    type: Literal["accrual"] = "accrual"
    lower: float | None = None
    upper: float | None = None
    holiday_rule: Literal["previous", "skip"] = "previous"
    proportion: Literal["days", "observations"] = "observations"
    observable: Observable | None = None


class TargetMod(_M):
    """Целевое погашение (TARF): по достижении накопленной суммы — досрочное прекращение."""
    type: Literal["target"] = "target"
    level: float
    measure: Literal["gain_per_unit", "gain_cash", "itm_count"] = "gain_per_unit"
    last_payment: Literal["full", "partial", "none"] = "partial"


class LeverageMod(_M):
    """Плечо: множитель номинала компонента при выполнении условия на наблюдаемую."""
    type: Literal["leverage"] = "leverage"
    factor: float
    when: Literal["below", "above", "always"] = "always"
    threshold: float | None = None


class CapFloorMod(_M):
    """Кэпы и флоры на выплату: локальные (по периоду) и глобальные (по сделке) не коммутируют."""
    type: Literal["cap_floor"] = "cap_floor"
    local_cap: float | None = None
    local_floor: float | None = None
    global_cap: float | None = None
    global_floor: float | None = None
    unit: Literal["rate", "amount"] = "rate"


class StrikeResetMod(_M):
    """Переустановка страйка (cliquet / forward start): страйк = pct × база на начало периода."""
    type: Literal["strike_reset"] = "strike_reset"
    base: Literal["spot", "previous_fixing"] = "spot"
    pct: float = 1.0


class EarlyTerminationMod(_M):
    """Право досрочного прекращения (бермудское расписание → обратная индукция / LSMC)."""
    type: Literal["early_termination"] = "early_termination"
    holder: Literal["client", "bank"] = "bank"
    dates: list[date]
    amount: float = 0.0                 # сумма, выплачиваемая клиенту при прекращении (в валюте отчёта)
    amount_type: Literal["fixed", "par"] = "fixed"
    notice_days: int = 0


class ExerciseMod(_M):
    """Опцион на вход в структуру (свопцион): при исполнении в дату T_i клиент
    получает потоки периодов, начинающихся не раньше T_i. Европейский — одна дата."""
    type: Literal["exercise"] = "exercise"
    dates: list[date]
    holder: Literal["client", "bank"] = "client"
    settlement: Literal["physical", "cash"] = "physical"


class MemoryMod(_M):
    """Память купона: неоплаченные купоны выплачиваются при следующем срабатывании."""
    type: Literal["memory"] = "memory"


Modifier = Annotated[Union[BarrierMod, AveragingMod, AutocallMod, AccrualMod, TargetMod, LeverageMod, CapFloorMod,
                           StrikeResetMod, EarlyTerminationMod, ExerciseMod, MemoryMod], Field(discriminator="type")]


# --------------------------------------------------------------------------- компоненты и ноги
ComponentKind = Literal[
    "forward",        # X − K
    "call", "put",    # (X − K)+, (K − X)+
    "digital_call", "digital_put",   # payout · 1{X > K}, payout · 1{X < K}
    "range_digital",  # payout · 1{lower ≤ X ≤ upper}
    "asset",          # X
    "cash",           # фиксированная выплата payout (с барьером — one-touch / no-touch)
    "fixed",          # rate · τ
    "fixed_compounded",  # (1 + rate)^τ − 1 (фиксированная нога инфляционного свопа)
    "float",          # (gearing·X + spread) · τ  — плавающая ставка
    "cap", "floor",   # (X − K)+·τ, (K − X)+·τ — каплет/флорлет
    "coupon",         # купон rate (за период), обычно с условием (digital/accrual) и памятью
    "redemption",     # погашение номинала: payout (по умолчанию 1)
    "variance",       # реализованная дисперсия − K (вариансный своп)
    "volatility",     # реализованная волатильность − K
    "premium",        # кредитная премия: rate · τ при выживании референсного лица
    "protection",     # защита: (1 − R) при дефолте в периоде
    "recovery",       # выплата R·номинал при дефолте (CLN)
    "index_ratio",    # X / X_база − 1 (инфляционная нога ZCIS, индексация)
]


class Component(_M):
    kind: ComponentKind
    position: Literal["long", "short"] = "long"
    strike: float | None = None
    lower: float | None = None
    upper: float | None = None
    payout: float | None = None
    rate: float | None = None
    spread: float = 0.0
    gearing: float = 1.0
    notional_multiplier: float = 1.0      # плечо/асимметрия номинала
    cap_strike: float | None = None       # потолок для call (call spread / ограниченное участие)
    modifiers: list[Modifier] = Field(default_factory=list)
    label: str = ""


class Quanto(_M):
    """Квантование: quanto фиксирует курс, composite — пересчёт по текущему курсу. Это разные цены."""
    type: Literal["quanto", "composite"] = "composite"
    pair: str                              # курс пересчёта (например, USDRUB)
    rate: float | None = None              # фиксированный курс для quanto
    fixing_source: str = "CBR"


class SettlementSpec(_M):
    type: Literal["physical", "cash"] = "cash"
    currency: str = "RUB"
    quanto: Quanto | None = None
    fixing_source: str | None = None
    lag_days: int = 0


class Leg(_M):
    name: str = "leg"
    underlying: str | None = None          # ключ в Trade.underlyings
    observable: Observable | None = None
    schedule: ScheduleSpec
    notional: NotionalSpec | None = None
    currency: str | None = None            # валюта выплат ноги (до квантования)
    components: list[Component]
    modifiers: list[Modifier] = Field(default_factory=list)
    settlement: SettlementSpec | None = None
    exchange_notional: Literal["none", "initial", "final", "both"] = "none"
    notional_reset: bool = False           # MtM CCS: ресет номинала по курсу на начало периода
    reset_pair: str | None = None


# --------------------------------------------------------------------------- прочие блоки
class Collateral(_M):
    regime: Literal["none", "one_way_client", "one_way_bank", "two_way"] = "none"
    threshold_client: float = 0.0          # порог для взноса клиентом
    threshold_bank: float = 0.0
    mta: float = 0.0
    currency: str = "RUB"
    rate_index: str | None = "RUSFAR"
    mpor_days: int = 10
    independent_amount: float = 0.0

    @property
    def collateralized(self) -> bool:
        return self.regime == "two_way" and self.threshold_client == 0 and self.threshold_bank == 0


class EarlyTermination(_M):
    holder: Literal["client", "bank", "both"] = "bank"
    dates: list[date] = Field(default_factory=list)
    triggers: list[str] = Field(default_factory=list)
    formula: str = "fixed_amount"
    amount: float = 0.0


class LinkedTrade(_M):
    trade_id: str
    relation: Literal["loan", "deposit", "hedge", "condition_precedent", "package_member", "host_contract", "other"] = "package_member"
    description: str = ""


class Premium(_M):
    amount: float = 0.0
    currency: str = "RUB"
    payment_date: date | None = None
    payer: Literal["client", "bank"] = "client"
    unit: Literal["absolute", "pct_notional", "per_unit"] = "absolute"


class TradeState(_M):
    """Состояние сезонной сделки для непрерывно наблюдаемых событий."""
    knocked: dict[str, bool] = Field(default_factory=dict)     # метка барьера -> сработал
    accumulated_target: float = 0.0
    autocalled: bool = False
    unpaid_coupons: float = 0.0


class ModelChoice(_M):
    engine: Literal["auto", "analytic", "mc", "pde", "tree"] = "auto"
    vol_model: Literal["auto", "black", "local_vol", "vanna_volga"] = "auto"
    paths: int = 40000
    seed: int = 20261015
    antithetic: bool = True
    time_steps_per_year: int = 252
    target_stderr_bp: float | None = None    # остановка по точности (б.п. номинала)
    greeks: Literal["auto", "pathwise", "lr", "bump"] = "auto"
    discount_override: str | None = None


class Trade(_M):
    schema_version: str = TRADE_SCHEMA_VERSION
    identification: Identification
    product: str
    product_type: str | None = None
    description: str = ""
    purpose: Purpose = Field(default_factory=Purpose)
    underlyings: dict[str, UnderlyingSpec] = Field(default_factory=dict)
    legs: list[Leg]
    modifiers: list[Modifier] = Field(default_factory=list)
    settlement: SettlementSpec = Field(default_factory=SettlementSpec)
    collateral: Collateral = Field(default_factory=Collateral)
    early_termination: EarlyTermination | None = None
    linked_trades: list[LinkedTrade] = Field(default_factory=list)
    premium: Premium | None = None
    state: TradeState = Field(default_factory=TradeState)
    model: ModelChoice = Field(default_factory=ModelChoice)
    report_currency: str = "RUB"
    termsheet_refs: dict[str, str] = Field(default_factory=dict)
    tags: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _extract_refs(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        refs: dict[str, str] = dict(data.get("termsheet_refs") or {})

        def walk(obj: Any, path: str) -> Any:
            if isinstance(obj, dict):
                if set(obj.keys()) <= {"value", "ref"} and "value" in obj and "ref" in obj:
                    refs[path] = str(obj["ref"])
                    return walk(obj["value"], path)
                return {k: walk(v, f"{path}.{k}" if path else k) for k, v in obj.items()}
            if isinstance(obj, list):
                return [walk(v, f"{path}[{i}]") for i, v in enumerate(obj)]
            return obj

        out = walk({k: v for k, v in data.items() if k != "termsheet_refs"}, "")
        out["termsheet_refs"] = refs
        return out

    # ------------------------------------------------------------------ utils
    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    def content_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def maturity(self) -> date:
        ends = []
        for leg in self.legs:
            s = leg.schedule
            if s.payment_dates:
                ends.append(max(s.payment_dates))
            elif s.dates:
                ends.append(max(s.dates))
            elif s.end:
                ends.append(s.end)
        return max(ends)

    @property
    def start(self) -> date:
        return self.identification.effective_date or self.identification.trade_date

    @property
    def asset_classes(self) -> set[str]:
        return {u.asset_class for u in self.underlyings.values()}

    def modifier_types(self) -> set[str]:
        out = {m.type for m in self.modifiers}
        for leg in self.legs:
            out |= {m.type for m in leg.modifiers}
            for c in leg.components:
                out |= {m.type for m in c.modifiers}
        return out

    def copy_with(self, **updates) -> "Trade":
        d = self.model_dump(mode="python")
        for k, v in updates.items():
            d[k] = v
        return Trade.model_validate(d)


# --------------------------------------------------------------------------- миграции схемы
def _migrate_1_0_to_1_1(d: dict) -> dict:
    """1.0 → 1.1: поле ``purpose.hedge`` переименовано в ``purpose.type``; ``collateral.csa`` → ``regime``."""
    d = copy.deepcopy(d)
    p = d.get("purpose")
    if isinstance(p, dict) and "hedge" in p:
        p["type"] = p.pop("hedge")
    c = d.get("collateral")
    if isinstance(c, dict) and "csa" in c:
        c["regime"] = {True: "two_way", False: "none"}.get(c.pop("csa"), "none")
    d["schema_version"] = "1.1"
    return d


MIGRATIONS = {"1.0": _migrate_1_0_to_1_1}


def migrate(data: dict) -> tuple[dict, list[str]]:
    """Привести данные сделки к текущей версии схемы. Возвращает (данные, журнал)."""
    log = []
    v = str(data.get("schema_version", "1.0"))
    while v != TRADE_SCHEMA_VERSION:
        fn = MIGRATIONS.get(v)
        if fn is None:
            raise ValueError(f"нет миграции схемы сделки с версии {v}")
        data = fn(data)
        log.append(f"{v} → {data['schema_version']}")
        v = data["schema_version"]
    return data, log


def load_trade(data: dict | str) -> Trade:
    """Загрузить сделку из dict / YAML / JSON-строки или пути к файлу."""
    import yaml
    from pathlib import Path
    if isinstance(data, str):
        p = Path(data)
        text = p.read_text(encoding="utf-8") if (len(data) < 4096 and p.exists()) else data
        data = yaml.safe_load(text)
    data, _ = migrate(dict(data))
    return Trade.model_validate(data)
