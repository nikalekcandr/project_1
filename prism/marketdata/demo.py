"""Демонстрационный снапшот рынка.

ВНИМАНИЕ: все числа здесь иллюстративные. Они внутренне согласованы
(котировки свопов получены из заданной траектории ключевой ставки,
форвардные пункты — из покрытого паритета с базисом и т.д.), но не являются
рыночными данными на указанную дату. Снапшот помечен ``meta.demo = true``,
и каждый отчёт, построенный на нём, выводит это предупреждение.

Для реальной оценки снапшот собирается адаптерами ``prism.marketdata.sources``
из публичных источников (Мосбиржа, Банк России, Росстат, раскрытие эмитентов).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

import numpy as np

from ..core.calendars import get_calendar
from ..core.dates import add_tenor
from ..core.daycount import DayCount
from ..core.provenance import DataKind, Provenance
from ..curves.base import YieldCurve
from ..curves.bootstrap import BasisSwapInstrument, SELF, deposit_from_tenor, swap_from_tenor
from ..curves.inflation import add_m, month_key
from .snapshot import Dataset, MarketSnapshot, Quote
from .sources import MSK

DEMO_NOTE = "ДЕМО: иллюстративное значение"

# Календарь заседаний Совета директоров Банка России (ДЕМО: сверить с официальной публикацией ЦБ)
MEETINGS = [
    ("2026-02-13", "core"), ("2026-03-20", "regular"), ("2026-04-24", "core"), ("2026-06-19", "regular"),
    ("2026-07-24", "core"), ("2026-09-11", "regular"), ("2026-10-23", "core"), ("2026-12-18", "regular"),
    ("2027-02-12", "core"), ("2027-03-19", "regular"), ("2027-04-23", "core"), ("2027-06-11", "regular"),
    ("2027-07-23", "core"), ("2027-09-10", "regular"), ("2027-10-22", "core"), ("2027-12-17", "regular"),
]
# Траектория ключевой ставки после каждого будущего заседания («истинная» для генерации котировок)
KEY_RATE_NOW = 0.165
PATH_AFTER = {
    "2026-10-23": 0.1600, "2026-12-18": 0.1550, "2027-02-12": 0.1500, "2027-03-19": 0.1450,
    "2027-04-23": 0.1400, "2027-06-11": 0.1375, "2027-07-23": 0.1350, "2027-09-10": 0.1325,
    "2027-10-22": 0.1300, "2027-12-17": 0.1300,
}
TAIL = [(3.0, 0.1275), (5.0, 0.1250), (7.0, 0.1240), (10.0, 0.1235), (15.0, 0.1230)]


def _p(source: str, ts: datetime, kind: DataKind = DataKind.MARKET, url: str | None = None, note: str = DEMO_NOTE) -> Provenance:
    return Provenance(source, ts, kind, url, note)


def _effective(ann: date, cal) -> date:
    return cal.advance_business_days(ann, 1)


def _true_keyrate_curve(ref: date, cal) -> YieldCurve:
    """«Истинная» кривая КС: форвард кусочно-постоянен между датами вступления в силу."""
    pts = [(0.0, KEY_RATE_NOW)]
    for ann, r in PATH_AFTER.items():
        eff = _effective(date.fromisoformat(ann), cal)
        pts.append(((eff - ref).days / 365.0, r))
    times, logdf = [], []
    ly = 0.0
    for (t0, r), (t1, _) in zip(pts, pts[1:] + [(2.2, None)]):
        c = 365 * np.log1p(r / 365)   # дневная простая ставка → непрерывная
        ly -= c * (t1 - t0)
        times.append(t1)
        logdf.append(ly)
    last_t = times[-1]
    for t, r in TAIL:
        if t <= last_t:
            continue
        c = 365 * np.log1p(r / 365)
        ly -= c * (t - last_t)
        times.append(t)
        logdf.append(ly)
        last_t = t
    return YieldCurve("TRUE.KEYRATE", ref, np.array(times), np.array(logdf), "log_linear", "RUB")


def _flat(cid: str, ref: date, r: float, ccy: str, slope: float = 0.0) -> YieldCurve:
    ts = np.array([0.25, 0.5, 1, 2, 3, 5, 7, 10, 15, 20, 30.0])
    z = r + slope * np.log1p(ts) / np.log(31)
    return YieldCurve(cid, ref, ts, -z * ts, "log_linear", ccy)


def build_demo_snapshot(as_of: datetime | None = None, *, day_shift: int = 0, noise_seed: int = 7) -> MarketSnapshot:
    as_of = as_of or datetime(2026, 10, 15, 18, 45, tzinfo=MSK)
    ref = as_of.date()
    rng = np.random.default_rng(noise_seed + day_shift)
    eps = (lambda scale: 0.0) if day_shift == 0 else (lambda scale: float(rng.normal(0, scale)))
    ru = get_calendar("RU")
    ts_moex = as_of
    ts_cbr = datetime.combine(ref, time(15, 30), MSK)
    ts_fix = datetime.combine(ref, time(13, 30), MSK)
    q: list[Quote] = []
    ds: list[Dataset] = []

    # ------------------------------------------------------------------ ставки РФ
    ks_true = _true_keyrate_curve(ref, ru)
    q.append(Quote("RATE.RUB.KEYRATE", KEY_RATE_NOW, _p("Банк России: ключевая ставка", datetime(2026, 9, 14, tzinfo=MSK),
                                                        url="https://www.cbr.ru/hd_base/KeyRate/"), "rate",
                   meta={"effective_date": "2026-09-14", "daycount": "ACT/365F"}))
    for tenor in ["3M", "6M", "9M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y"]:
        ins = swap_from_tenor("x", "x", 0.0, ref, 1, tenor, ru, "3M", "3M", compounding="simple_average")
        par = round(ins.model(ks_true, {}) + eps(0.0004), 4)
        q.append(Quote(f"SWAP.RUB.KEYRATE.{tenor}", par,
                       _p("НФА / Мосбиржа: индикативные котировки IRS на ключевую ставку", ts_moex),
                       "rate", bid=round(par - 0.0010, 4), ask=round(par + 0.0010, 4),
                       meta={"tenor": tenor, "fixed_freq": "3M", "float": "KEYRATE simple average"}))
    rusfar_true = YieldCurve("TRUE.RUSFAR", ref, ks_true.times, ks_true.logdf + 0.0040 * ks_true.times, "log_linear", "RUB")
    for tenor in ["ON", "1W", "2W", "1M", "3M"]:
        ins = deposit_from_tenor("x", "x", 0.0, ref, 0, tenor, ru)
        r = round(ins.model(rusfar_true, {}) + eps(0.0003), 4)
        q.append(Quote(f"RATE.RUB.RUSFAR.{tenor}", r, _p(f"Мосбиржа: индикатор RUSFAR{'' if tenor == 'ON' else tenor}", ts_fix,
                                                          url="https://www.moex.com/ru/index/RUSFAR"), "rate",
                       meta={"tenor": tenor, "daycount": "ACT/365F"}))
    for tenor in ["6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y"]:
        sw = swap_from_tenor("x", "x", 0.0, ref, 1, tenor, ru, "3M", "3M")
        b = BasisSwapInstrument("x", "x", 0.0, sw.maturity, sw.float_periods, SELF, "KS", "KS", "compounded", "simple_average")
        sp = round(b.model(rusfar_true, {"KS": ks_true}) + eps(0.0002), 4)
        q.append(Quote(f"BASIS.RUB.RUSFAR_KEYRATE.{tenor}", sp, _p("НФА: индикативные базисные свопы RUSFAR/КС", ts_moex),
                       "rate", meta={"tenor": tenor, "quote": "спред на ноге RUSFAR"}))
    ruonia_true = YieldCurve("TRUE.RUONIA", ref, ks_true.times, ks_true.logdf + 0.0025 * ks_true.times, "log_linear", "RUB")
    q.append(Quote("RATE.RUB.RUONIA", round(deposit_from_tenor("x", "x", 0, ref, 0, "ON", ru).model(ruonia_true, {}), 4),
                   _p("Банк России: RUONIA", datetime.combine(ref - timedelta(days=1), time(14, 0), MSK),
                      url="https://www.cbr.ru/hd_base/ruonia/"), "rate", meta={"tenor": "ON"}))
    for tenor in ["1W", "2W", "1M", "2M", "3M", "6M", "1Y"]:
        ins = swap_from_tenor("x", "x", 0.0, ref, 1, tenor, ru, compounding="compounded")
        q.append(Quote(f"RATE.RUB.ROISFIX.{tenor}", round(ins.model(ruonia_true, {}) + eps(0.0003), 4),
                       _p("НФА: ROISfix", ts_fix, url="https://www.nfa.ru/"), "rate", meta={"tenor": tenor}))
    for tenor in ["2Y", "3Y", "5Y", "7Y", "10Y"]:
        sw = swap_from_tenor("x", "x", 0.0, ref, 1, tenor, ru, "3M", "3M")
        b = BasisSwapInstrument("x", "x", 0.0, sw.maturity, sw.float_periods, SELF, "KS", "KS", "compounded", "simple_average")
        q.append(Quote(f"BASIS.RUB.RUONIA_KEYRATE.{tenor}", round(b.model(ruonia_true, {"KS": ks_true}), 4),
                       _p("НФА: индикативные базисные свопы RUONIA/КС", ts_moex), "rate", meta={"tenor": tenor}))
    q.append(Quote("CURVE.RUB.KBD", {"B1": 1350.0 + eps(5), "B2": 180.0, "B3": -120.0, "T1": 2.0,
                                     "G1": 4.0, "G2": -3.0, "G3": 2.0, "G4": 0.0, "G5": 0.0, "G6": 0.0, "G7": 0.0, "G8": 0.0, "G9": 0.0},
                   _p("Мосбиржа: КБД ОФЗ (параметры)", ts_moex, url="https://iss.moex.com/iss/engines/stock/zcyc.json"),
                   "nss_params_bp"))

    # ------------------------------------------------------------------ иностранные ставки
    foreign = {
        "USD": ("SOFR", 0.0360, -0.0020, "US", 2, "ACT/360", "1Y", "ФРБ Нью-Йорка / котировки OIS SOFR (внешний рынок)"),
        "EUR": ("ESTR", 0.0195, 0.0025, "TARGET", 2, "ACT/360", "1Y", "ЕЦБ / котировки OIS €STR (внешний рынок)"),
        "CNY": ("REPO", 0.0155, 0.0030, "CN", 1, "ACT/365F", "3M", "CFETS: IRS на FR007 (onshore)"),
        "CNH": ("HIBOR", 0.0190, 0.0020, "HK", 2, "ACT/365F", "3M", "TMA: CNH HIBOR / IRS (offshore)"),
    }
    true_foreign = {}
    for ccy, (name, r, slope, calc, lag, dcs, freq, src) in foreign.items():
        tc = _flat(f"TRUE.{ccy}", ref, r, ccy, slope)
        true_foreign[ccy] = tc
        cal = get_calendar(calc)
        dc = DayCount.parse(dcs)
        for tenor in ["1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y"]:
            ins = swap_from_tenor("x", "x", 0.0, ref, lag, tenor, cal, freq, freq, dc, dc, compounding="compounded")
            q.append(Quote(f"RATE.{ccy}.{name}.{tenor}", round(ins.model(tc, {}), 5), _p(src, ts_moex, note=DEMO_NOTE + "; внешний рынок"),
                           "rate", meta={"tenor": tenor}))

    # ------------------------------------------------------------------ FX
    fx_spec = {
        "USDRUB": (82.50, "USD", -0.0120, 0.10, "RU+US", "Внебиржевой рынок / ЦБ РФ (USD/RUB торгуется вне биржи)"),
        "EURRUB": (96.10, "EUR", -0.0100, 0.12, "RU+TARGET", "Внебиржевой рынок / ЦБ РФ"),
        "CNYRUB": (11.52, "CNY", -0.0060, 0.005, "RU+CN", "Мосбиржа: CNYRUB_TOM, режим CETS"),
    }
    fx_spots = {}
    for pair, (spot, fccy, basis, hs, calc, src) in fx_spec.items():
        cal = get_calendar(calc)
        spot = round(spot * (1 + eps(0.004)), 4)
        fx_spots[pair] = spot
        sd = cal.advance_business_days(ref, 1)
        q.append(Quote(f"FX.{pair}.SPOT", spot, _p(src, ts_moex), "price", bid=round(spot - hs, 4), ask=round(spot + hs, 4),
                       meta={"settlement": "TOM"}))
        tf = true_foreign[fccy]
        dcf = 360.0 if fccy in ("USD", "EUR") else 365.0
        for tenor in ["1W", "2W", "1M", "2M", "3M", "6M", "9M", "1Y", "18M", "2Y", "3Y"]:
            d = add_tenor(sd, tenor, cal)
            t_s, t_d = (sd - ref).days / 365.0, (d - ref).days / 365.0
            gross_d = float(ks_true.df(t_s) / ks_true.df(t_d)) * np.exp(basis * (t_d - t_s))
            gross_f = float(tf.df(t_s) / tf.df(t_d))
            fwd = spot * gross_d / gross_f
            pts = round(fwd - spot, 4)
            hsp = round(max(abs(pts) * 0.02, hs * 0.2), 4)
            q.append(Quote(f"FX.{pair}.FWD.{tenor}", pts, _p(f"{src}: форвардные пункты (своп)", ts_moex), "points",
                           bid=round(pts - hsp, 4), ask=round(pts + hsp, 4), meta={"tenor": tenor}))
        q.append(Quote(f"FX.{pair}.FIX.CBR", round(spot * 0.999, 4),
                       _p("Банк России: официальный курс", ts_cbr, url="https://www.cbr.ru/currency_base/daily/",
                          note=DEMO_NOTE + f"; курс установлен на {(ref + timedelta(days=1)).isoformat()}"),
                       "price", meta={"effective_date": (ref + timedelta(days=1)).isoformat()}))
        q.append(Quote(f"FX.{pair}.FIX.MOEX", round(spot * 1.0004, 4),
                       _p(f"Мосбиржа: фиксинг {pair[:3]}FIXME", datetime.combine(ref, time(12, 30), MSK)), "price"))

    # волатильность: USDRUB и CNYRUB — опционы срочного рынка Мосбиржи; EURRUB — котировок нет (исторический фоллбэк)
    vol_spec = {
        "USDRUB": {"1W": (13.5, 2.4, 0.55), "1M": (14.0, 2.8, 0.65), "2M": (14.5, 3.1, 0.72), "3M": (15.0, 3.4, 0.80),
                   "6M": (16.0, 3.9, 0.92), "9M": (16.8, 4.2, 1.00), "1Y": (17.5, 4.5, 1.08), "2Y": (18.5, 4.8, 1.15)},
        "CNYRUB": {"1W": (12.0, 2.0, 0.45), "1M": (12.5, 2.4, 0.55), "2M": (13.0, 2.7, 0.62), "3M": (13.5, 3.0, 0.70),
                   "6M": (14.5, 3.4, 0.82), "9M": (15.2, 3.7, 0.90), "1Y": (15.8, 4.0, 0.98)},
    }
    for pair, rows in vol_spec.items():
        src = "Мосбиржа: опционы на фьючерс Si (USD/RUB)" if pair == "USDRUB" else "Мосбиржа: опционы на фьючерс CR (CNY/RUB)"
        for tenor, (atm, rr, bf) in rows.items():
            kind = DataKind.MARKET if tenor != "2Y" else DataKind.EXTRAPOLATED
            note = DEMO_NOTE if kind is DataKind.MARKET else DEMO_NOTE + "; срок вне ликвидной части — достроено по форме более коротких сроков"
            atm_v = round((atm + eps(0.2)) / 100, 4)
            for name, val, h in (("ATM", atm_v, 0.005), ("RR25", rr / 100, 0.004), ("BF25", bf / 100, 0.003),
                                 ("RR10", round(rr * 1.85 / 100, 4), 0.007), ("BF10", round(bf * 3.1 / 100, 4), 0.006)):
                q.append(Quote(f"VOL.{pair}.{name}.{tenor}", round(val, 4), _p(src, ts_moex, kind, note=note), "vol",
                               bid=round(val - h, 4), ask=round(val + h, 4), meta={"tenor": tenor}))

    # ------------------------------------------------------------------ инфляция
    q += [Quote(f"INFL.RUB.ZCIS.{t}", v, _p("Мосбиржа: ОФЗ-ИН против ОФЗ сопоставимой дюрации (безубыточная инфляция)", ts_moex,
                                             DataKind.DERIVED), "rate", meta={"tenor": t})
          for t, v in (("1Y", 0.0560), ("2Y", 0.0510), ("3Y", 0.0485), ("5Y", 0.0460), ("7Y", 0.0450), ("10Y", 0.0445))]

    # ------------------------------------------------------------------ товары
    def months_from(ym, n):
        return [add_m(ym, k) for k in range(n)]
    start = add_m((ref.year, ref.month), 2)
    for i, ym in enumerate(months_from(start, 20)):
        brent = round(68.4 - 0.18 * i + eps(0.5), 2)
        q.append(Quote(f"CMDTY.BRENT.FUT.{month_key(*ym)}", brent, _p("ICE Brent (внешняя биржа) / индексы СПбМТСБ", ts_moex),
                       "USD/bbl", bid=brent - 0.03, ask=brent + 0.03))
        urals = round(brent - 11.5, 2)
        q.append(Quote(f"CMDTY.URALS.FUT.{month_key(*ym)}", urals, _p("Ценовые агентства / СПбМТСБ: Urals (дифференциал к Brent)", ts_moex,
                                                                        DataKind.DERIVED), "USD/bbl", bid=urals - 0.25, ask=urals + 0.25))
        gold = round(3610 + 9.5 * i, 1)
        q.append(Quote(f"CMDTY.GOLD.FUT.{month_key(*ym)}", gold, _p("LBMA / Мосбиржа: GLDRUB_TOM пересчёт в USD", ts_moex),
                       "USD/troy_oz", bid=gold - 1.0, ask=gold + 1.0))
    wheat_seas = np.array([1.03, 1.04, 1.05, 1.05, 1.04, 0.97, 0.93, 0.94, 0.97, 0.99, 1.00, 1.01])
    wheat_seas /= np.exp(np.mean(np.log(wheat_seas)))
    for ym in months_from(start, 12)[::3]:
        v = round(16200 * wheat_seas[ym[1] - 1], 0)
        q.append(Quote(f"CMDTY.WHEAT_RU.FUT.{month_key(*ym)}", v, _p("СПбМТСБ / Национальный товарный индекс: пшеница 3 кл.", ts_moex),
                       "RUB/t"))
    power_seas = np.array([1.22, 1.18, 1.08, 0.97, 0.90, 0.86, 0.88, 0.90, 0.93, 1.00, 1.08, 1.18])
    power_seas /= np.exp(np.mean(np.log(power_seas)))
    for ym in months_from(start, 12)[::2]:
        v = round(1650 * power_seas[ym[1] - 1], 0)
        q.append(Quote(f"CMDTY.POWER_EU_ZONE1.FUT.{month_key(*ym)}", v, _p("АТС: РСВ, первая ценовая зона (индекс)", ts_moex),
                       "RUB/MWh"))
    for asset, F0, atm, skew in (("BRENT", 68.0, 0.32, -0.08), ("URALS", 56.5, 0.36, -0.08), ("GOLD", 3620, 0.18, 0.03)):
        for k, months in enumerate((2, 5, 8, 14)):
            exp = add_tenor(ref, f"{months}M", ru)
            Fm = F0
            strikes = [round(Fm * m, 2) for m in (0.75, 0.85, 0.95, 1.0, 1.05, 1.15, 1.3)]
            vols = [round(atm + 0.01 * k + skew * np.log(m) * 1.0 + 0.25 * np.log(m) ** 2, 4)
                    for m in (0.75, 0.85, 0.95, 1.0, 1.05, 1.15, 1.3)]
            q.append(Quote(f"VOL.{asset}.{exp.isoformat()}", {"strikes": strikes, "vols": vols},
                           _p("Биржевые опционы на фьючерсы (внешний рынок) / Мосбиржа", ts_moex), "vol_slice"))

    # ------------------------------------------------------------------ акции
    for asset, spot, divs, borrow, atm, skew in (
        ("SBER", 305.0, [("2027-07-17", 37.0)], 0.015, 0.28, -0.18),
        ("GAZP", 134.5, [("2027-07-18", 0.0)], 0.020, None, None),
        ("IMOEX", 2850.0, [("2027-06-20", 25.0), ("2027-07-15", 55.0), ("2027-08-10", 20.0)], 0.005, 0.22, -0.20),
    ):
        spot = round(spot * (1 + eps(0.01)), 2)
        q.append(Quote(f"EQ.{asset}.SPOT", spot, _p(f"Мосбиржа: {asset}, режим TQBR" if asset != "IMOEX" else "Мосбиржа: индекс IMOEX",
                                                    ts_moex), "price", bid=round(spot * 0.9997, 2), ask=round(spot * 1.0003, 2)))
        for d, a in divs:
            if a:
                q.append(Quote(f"EQ.{asset}.DIV.{d}", a, _p("Раскрытие эмитента / дивидендная политика: прогноз дивиденда", ts_moex,
                                                            DataKind.MODEL, note=DEMO_NOTE + "; прогноз, решение не объявлено"), "RUB"))
        q.append(Quote(f"EQ.{asset}.BORROW", borrow, _p("Мосбиржа: ставки РЕПО с акциями / ЦК", ts_moex, DataKind.DERIVED), "rate"))
        if atm is not None:
            for k, months in enumerate((2, 5, 8, 14)):
                exp = add_tenor(ref, f"{months}M", ru)
                ms = (0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.35)
                strikes = [round(spot * m, 2) for m in ms]
                vols = [round(atm + 0.008 * k + skew * np.log(m) + 0.3 * np.log(m) ** 2, 4) for m in ms]
                q.append(Quote(f"VOL.{asset}.SLICE.{exp.isoformat()}", {"strikes": strikes, "vols": vols},
                               _p("Мосбиржа: опционы срочного рынка (теоретические волатильности)", ts_moex), "vol_slice"))

    # ------------------------------------------------------------------ кредит: облигации эмитентов
    bonds = [
        ("RU000DEMMET1", "CLIENT_METAL", 0.1720, 1.1, "metals", "AA(RU)"),
        ("RU000DEMMET2", "CLIENT_METAL", 0.1690, 2.4, "metals", "AA(RU)"),
        ("RU000DEMMET3", "CLIENT_METAL", 0.1670, 3.8, "metals", "AA(RU)"),
        ("RU000PEERTR1", "PEER_TRADE_1", 0.1950, 1.5, "trade", "A(RU)"),
        ("RU000PEERTR2", "PEER_TRADE_2", 0.1990, 2.2, "trade", "A(RU)"),
        ("RU000PEERTR3", "PEER_TRADE_3", 0.1930, 3.0, "trade", "A(RU)"),
        ("RU000BANKDM1", "BANK_DEMO", 0.1640, 1.8, "banks", "AA+(RU)"),
        ("RU000BANKDM2", "BANK_DEMO", 0.1610, 3.2, "banks", "AA+(RU)"),
    ]
    for isin, issuer, y, dur, sector, rating in bonds:
        q.append(Quote(f"CREDIT.BOND.{isin}", round(y + eps(0.001), 4),
                       _p("Мосбиржа: доходность облигации (раскрытие эмитента)", ts_moex,
                          url=f"https://www.moex.com/ru/issue.aspx?code={isin}"), "yield",
                       meta={"issuer": issuer, "duration": dur, "sector": sector, "rating": rating}))

    # ------------------------------------------------------------------ датасеты
    ms = [{"announcement": a, "effective": _effective(date.fromisoformat(a), ru).isoformat(), "kind": k} for a, k in MEETINGS]
    ds.append(Dataset("cbr_meetings", {"meetings": ms},
                      _p("Банк России: календарь заседаний Совета директоров", datetime(2026, 9, 12, tzinfo=MSK),
                         url="https://www.cbr.ru/dkp/cal_mp/",
                         note=DEMO_NOTE + "; даты требуют сверки с официальной публикацией")))
    ds.append(_cpi_dataset(ref))
    ds.append(Dataset("rating_pd", _rating_tables(), _p("Статистика дефолтов рейтинговых агентств (АКРА, Эксперт РА)",
                                                       datetime(2026, 4, 1, tzinfo=MSK), DataKind.HISTORICAL,
                                                       note=DEMO_NOTE + "; заменить на опубликованную статистику агентств")))
    ds.append(Dataset("credit_entities", {
        "CLIENT_IMPORT": {"name": "ООО «Демо-Импорт»", "sector": "trade", "rating": "A(RU)", "agency": "AKRA", "recovery": 0.35},
        "CLIENT_METAL": {"name": "ПАО «Демо-Металл»", "sector": "metals", "rating": "AA(RU)", "agency": "AKRA", "recovery": 0.4},
        "CLIENT_AGRO": {"name": "ООО «Демо-Агро»", "sector": "agro", "rating": "BBB(RU)", "agency": "AKRA", "recovery": 0.3},
        "CLIENT_ENERGY": {"name": "АО «Демо-Энерго»", "sector": "energy", "rating": "ruA+", "agency": "EXPERT_RA", "recovery": 0.4},
        "BANK_DEMO": {"name": "Банк «Демо»", "sector": "banks", "rating": "AA+(RU)", "agency": "AKRA", "recovery": 0.3},
        "BANK_OTHER": {"name": "Банк «Альтернатива»", "sector": "banks", "rating": "AA(RU)", "agency": "AKRA", "recovery": 0.3},
    }, _p("Карточки контрагентов: рейтинги АКРА / Эксперт РА (публичные пресс-релизы)", ts_moex)))
    ds.append(Dataset("correlations", {
        "USDRUB|CNYRUB": 0.93, "USDRUB|EURRUB": 0.91, "CNYRUB|EURRUB": 0.90, "USDRUB|KEYRATE": 0.35,
        "CNYRUB|KEYRATE": 0.32, "EURRUB|KEYRATE": 0.33, "BRENT|USDRUB": -0.35, "URALS|USDRUB": -0.37, "BRENT|URALS": 0.95,
        "GOLD|USDRUB": 0.22, "GOLD|BRENT": 0.15, "SBER|IMOEX": 0.85, "GAZP|IMOEX": 0.74, "SBER|GAZP": 0.58,
        "SBER|USDRUB": -0.30, "GAZP|USDRUB": -0.20, "IMOEX|USDRUB": -0.35, "WHEAT_RU|USDRUB": 0.30,
        "BRENT|CNYRUB": -0.30, "URALS|CNYRUB": -0.32, "IMOEX|KEYRATE": -0.30, "SBER|KEYRATE": -0.25,
        "POWER_EU_ZONE1|KEYRATE": 0.05, "WHEAT_RU|BRENT": 0.12,
    }, _p("Историческая оценка корреляций по дневным доходностям (окно 1 год)", ts_moex, DataKind.HISTORICAL)))
    ds.append(_hist_rates(ref, rng_seed=11))
    for pair, spot, vol in (("usdrub", fx_spots["USDRUB"], 0.16), ("cnyrub", fx_spots["CNYRUB"], 0.145),
                            ("eurrub", fx_spots["EURRUB"], 0.155)):
        ds.append(_hist_series(f"hist_fx_{pair}", spot, vol, 520, 100 + len(pair) + int(spot)))
    ds.append(_hist_series("hist_gazp", 134.5, 0.30, 520, 31))
    ds.append(_hist_series("hist_wheat_ru", 16200, 0.24, 520, 32))
    ds.append(_hist_series("hist_power_eu_zone1", 1650, 0.45, 520, 33))
    ds.append(_hist_series("hist_brent", 68.0, 0.32, 520, 34))
    ds.append(Dataset("seasonality_wheat_ru", {"factors": [round(float(x), 4) for x in wheat_seas]},
                      _p("Оценка сезонности по истории индекса СПбМТСБ", ts_moex, DataKind.HISTORICAL)))
    ds.append(Dataset("seasonality_power_zone1", {"factors": [round(float(x), 4) for x in power_seas]},
                      _p("Оценка сезонности по истории РСВ АТС", ts_moex, DataKind.HISTORICAL)))
    ds.append(_fixings(ref, fx_spots, ru))
    ds.append(_weather())
    snap = MarketSnapshot.create(as_of, "demo", q, ds, meta={
        "demo": True,
        "description": "Демонстрационный снапшот: иллюстративные, внутренне согласованные данные. Не для реальной оценки.",
        "generator": "prism.marketdata.demo.build_demo_snapshot",
        "day_shift": day_shift,
    })
    return snap


def _cpi_dataset(ref: date) -> Dataset:
    seas = [0.75, 0.55, 0.40, 0.38, 0.40, 0.30, 0.62, -0.10, 0.18, 0.48, 0.55, 0.68]
    first, revised, pub = {}, {}, {}
    lvl = 100.0
    rng = np.random.default_rng(5)
    ym = (2020, 12)
    first[month_key(*ym)] = revised[month_key(*ym)] = lvl
    pub[month_key(*ym)] = "2021-01-13"
    while True:
        ym = add_m(ym, 1)
        pd = date(*add_m(ym, 1), 12)
        if pd > ref:
            break
        mom = seas[ym[1] - 1] + float(rng.normal(0, 0.12)) + (0.15 if ym[0] in (2022,) else 0.0)
        rev = mom + (float(rng.normal(0, 0.03)) if rng.random() < 0.3 else 0.0)
        first[month_key(*ym)] = round(lvl * (1 + mom / 100), 4)
        lvl = lvl * (1 + rev / 100)
        revised[month_key(*ym)] = round(lvl, 4)
        pub[month_key(*ym)] = pd.isoformat()
    return Dataset("cpi_ru", {"index_first": first, "index_revised": revised, "published": pub,
                              "base": "декабрь 2020 = 100"},
                   _p("Росстат: индексы потребительских цен (первая и уточнённая публикации), календарь публикаций",
                      datetime.combine(ref, time(10, 0), MSK), url="https://rosstat.gov.ru/statistics/price"))


def _rating_tables() -> dict:
    hz = [1, 2, 3, 4, 5]
    akra = {
        "AAA(RU)": [0.0002, 0.0006, 0.0012, 0.0020, 0.0030],
        "AA+(RU)": [0.0006, 0.0016, 0.0030, 0.0046, 0.0064],
        "AA(RU)": [0.0010, 0.0026, 0.0047, 0.0071, 0.0098],
        "AA-(RU)": [0.0018, 0.0044, 0.0076, 0.0112, 0.0150],
        "A+(RU)": [0.0030, 0.0072, 0.0121, 0.0174, 0.0229],
        "A(RU)": [0.0048, 0.0112, 0.0184, 0.0260, 0.0336],
        "A-(RU)": [0.0075, 0.0170, 0.0274, 0.0380, 0.0484],
        "BBB+(RU)": [0.0115, 0.0255, 0.0400, 0.0544, 0.0682],
        "BBB(RU)": [0.0170, 0.0370, 0.0570, 0.0762, 0.0942],
        "BBB-(RU)": [0.0250, 0.0530, 0.0800, 0.1050, 0.1280],
        "BB+(RU)": [0.0380, 0.0780, 0.1150, 0.1480, 0.1770],
        "BB(RU)": [0.0560, 0.1120, 0.1610, 0.2030, 0.2390],
    }
    expert = {"ru" + k.replace("(RU)", ""): v for k, v in akra.items()}
    return {
        "AKRA": {"agency": "АКРА", "horizons": hz, "cumulative_pd": akra, "default_risk_premium_mult": 1.5},
        "EXPERT_RA": {"agency": "Эксперт РА", "horizons": hz, "cumulative_pd": expert, "default_risk_premium_mult": 1.5},
    }


def _hist_series(name: str, last: float, vol: float, n: int, seed: int) -> Dataset:
    rng = np.random.default_rng(seed)
    r = rng.normal(0, vol / np.sqrt(252), n)
    path = last * np.exp(np.cumsum(r[::-1]))[::-1]
    path = path / path[-1] * last
    return Dataset(name, {"spot": [round(float(x), 6) for x in path], "frequency": "1B"},
                   _p("Исторический ряд (публичный источник)", datetime(2026, 10, 15, 18, 45, tzinfo=MSK), DataKind.HISTORICAL,
                      note=DEMO_NOTE + "; синтетический ряд"))


def _hist_rates(ref: date, rng_seed: int) -> Dataset:
    rng = np.random.default_rng(rng_seed)
    tenors = {"1Y": (0.1450, 0.0210), "2Y": (0.1360, 0.0185), "3Y": (0.1320, 0.0170), "5Y": (0.1290, 0.0150),
              "10Y": (0.1260, 0.0135)}
    series = {}
    n = 300
    z_common = rng.normal(0, 1, n)
    for t, (last, nv) in tenors.items():
        z = 0.85 * z_common + np.sqrt(1 - 0.85 ** 2) * rng.normal(0, 1, n)
        inc = z * nv / np.sqrt(252)
        path = last - np.cumsum(inc[::-1])[::-1] + inc[-1]
        path = path - path[-1] + last
        series[t] = [round(float(x), 6) for x in path]
    return Dataset("hist_rub_keyrate_swaps", {"series": series, "frequency": "1B"},
                   _p("История индикативных ставок IRS на ключевую ставку (НФА / Мосбиржа)", datetime.combine(ref, time(18, 45), MSK),
                      DataKind.HISTORICAL, note=DEMO_NOTE + "; синтетический ряд"))


def _fixings(ref: date, spots: dict, cal) -> Dataset:
    days = []
    d = ref
    while len(days) < 160:
        d -= timedelta(days=1)
        if cal.is_business_day(d):
            days.append(d)
    days = days[::-1] + [ref]
    rng = np.random.default_rng(21)
    out = {"CBR": {}, "MOEX": {}}
    vols = {"USDRUB": 0.16, "EURRUB": 0.155, "CNYRUB": 0.145}
    for pair, s in spots.items():
        z = rng.normal(0, vols[pair] / np.sqrt(252), len(days))
        path = s * np.exp(np.cumsum(z[::-1]))[::-1]
        path = path / path[-1] * s
        out["MOEX"][pair] = {dd.isoformat(): round(float(v * 1.0004), 4) for dd, v in zip(days, path)}
        # курс ЦБ на дату D устанавливается накануне — по рынку предыдущего рабочего дня
        cbr = {}
        for i, dd in enumerate(days[1:], start=1):
            cbr[dd.isoformat()] = round(float(path[i - 1] * 0.999), 4)
        out["CBR"][pair] = cbr
    # история ключевой ставки и RUONIA
    out["CBR"]["KEYRATE"] = {dd.isoformat(): (0.17 if dd < date(2026, 9, 14) else 0.165) for dd in days}
    out["CBR"]["RUONIA"] = {dd.isoformat(): round(out["CBR"]["KEYRATE"][dd.isoformat()] - 0.0025, 4) for dd in days}
    return Dataset("fixings", out, _p("Банк России (официальные курсы, КС, RUONIA) и Мосбиржа (фиксинги)",
                                      datetime.combine(ref, time(15, 30), MSK), note=DEMO_NOTE + "; синтетическая история"))


def _weather() -> Dataset:
    rng = np.random.default_rng(99)
    years = list(range(1996, 2026))
    hdd = [round(float(4150 - 9.0 * (y - 1996) + rng.normal(0, 210)), 1) for y in years]
    return Dataset("weather_hdd_27612", {"station": "27612 (Москва, ВДНХ)", "index": "HDD, база 18°C, ноябрь–март",
                                         "years": years, "values": hdd},
                   _p("Росгидромет: архив метеонаблюдений станции 27612", datetime(2026, 4, 1, tzinfo=MSK), DataKind.HISTORICAL,
                      note=DEMO_NOTE + "; синтетический ряд"))


def demo_store_snapshots(store) -> tuple[MarketSnapshot, MarketSnapshot]:
    """Создать демо-снапшоты на дату и на предыдущий рабочий день (для QC выбросов)."""
    from .qc import run_qc
    prev = build_demo_snapshot(datetime(2026, 10, 14, 18, 45, tzinfo=MSK), day_shift=1)
    cur = build_demo_snapshot()
    cur = cur.with_qc([f.to_dict() for f in run_qc(cur, prev)])
    prev = prev.with_qc([f.to_dict() for f in run_qc(prev)])
    store.save(prev)
    store.save(cur)
    return cur, prev
