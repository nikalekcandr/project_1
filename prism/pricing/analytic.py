"""Аналитический движок для структур без сквозной путезависимости.

Компонент за компонентом, период за периодом:

* FX/акции/товары: форвард; ваниль Garman-Kohlhagen со смайлом (вола на
  страйке); цифровые с поправкой на скос улыбки; одиночный барьер
  (Reiner-Rubinstein, дискретное наблюдение — BGK) с поправкой vanna-volga;
  one-touch / no-touch; двойной барьер (Ikeda-Kunitomo), double-no-touch
  (Hui); азиатские (моменты); спред (Kirk);
* ставки: фиксированная/плавающая нога по мультикривой, каплеты/флорлеты
  Башелье по нормальной воле, европейский свопцион;
* ИПЦ: индексация с лагом, сезонностью и версией публикации;
* кредит: премия/защита/восстановление по кривой интенсивности;
* вариансные свопы: статическая репликация с оценкой ошибки дискретизации;
* погодные: актуарная оценка по исторической статистике.

Если хотя бы один элемент не покрывается аналитикой — :class:`NotAnalytic`,
и маршрутизатор переходит к Монте-Карло.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np

from ..core.provenance import DataKind, Provenance, UsedInput
from ..instruments.schema import (AssetObs, AveragingMod, BarrierMod, CapFloorMod, Component, CPIObs, CreditObs,
                                  ExerciseMod, LeverageMod, RateObs, RealizedVarObs, SpreadObs, Trade, WeatherObs)
from ..models.analytic.asian import arithmetic_asian, geometric_asian
from ..models.analytic.barriers import (bgk_shift, barrier_price, double_barrier_ko, double_no_touch,
                                        double_no_touch_prob, no_touch_prob, touch_price)
from ..models.analytic.black import bachelier, black, black_digital
from ..models.analytic.spread import kirk
from ..models.analytic.vanna_volga import vanna_volga_price
from ..models.analytic.variance import replicate_variance
from ..payoff.compile import CLeg, CPeriod, CProduct


class NotAnalytic(Exception):
    pass


class _LazySurf:
    """Поверхность строится только при первом обращении (форварды её не требуют)."""

    def __init__(self, fn):
        self._fn = fn
        self._s = None

    def __getattr__(self, item):
        if self._s is None:
            self._s = self._fn()
        return getattr(self._s, item)


@dataclass
class AnalyticResult:
    value: float
    items: list[dict[str, Any]] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    measure: str = "risk_neutral"


def _t(ref: date, d: date) -> float:
    return (d - ref).days / 365.0


class AnalyticEngine:
    def __init__(self, ctx, vol_model: str = "auto"):
        self.ctx = ctx
        self.vol_model = vol_model

    # ================================================================= общее
    def price(self, trade: Trade, cp: CProduct) -> AnalyticResult:
        if cp.modifiers:
            if all(isinstance(m, ExerciseMod) for m in cp.modifiers) and len(cp.modifiers) == 1 \
                    and len(cp.modifiers[0].dates) == 1 and all(l.is_rate for l in cp.legs):
                return self._european_swaption(trade, cp, cp.modifiers[0])
            raise NotAnalytic("модификаторы уровня сделки требуют Монте-Карло/дерева")
        self.trade = trade
        self.cp = cp
        self.ref = cp.ref_date
        res = AnalyticResult(0.0)
        for li, leg in enumerate(cp.legs):
            if isinstance(leg.observable, WeatherObs):
                return self._weather(trade, cp)
            for p in leg.periods:
                if p.payment <= self.ref:
                    continue
                for ci, c in enumerate(leg.components):
                    v, meth, extra = self._component(leg, p, c, ci)
                    res.value += v
                    res.items.append({"leg": leg.name, "period": p.idx, "fixing": p.fixing.isoformat(),
                                      "payment": p.payment.isoformat(), "component": c.kind, "label": c.label,
                                      "pv": v, "method": meth, **extra})
            v_n = self._notional_flows(leg)
            if v_n:
                res.value += v_n
                res.items.append({"leg": leg.name, "component": "notional", "pv": v_n, "method": "дисконтирование"})
        if any(isinstance(l.observable, WeatherObs) for l in cp.legs):
            res.measure = "historical"
        return res

    # ------------------------------------------------------------------ дисконтирование
    def _df(self, ccy: str, d: date, leg: CLeg | None = None) -> float:
        """PV в валюте отчёта единицы ``ccy``, выплачиваемой в дату d (с квантованием ноги)."""
        rep = self.trade.report_currency
        disc = self.ctx.discount_curve(rep, self.trade.collateral.collateralized, t_max=_t(self.ref, d),
                                       override=self.trade.model.discount_override)
        t = _t(self.ref, d)
        settle = leg.settlement if leg is not None else None
        q = settle.quanto if settle is not None else None
        if q is not None and ccy != settle.currency:
            if q.type == "composite":
                raise NotAnalytic("composite-квантование требует совместной модели актива и курса (Монте-Карло)")
            rate = q.rate if q.rate is not None else self.ctx.fx(q.pair).forward(d)
            conv = rate if ccy == q.pair[:3] else 1.0 / rate
            return conv * self._df(settle.currency, d)
        if ccy == rep:
            return float(disc.df(t))
        fx = self.ctx.fx(f"{ccy}{rep}", f"пересчёт {ccy} в {rep}")
        return fx.forward(d) * float(disc.df(t))

    def _notional_flows(self, leg: CLeg) -> float:
        ex = leg.spec.exchange_notional
        if ex == "none":
            return 0.0
        if leg.spec.notional_reset:
            raise NotAnalytic("MtM-ресет номинала требует Монте-Карло")
        sign = 1.0 if (leg.components and leg.components[0].position == "long") else -1.0
        ps = leg.periods
        v = 0.0
        if ex in ("initial", "both") and ps[0].start > self.ref:
            v += -sign * ps[0].notional * self._df(leg.currency, ps[0].start, leg)
        if ex in ("final", "both"):
            for i, p in enumerate(ps):
                nxt = ps[i + 1].notional if i + 1 < len(ps) else 0.0
                if p.payment > self.ref and p.notional != nxt:
                    v += sign * (p.notional - nxt) * self._df(leg.currency, p.payment, leg)
        return v

    # ================================================================= компоненты
    def _component(self, leg: CLeg, p: CPeriod, c: Component, ci: int = 0) -> tuple[float, str, dict]:
        obs = leg.observable
        bar_idx = [i for i, m in enumerate(c.modifiers) if isinstance(m, BarrierMod)]
        self._label = f"{leg.name}:{ci}:{bar_idx[0]}" if bar_idx else f"{leg.name}:leg:0"
        sign = 1.0 if c.position == "long" else -1.0
        mult = c.notional_multiplier
        mods = list(leg.modifiers) + list(c.modifiers)
        for m in mods:
            if isinstance(m, LeverageMod):
                if m.when == "always":
                    mult *= m.factor
                elif c.kind in ("put", "digital_put") and m.when == "below" and m.threshold == c.strike:
                    mult *= m.factor
                elif c.kind in ("call", "digital_call") and m.when == "above" and m.threshold == c.strike:
                    mult *= m.factor
                else:
                    raise NotAnalytic("условное плечо требует Монте-Карло")
        other = [m for m in mods if not isinstance(m, (LeverageMod, BarrierMod, AveragingMod, CapFloorMod))]
        if other:
            raise NotAnalytic(f"модификатор {other[0].type} требует Монте-Карло")
        scale = sign * p.notional * mult
        if isinstance(obs, (AssetObs,)) or (obs is not None and obs.type == "performance" and obs.initial is not None):
            v, meth, extra = self._asset_component(leg, p, c, mods)
        elif isinstance(obs, SpreadObs):
            v, meth, extra = self._spread_component(leg, p, c, mods)
        elif isinstance(obs, RateObs):
            v, meth, extra = self._rate_component(leg, p, c, mods)
        elif isinstance(obs, CPIObs):
            v, meth, extra = self._cpi_component(leg, p, c, mods)
        elif isinstance(obs, CreditObs):
            v, meth, extra = self._credit_component(leg, p, c, mods)
        elif isinstance(obs, RealizedVarObs):
            v, meth, extra = self._variance_component(leg, p, c, mods)
        elif obs is None and c.kind in ("fixed", "fixed_compounded", "cash", "redemption") and not mods:
            df = self._df(leg.currency, p.payment, leg)
            amt = {"fixed": (c.rate or 0.0) * p.tau, "fixed_compounded": (1 + (c.rate or 0.0)) ** p.tau - 1}.get(
                c.kind, c.payout if c.payout is not None else 1.0)
            v, meth, extra = amt * df, "детерминированный поток", {}
        else:
            raise NotAnalytic(f"наблюдаемая {getattr(obs, 'type', None)} не покрывается аналитикой")
        return scale * v, meth, {**extra, "unit_pv": v}

    # ------------------------------------------------------------------ активы
    def _asset_ctx(self, leg: CLeg, p: CPeriod):
        obs = leg.observable
        name = obs.name
        spec = self.trade.underlyings[name]
        aid = spec.id
        cls = spec.asset_class
        T = max(_t(self.ref, p.fixing), 0.0)
        if cls == "fx":
            fx = self.ctx.fx(aid, f"форвард {aid}")
            S0 = fx.spot_today()
            # фиксинг на дату D (курс ЦБ на D устанавливается накануне)
            from ..core.calendars import get_calendar
            lag = spec.fixing.lag_days
            fixd = get_calendar(spec.fixing.calendar or "RU").advance_business_days(p.fixing, lag) if lag else p.fixing
            T = max(_t(self.ref, fixd), 0.0)
            F = fx.forward_t(T + (fx.spot_date - fx.ref_date).days / 365.0)[0]
            surf = _LazySurf(lambda a=aid: self.ctx.fx_vol(a)) if T > 0 else None
        elif cls == "equity":
            fwd = self.ctx.asset_forward_fn(aid)
            eq = self.ctx.equity(aid, f"спот {aid}")
            S0 = eq.spot * eq.shock
            F = float(fwd(np.array([T]))[0])
            surf = _LazySurf(lambda a=aid: self.ctx.asset_vol(a)) if T > 0 else None
        elif cls == "commodity":
            cc = self.ctx.commodity(aid, f"форвард {aid}")
            if spec.contract_month:
                y, m = map(int, spec.contract_month.split("-"))
                F = cc.forward_month((y, m))
            else:
                F = cc.forward(p.fixing)
            S0 = F
            surf = _LazySurf(lambda a=aid: self.ctx.asset_vol(a)) if T > 0 else None
            if not (spec.tradeable_hedge if spec.tradeable_hedge is not None else cc.tradeable_hedge):
                self.ctx.tracker.warn(f"{aid}: нет торгуемого хеджа — риск-нейтральная оценка некорректна, "
                                      f"результат следует читать как оценку по исторической мере")
        else:
            raise NotAnalytic(f"класс {cls} для наблюдаемой asset")
        if obs.type == "performance":
            F = F / obs.initial
            S0 = S0 / obs.initial
        return aid, cls, S0, F, T, surf, spec

    def _known_fixing(self, spec, d: date) -> float | None:
        if d < self.ref or (d == self.ref and self.ctx.has_fixing(spec.id, spec.fixing.source, d)):
            return self.ctx.fixing(spec.id, spec.fixing.source, d, f"фиксинг {spec.id} ({spec.fixing.source})")
        return None

    def _asset_component(self, leg: CLeg, p: CPeriod, c: Component, mods) -> tuple[float, str, dict]:
        obs = leg.observable
        spec = self.trade.underlyings[obs.name]
        df = self._df(leg.currency, p.payment, leg)
        avg = next((m for m in mods if isinstance(m, AveragingMod)), None)
        barriers = [m for m in mods if isinstance(m, BarrierMod)]
        capfl = [m for m in mods if isinstance(m, CapFloorMod)]
        if capfl:
            raise NotAnalytic("кэп/флор на выплату по активу — Монте-Карло")
        K = c.strike
        kind = c.kind
        if avg is not None and p.obs_dates:
            if barriers:
                raise NotAnalytic("усреднение с барьером — Монте-Карло")
            return self._asian(leg, p, c, avg, df)
        known = self._known_fixing(spec, p.fixing)
        if known is not None and not barriers:
            x = known / (obs.initial if obs.type == "performance" else 1.0)
            return self._intrinsic(c, x) * df, "фиксинг известен", {"fixing": known}
        aid, cls, S0, F, T, surf, _ = self._asset_ctx(leg, p)
        if kind == "forward":
            if barriers:
                call = self._barrier_opt(c, "call", K, barriers, leg, p, S0, F, T, surf, df)
                put = self._barrier_opt(c, "put", K, barriers, leg, p, S0, F, T, surf, df)
                return c.gearing * (call[0] - put[0]), call[1], {"call": call[0], "put": put[0]}
            return c.gearing * (F - K) * df, "форвард по кривой", {"forward": F}
        if kind == "asset":
            if barriers:
                raise NotAnalytic("asset-or-nothing с барьером — Монте-Карло")
            return c.gearing * F * df, "форвард", {"forward": F}
        if kind in ("cash", "redemption"):
            pay = c.payout if c.payout is not None else 1.0
            if not barriers:
                return pay * df, "дисконтирование", {}
            return self._touch(c, pay, barriers, leg, p, S0, F, T, surf, df)
        if kind in ("call", "put"):
            if barriers:
                v, meth, extra = self._barrier_opt(c, kind, K, barriers, leg, p, S0, F, T, surf, df)
                if c.cap_strike is not None:
                    v2, *_ = self._barrier_opt(c, "call", c.cap_strike, barriers, leg, p, S0, F, T, surf, df)
                    v -= v2
                return c.gearing * v, meth, extra
            cp = 1 if kind == "call" else -1
            vol = float(surf.vol(K, T))
            surf.register(self.ctx.tracker, T, K)
            v = float(black(F, K, T, vol, df, cp))
            if c.cap_strike is not None:
                v -= float(black(F, c.cap_strike, T, float(surf.vol(c.cap_strike, T)), df, 1))
            return c.gearing * v, "Garman-Kohlhagen, вола на страйке (улыбка)", {"forward": F, "vol": vol, "T": T}
        if kind in ("digital_call", "digital_put", "range_digital"):
            if barriers:
                raise NotAnalytic("цифровой опцион с барьером — Монте-Карло")
            pay = c.payout if c.payout is not None else 1.0
            if kind == "range_digital":
                v = self._digital(F, c.lower, T, surf, df, 1) - self._digital(F, c.upper, T, surf, df, 1)
            else:
                v = self._digital(F, K, T, surf, df, 1 if kind == "digital_call" else -1)
            return pay * v, "цифровой: Блэк + поправка на наклон улыбки", {"forward": F}
        raise NotAnalytic(f"компонент {kind} по активу")

    def _intrinsic(self, c: Component, x: float) -> float:
        K = c.strike
        k = c.kind
        if k == "forward":
            return c.gearing * (x - K)
        if k == "call":
            v = max(x - K, 0)
            if c.cap_strike is not None:
                v -= max(x - c.cap_strike, 0)
            return c.gearing * v
        if k == "put":
            return c.gearing * max(K - x, 0)
        if k == "digital_call":
            return (c.payout or 1.0) * (x > K)
        if k == "digital_put":
            return (c.payout or 1.0) * (x < K)
        if k == "range_digital":
            return (c.payout or 1.0) * (c.lower <= x <= c.upper)
        if k in ("cash", "redemption"):
            return c.payout if c.payout is not None else 1.0
        if k == "asset":
            return c.gearing * x
        raise NotAnalytic(k)

    def _digital(self, F, K, T, surf, df, cp) -> float:
        surf.register(self.ctx.tracker, T, K)
        vol = float(surf.vol(K, T))
        h = K * 1e-4
        dvdk = (float(surf.vol(K + h, T)) - float(surf.vol(K - h, T))) / (2 * h)
        from ..models.analytic.black import black_greeks
        vega = float(black_greeks(F, K, T, vol, df, 1)["vega"])
        base = float(black_digital(F, K, T, vol, df, cp))
        # −∂C/∂K = DF·N(d2) − vega·∂σ/∂K (колл); пут — дополнение
        return base - cp * vega * dvdk

    def _vv_inputs(self, S0, F, T, surf, df):
        rd = -np.log(df) / T if T > 0 else 0.0
        rf = rd - np.log(F / S0) / T if T > 0 else 0.0
        (kp, ka, kc), (vp, va, vc) = surf.pillars_at(T)
        return rd, rf, (kp, ka, kc), (vp, va, vc)

    def _barrier_window_ok(self, m: BarrierMod, leg: CLeg, p: CPeriod) -> None:
        ws = m.window_start or (p.start if m.scope == "period" else self.cp.start)
        we = m.window_end or p.fixing
        if we < p.fixing:
            raise NotAnalytic("оконный барьер (окно заканчивается до экспирации) — Монте-Карло/PDE")
        if ws > self.ref:
            raise NotAnalytic("барьер с отложенным началом окна — Монте-Карло/PDE")
        if m.soft_width:
            raise NotAnalytic("soft barrier — Монте-Карло")

    def _bar_level(self, m: BarrierMod, S0, T, vol) -> tuple[float | None, float | None, float | None, str]:
        """Уровни с BGK-сдвигом для дискретного наблюдения."""
        note = ""
        if m.monitoring == "discrete":
            dt = {"daily": 1 / 252, "fixings": None}.get(m.observation)
            if dt is None:
                from ..core.dates import Tenor
                dt = Tenor.parse(m.observation).approx_years if m.observation not in ("fixings",) else None
            if dt is None:
                raise NotAnalytic("дискретный барьер по датам фиксингов — Монте-Карло")
            sh = lambda H: bgk_shift(H, S0, vol, dt)
            note = f"дискретное наблюдение: сдвиг BGK 0.5826·σ·√Δt (Δt={dt:.4f})"
        else:
            sh = lambda H: H
        if m.lower is not None or m.upper is not None:
            return None, sh(m.lower) if m.lower else None, sh(m.upper) if m.upper else None, note
        return sh(m.level), None, None, note

    def _past_knocked(self, m: BarrierMod, label: str) -> bool:
        return bool(self.trade.state.knocked.get(label, False))

    def _barrier_opt(self, c, kind, K, barriers, leg, p, S0, F, T, surf, df):
        if len(barriers) > 1:
            raise NotAnalytic("несколько барьеров на компоненте — Монте-Карло")
        m = barriers[0]
        if m.monitoring == "terminal":
            raise NotAnalytic("терминальный барьер — Монте-Карло")
        self._barrier_window_ok(m, leg, p)
        cp = 1 if kind == "call" else -1
        if T <= 0:
            raise NotAnalytic("барьер на дату экспирации — требуется история наблюдений")
        rd, rf, pk, pv = self._vv_inputs(S0, F, T, surf, df)
        atm = pv[1]
        surf.register(self.ctx.tracker, T, K, "волатильность для vanna-volga (столпы 25Δ/ATM)")
        H, L, U, note = self._bar_level(m, S0, T, atm)
        reb = m.rebate.amount if m.rebate else 0.0
        at_hit = bool(m.rebate and m.rebate.timing == "at_hit")
        if H is not None:
            ko = vanna_volga_price(lambda s, v: barrier_price(s, K, H, T, rd, rf, v, cp, m.direction, "out", 0.0), S0, T, rd, rf,
                                   atm, pk, pv, survival=no_touch_prob(S0, H, T, rd, rf, atm, m.direction))
            van = float(black(F, K, T, float(surf.vol(K, T)), df, cp))
            ko_v = ko["price"]
            if self._past_knocked(m, self._label):
                ko_v = 0.0
            reb_v = 0.0
            if reb:
                ot = touch_price(S0, H, T, rd, rf, atm, m.direction, "in", reb, at_hit)
                reb_v = ot if m.kind == "out" else touch_price(S0, H, T, rd, rf, atm, m.direction, "out", reb)
            v = (ko_v if m.kind == "out" else max(van - ko_v, 0.0)) + reb_v
            flat = barrier_price(S0, K, H, T, rd, rf, atm, cp, m.direction, m.kind, reb, at_hit)
            extra = {"forward": F, "barrier_effective": H, "bs_flat_atm": flat, "vv_correction": ko["correction"],
                     "survival": ko["survival_weight"], "vanilla": van}
            return v, "Reiner-Rubinstein + vanna-volga" + (f"; {note}" if note else ""), extra
        # двойной барьер
        if L is None or U is None:
            raise NotAnalytic("двойной барьер требует обоих уровней")
        dnt = double_no_touch_prob(S0, L, U, T, rd, rf, atm)
        ko = vanna_volga_price(lambda s, v: double_barrier_ko(s, K, L, U, T, rd, rf, v, cp), S0, T, rd, rf, atm, pk, pv, dnt)
        van = float(black(F, K, T, float(surf.vol(K, T)), df, cp))
        v = ko["price"] if m.kind == "out" else max(van - ko["price"], 0.0)
        return v, "Ikeda-Kunitomo + vanna-volga" + (f"; {note}" if note else ""), \
            {"forward": F, "lower": L, "upper": U, "survival": dnt, "vanilla": van}

    def _touch(self, c, pay, barriers, leg, p, S0, F, T, surf, df):
        if len(barriers) > 1:
            raise NotAnalytic("несколько барьеров — Монте-Карло")
        m = barriers[0]
        self._barrier_window_ok(m, leg, p)
        rd, rf, pk, pv = self._vv_inputs(S0, F, T, surf, df)
        atm = pv[1]
        surf.register(self.ctx.tracker, T, None, "волатильность для vanna-volga")
        H, L, U, note = self._bar_level(m, S0, T, atm)
        if H is not None:
            at_hit = bool(m.rebate and m.rebate.timing == "at_hit") if m.kind == "in" else False
            nt = no_touch_prob(S0, H, T, rd, rf, atm, m.direction)
            fn = lambda s, v: touch_price(s, H, T, rd, rf, v, m.direction, "out", 1.0)
            vv = vanna_volga_price(fn, S0, T, rd, rf, atm, pk, pv, survival=nt)
            nt_v = vv["price"]
            if m.kind == "out":
                v = pay * nt_v
                meth = "no-touch: аналитика + vanna-volga"
            else:
                if at_hit:
                    v = pay * (touch_price(S0, H, T, rd, rf, atm, m.direction, "in", 1.0, True)
                               + (vv["bs_atm"] - nt_v))
                else:
                    v = pay * (df - nt_v)
                meth = "one-touch: аналитика + vanna-volga"
            return v, meth + (f"; {note}" if note else ""), {"no_touch_vv": nt_v / max(df, 1e-12), "no_touch_flat": nt}
        dnt_flat = double_no_touch(S0, L, U, T, rd, rf, atm, 1.0)
        fn = lambda s, v: double_no_touch(s, L, U, T, rd, rf, v, 1.0)
        vv = vanna_volga_price(fn, S0, T, rd, rf, atm, pk, pv, survival=dnt_flat / df)
        dnt = vv["price"]
        v = pay * dnt if m.kind == "out" else pay * (df - dnt)
        return v, "double-no-touch (Hui) + vanna-volga", {"dnt_flat": dnt_flat, "dnt_vv": dnt}

    def _asian(self, leg, p, c, avg, df):
        if c.kind not in ("call", "put", "forward"):
            raise NotAnalytic("азиатская выплата не call/put/forward")
        if avg.average_of == "strike":
            raise NotAnalytic("усреднение страйка — Монте-Карло")
        spec = self.trade.underlyings[leg.observable.name]
        w = np.asarray(p.obs_weights) if p.obs_weights else np.full(len(p.obs_dates), 1 / len(p.obs_dates))
        known_part, fut_d, fut_w = 0.0, [], []
        for d, wi in zip(p.obs_dates, w):
            fx = self._known_fixing(spec, d)
            if fx is not None:
                known_part += wi * fx
            else:
                fut_d.append(d)
                fut_w.append(wi)
        sub = CPeriod(p.idx, p.start, p.end, p.fixing, p.payment, p.tau, p.notional)
        fwds, ts = [], []
        aid, cls, S0, F_last, T_last, surf, _ = self._asset_ctx(leg, sub)
        for d in fut_d:
            sub2 = CPeriod(p.idx, p.start, p.end, d, p.payment, p.tau, p.notional)
            _, _, _, F, T, _, _ = self._asset_ctx(leg, sub2)
            fwds.append(F)
            ts.append(max(T, 1e-6))
        if c.kind == "forward":
            return c.gearing * (known_part + float(np.dot(fut_w, fwds)) - c.strike) * df, "форвард на среднее", {}
        cp = 1 if c.kind == "call" else -1
        K = c.strike
        if surf is not None:
            surf.register(self.ctx.tracker, max(ts) if ts else 0.0, K)
        tv = (lambda t, s=surf, k=K: float(s.vol(k, t)) ** 2 * t) if surf is not None else (lambda t: 0.0)
        if avg.method == "geometric":
            if known_part:
                raise NotAnalytic("геометрическое среднее с прошедшими фиксингами — Монте-Карло")
            v = geometric_asian(fwds, ts, fut_w, tv, K, df, cp)
            return c.gearing * v, "геометрическое среднее: точная формула", {}
        r = arithmetic_asian(fwds, ts, fut_w, tv, K, df, cp, known_part)
        return c.gearing * r["price"], "азиатский: моменты (Turnbull-Wakeman/Levy), вола на страйке", \
            {"avg_forward": r["M1"], "sigma_eff": r["sigma_eff"]}

    def _spread_component(self, leg, p, c, mods):
        if any(isinstance(m, (BarrierMod, AveragingMod)) for m in mods):
            raise NotAnalytic("спред с барьером/усреднением — Монте-Карло")
        obs = leg.observable
        df = self._df(leg.currency, p.payment, leg)
        terms = obs.terms
        Fs, vols, ids = [], [], []
        T = max(_t(self.ref, p.fixing), 1e-6)
        for term in terms:
            spec = self.trade.underlyings[term["name"]]
            sub_leg = CLeg(leg.name, leg.spec, AssetObs(name=term["name"]), [p], leg.currency, leg.settlement, [], [], leg.daycount)
            aid, cls, S0, F, T_, surf, _ = self._asset_ctx(sub_leg, p)
            Fs.append(F * float(term.get("coef", 1.0)))
            vols.append(surf.atm_vol(T) if (surf is not None and c.kind != "forward") else 0.0)
            ids.append(aid)
        lin = sum(Fs)
        if c.kind == "forward":
            return c.gearing * (lin - c.strike) * df, "линейная комбинация форвардов", {"spread_forward": lin}
        if len(terms) != 2 or c.kind not in ("call", "put"):
            raise NotAnalytic("спред более чем на два базиса — Монте-Карло")
        rho = self.ctx.correlation(ids[0], ids[1], "корреляция для спред-опциона")
        a, b = Fs[0], -Fs[1]
        if b <= 0 or a <= 0:
            raise NotAnalytic("спред-опцион с нестандартными знаками — Монте-Карло")
        cp = 1 if c.kind == "call" else -1
        try:
            v = kirk(a, b, c.strike, T, vols[0], vols[1], rho, df, cp)
        except ValueError as e:
            raise NotAnalytic(str(e))
        return c.gearing * v, "Кирк (Блэк на спред неприменим)", {"spread_forward": lin, "rho": rho}

    # ------------------------------------------------------------------ ставки
    def _period_rate(self, leg: CLeg, obs: RateObs, p: CPeriod) -> tuple[float, float, str]:
        """(форвардная ставка периода, эффективное время для волатильности, конвенция)."""
        idx = self.ctx.index(obs.index)
        comp = obs.compounding if obs.compounding != "default" else idx.get("compounding", "compounded")
        fc = self.ctx.forecast_curve(obs.index, t_max=_t(self.ref, p.end))
        ts, te = _t(self.ref, p.start), _t(self.ref, p.end)
        tau = te - ts
        if comp == "term":
            from ..core.dates import Tenor
            ten = Tenor.parse(obs.tenor or idx.get("tenor", "3M")).approx_years
            tf = _t(self.ref, p.fixing)
            if p.fixing < self.ref:
                if self.ctx.has_fixing(obs.index, "CBR", p.fixing):
                    return self.ctx.fixing(obs.index, "CBR", p.fixing), 0.0, comp
                raise NotAnalytic(f"нет исторического фиксинга {obs.index} на {p.fixing}")
            r = float(fc.fwd_simple(tf, tf + ten))
            if idx.get("legacy"):
                r += float(idx.get("spread_adjustment", 0.0))
            return r, tf, comp
        if ts < 0:
            # начисление уже идёт: прошедшая часть — по историческим дневным фиксингам
            past = self._past_overnight(obs.index, p.start, self.ref)
            fut = float(fc.fwd_average(0.0, te)) if comp == "simple_average" else float(np.log1p(fc.fwd_simple(0.0, te) * te) / te if te > 0 else 0.0)
            w_past = (-ts) / tau
            if comp == "simple_average":
                r = w_past * past + (1 - w_past) * 365.0 * np.expm1(fut / 365.0)
            else:
                growth = (1 + past * (-ts)) * float(np.exp(-fc.logdf_t(te)))
                r = (growth - 1) / tau
            return float(r), max(te / 3.0, 0.0), comp
        if comp == "simple_average":
            r = 365.0 * np.expm1(float(fc.fwd_average(ts, te)) / 365.0)
        else:
            r = float(fc.fwd_simple(ts, te))
        return float(r), ts + tau / 3.0, comp

    def _past_overnight(self, index: str, d0: date, d1: date) -> float:
        ds = self.ctx.snapshot.dataset("fixings").data.get("CBR", {}).get(index.upper(), {})
        vals = [v for k, v in ds.items() if d0.isoformat() <= k < d1.isoformat()]
        if not vals:
            self.ctx.tracker.warn(f"{index}: нет исторических фиксингов за {d0}–{d1}, использована текущая ставка")
            return float(self.ctx.forecast_curve(index).inst_fwd(0.0))
        self.ctx.tracker.record(UsedInput(f"FIX.CBR.{index}.{d0}..{d1}", float(np.mean(vals)),
                                          self.ctx.snapshot.dataset("fixings").provenance, "прошедшая часть периода начисления"))
        return float(np.mean(vals))

    def _rate_component(self, leg, p, c, mods):
        obs = leg.observable
        if any(isinstance(m, AveragingMod) for m in mods):
            raise NotAnalytic("усреднение на ставке — Монте-Карло")
        df = self._df(leg.currency, p.payment, leg)
        k = c.kind
        if k == "fixed":
            return (c.rate or 0.0) * p.tau * df, "фиксированный купон", {}
        if k == "fixed_compounded":
            return ((1 + (c.rate or 0.0)) ** p.tau - 1) * df, "фиксированный (сложный процент)", {}
        if k in ("cash", "redemption"):
            return (c.payout if c.payout is not None else 1.0) * df, "дисконтирование", {}
        F, Tv, comp = self._period_rate(leg, obs, p)
        barriers = [m for m in mods if isinstance(m, BarrierMod)]
        capfl = [m for m in mods if isinstance(m, CapFloorMod)]
        irv = None
        need_vol = k in ("cap", "floor", "digital_call", "digital_put", "range_digital") or barriers or capfl
        if need_vol and Tv > 0:
            fc_id = self.ctx.index(obs.index)["curve"]
            irv = self.ctx.ir_vol(fc_id, Tv, f"нормальная волатильность {obs.index}")

        def nvol(K):
            return irv.normal_vol(F, K, Tv, p.tau) if irv is not None else 0.0

        def caplet(K, cp):
            if Tv <= 0:
                return max(cp * (F - K), 0.0)
            return float(bachelier(F, K, Tv, nvol(K), 1.0, cp))

        def digital(K, cp):
            if Tv <= 0:
                return float(cp * (F - K) > 0)
            from ..models.analytic.black import bachelier_digital
            return float(bachelier_digital(F, K, Tv, nvol(K), 1.0, cp))

        x_eff = c.gearing * F + c.spread
        extra = {"forward_rate": F, "compounding": comp}
        if barriers:
            m = barriers[0]
            if len(barriers) > 1 or m.monitoring not in ("terminal",) or k not in ("cap", "floor", "float"):
                raise NotAnalytic("барьер на ставку с наблюдением на пути — Монте-Карло (Hull-White)")
            # KO при фиксинге за барьером в тот же день: разложение на ванильные и цифровые каплеты
            B = m.level
            if m.direction == "up" and k == "cap" and m.kind == "out":
                K = c.strike
                v = caplet(K, 1) - caplet(B, 1) - (B - K) * digital(B, 1)
                return v * p.tau * df, "каплет с отключением при фиксинге: разложение (Башелье)", extra
            raise NotAnalytic("конфигурация барьера на ставку — Монте-Карло")
        if k == "float":
            v = x_eff
            meth = "форвард по прогнозной кривой"
            for m in capfl:
                if m.local_cap is not None:
                    v -= caplet((m.local_cap - c.spread) / c.gearing, 1) * c.gearing
                if m.local_floor is not None:
                    v += caplet((m.local_floor - c.spread) / c.gearing, -1) * c.gearing
                if m.global_cap is not None or m.global_floor is not None:
                    raise NotAnalytic("глобальный кэп/флор — Монте-Карло")
                meth = "плавающая ставка со встроенным кэпом/флором (Башелье)"
            return v * p.tau * df, meth, extra
        if k == "cap":
            return c.gearing * caplet((c.strike - c.spread) / c.gearing, 1) * p.tau * df, "каплет (Башелье)", \
                {**extra, "normal_vol_bp": nvol(c.strike) * 1e4}
        if k == "floor":
            return c.gearing * caplet((c.strike - c.spread) / c.gearing, -1) * p.tau * df, "флорлет (Башелье)", \
                {**extra, "normal_vol_bp": nvol(c.strike) * 1e4}
        if k in ("digital_call", "digital_put"):
            return (c.payout or 1.0) * digital(c.strike, 1 if k == "digital_call" else -1) * df, "цифровой каплет", extra
        if k == "range_digital":
            return (c.payout or 1.0) * (digital(c.lower, 1) - digital(c.upper, 1)) * df, "диапазонный цифровой", extra
        raise NotAnalytic(f"компонент {k} на ставке")

    def _european_swaption(self, trade: Trade, cp: CProduct, m: ExerciseMod) -> AnalyticResult:
        self.trade, self.cp, self.ref = trade, cp, cp.ref_date
        ex = m.dates[0]
        T = _t(self.ref, ex)
        und = AnalyticResult(0.0)
        fixed_ann = 0.0
        fixed_rate = None
        fixed_sign = 0.0
        float_pv = 0.0
        for leg in cp.legs:
            for p in leg.periods:
                if p.start < ex:
                    continue
                for c in leg.components:
                    sign = 1.0 if c.position == "long" else -1.0
                    df = self._df(leg.currency, p.payment, leg)
                    if c.kind == "fixed":
                        fixed_ann += p.notional * p.tau * df
                        fixed_rate = c.rate
                        fixed_sign = sign
                    elif c.kind == "float":
                        F, _, _ = self._period_rate(leg, leg.observable, p)
                        float_pv += sign * p.notional * (F * c.gearing + c.spread) * p.tau * df
                    else:
                        raise NotAnalytic("свопцион на нестандартный своп")
        if fixed_rate is None or fixed_ann <= 0:
            raise NotAnalytic("свопцион без фиксированной ноги")
        S = abs(float_pv) / fixed_ann
        payer = fixed_sign < 0   # клиент платит фиксированную ставку
        cpf = 1 if payer else -1
        idx_curve = self.ctx.index(cp.legs[0].observable.index if cp.legs[0].is_rate else cp.legs[1].observable.index)["curve"]
        tenor = _t(ex, cp.last_payment)
        irv = self.ctx.ir_vol(idx_curve, T, "нормальная волатильность свопциона")
        nv = irv.normal_vol(S, fixed_rate, T, tenor)
        v = fixed_ann * float(bachelier(S, fixed_rate, T, nv, 1.0, cpf))
        if m.holder == "bank":
            v = -v
        res = AnalyticResult(v)
        res.items.append({"component": "swaption", "pv": v, "method": "Башелье на своп-ставку (физическая поставка)",
                          "swap_rate": S, "strike": fixed_rate, "normal_vol_bp": nv * 1e4, "annuity": fixed_ann,
                          "payer": payer})
        return res

    # ------------------------------------------------------------------ ИПЦ
    def _cpi_component(self, leg, p, c, mods):
        obs: CPIObs = leg.observable
        if mods and any(not isinstance(m, CapFloorMod) for m in mods):
            raise NotAnalytic("модификаторы на ИПЦ — Монте-Карло")
        cpi = self.ctx.cpi(obs.name, "индексация по ИПЦ")
        df = self._df(leg.currency, p.payment, leg)
        k = c.kind
        if k == "fixed_compounded":
            return ((1 + (c.rate or 0.0)) ** p.tau - 1) * df, "фиксированная нога (сложный процент)", {}
        if k == "fixed":
            return (c.rate or 0.0) * p.tau * df, "фиксированная нога", {}
        i_t = cpi.index_for_date(p.fixing, obs.lag_months, obs.interpolate, obs.version)
        if obs.measure == "ratio_to_base":
            base = obs.base_index or cpi.index_for_date(self.cp.start, obs.lag_months, obs.interpolate, obs.version)
            X = i_t / base
            if k == "index_ratio":
                return c.gearing * (X - 1.0) * df, "индексация ИПЦ: прогнозная кривая с лагом и сезонностью", \
                    {"index": i_t, "base": base, "ratio": X}
            if k in ("redemption", "cash"):
                return (c.payout or 1.0) * X * df, "индексируемый номинал (ОФЗ-ИН)", {"ratio": X}
            if k in ("fixed",):
                return (c.rate or 0.0) * p.tau * X * df, "купон на индексируемый номинал", {"ratio": X}
            raise NotAnalytic(f"{k} на ИПЦ (ratio)")
        # yoy
        from ..curves.inflation import add_m
        d_prev = date(*add_m((p.fixing.year, p.fixing.month), -12), min(p.fixing.day, 28))
        i_prev = cpi.index_for_date(d_prev, obs.lag_months, obs.interpolate, obs.version)
        yoy = i_t / i_prev - 1
        T = _t(self.ref, p.fixing)
        vol_yoy = self._yoy_vol(cpi)
        # поправка на выпуклость YoY — модельный параметр (без модели Джарроу-Йилдирима)
        cfg = self.ctx.config.get("inflation", {}).get(obs.name, {})
        conv_rate = float(cfg.get("yoy_convexity_per_year", 0.0002))
        conv = conv_rate * max(T - 1.0, 0.0)
        self.ctx.tracker.record(UsedInput("model:YOY_CONVEXITY", conv_rate, Provenance(
            "поправка на выпуклость YoY-инфляции", None, DataKind.MODEL, note="доля в год сверх первого года"),
            "поправка на выпуклость YoY"))
        F = yoy + conv
        if k == "float":
            return (c.gearing * F + c.spread) * p.tau * df, "YoY: прогнозная кривая ИПЦ", {"yoy": F}
        if k in ("cap", "floor"):
            cpf = 1 if k == "cap" else -1
            v = float(bachelier(F, c.strike, max(T, 1e-6), vol_yoy, df, cpf))
            return v * p.tau, "кэп/флор на годовую инфляцию (Башелье, историческая вола)", {"yoy": F, "vol": vol_yoy}
        raise NotAnalytic(f"{k} на YoY")

    def _yoy_vol(self, cpi) -> float:
        keys = sorted(cpi.history_revised)
        vals = np.array([cpi.history_revised[k] for k in keys])
        if len(vals) < 25:
            return 0.01
        yoy = vals[12:] / vals[:-12] - 1
        v = float(np.std(np.diff(yoy[-60:])) * np.sqrt(12))
        self.ctx.tracker.record(UsedInput("hist:CPI_YOY_VOL", round(v, 5),
                                          Provenance("историческая волатильность годовой инфляции (ИПЦ Росстата)", None,
                                                     DataKind.HISTORICAL), "волатильность YoY-инфляции"))
        return max(v, 1e-4)

    # ------------------------------------------------------------------ кредит
    def _credit_component(self, leg, p, c, mods):
        obs: CreditObs = leg.observable
        if mods:
            raise NotAnalytic("модификаторы на кредитной ноге — Монте-Карло")
        hc = self.ctx.credit_curve(obs.entity, f"кривая дефолта {obs.entity}")
        R = obs.recovery if obs.recovery is not None else hc.recovery
        ts, te = max(_t(self.ref, p.start), 0.0), _t(self.ref, p.payment)
        df = self._df(leg.currency, p.payment, leg)
        k = c.kind
        q_end = float(hc.survival(te)[0])
        grid = np.linspace(ts, te, 9)
        rep = self.trade.report_currency
        disc = self.ctx.discount_curve(rep, self.trade.collateral.collateralized)
        dq = -np.diff(hc.survival(grid))
        dfs = disc.df(0.5 * (grid[1:] + grid[:-1]))
        if leg.currency != rep:
            fx = self.ctx.fx(f"{leg.currency}{rep}")
            dfs = dfs * np.array([fx.forward_t(t)[0] for t in 0.5 * (grid[1:] + grid[:-1])])
        default_leg = float(np.sum(dq * dfs))
        if k in ("premium", "fixed", "coupon"):
            rate = c.rate or 0.0
            amt = rate * p.tau if k != "coupon" else rate
            accr = 0.5 * amt * default_leg if k == "premium" else 0.0
            return amt * q_end * df + accr, "премия × вероятность выживания (+ накопленная при дефолте)", \
                {"survival": q_end}
        if k == "protection":
            return (1 - R) * default_leg, "защита: (1−R)·∫DF dPD", {"pd_period": float(dq.sum()), "recovery": R}
        if k == "recovery":
            return R * default_leg, "восстановление при дефолте", {}
        if k in ("redemption", "cash"):
            return (c.payout if c.payout is not None else 1.0) * q_end * df, "погашение × выживание", {"survival": q_end}
        raise NotAnalytic(f"{k} на кредитной ноге")

    # ------------------------------------------------------------------ дисперсия
    def _variance_component(self, leg, p, c, mods):
        obs: RealizedVarObs = leg.observable
        if mods:
            raise NotAnalytic("модификаторы на вариансном свопе — Монте-Карло")
        if p.start < self.ref:
            raise NotAnalytic("сезонный вариансный своп (наблюдения уже идут) — Монте-Карло")
        spec = self.trade.underlyings[obs.name]
        sub = CLeg(leg.name, leg.spec, AssetObs(name=obs.name), [p], leg.currency, leg.settlement, [], [], leg.daycount)
        aid, cls, S0, F, T, surf, _ = self._asset_ctx(sub, p)
        surf.register(self.ctx.tracker, T, None, "репликация вариансного свопа")
        quoted = []
        for sl in surf.slices:
            if abs(sl.T - T) < 0.25 or sl is surf.slices[-1]:
                quoted = [pl.strike * F / sl.forward for pl in sl.pillars]
        rep = replicate_variance(F, T, lambda K: surf.vol(K, T), quoted or [F])
        df = self._df(leg.currency, p.payment, leg)
        if c.kind == "variance":
            v = (rep["fair_variance"] - c.strike) * df
        elif c.kind == "volatility":
            # поправка на выпуклость: модельная, через «вола волы» ~ 0.5·σ (допущение)
            from ..models.analytic.variance import vol_swap_convexity
            fv = rep["fair_variance"]
            vov = (0.5 * np.sqrt(fv)) ** 2 * fv * T  # Var(V) — модельное допущение
            ev = vol_swap_convexity(fv, vov)
            v = (ev - c.strike) * df
            rep["expected_vol"] = ev
            self.ctx.tracker.warn("Своп на волатильность: поправка на выпуклость использует модельную «волатильность волатильности»")
        else:
            raise NotAnalytic(c.kind)
        self.ctx.tracker.warn(f"Вариансный своп: ошибка репликации по доступным страйкам "
                              f"{rep['total_error_vol_pts']:+.2f} п. волатильности (дискретизация {rep['discretization_error']:.2e}, "
                              f"усечение {rep['truncation_error']:.2e} в дисперсии)")
        return v, "статическая репликация (Carr-Madan), ошибка дискретизации выведена", rep

    # ------------------------------------------------------------------ погода
    def _weather(self, trade: Trade, cp: CProduct) -> AnalyticResult:
        res = AnalyticResult(0.0, measure="historical")
        for leg in cp.legs:
            obs: WeatherObs = leg.observable
            ds = self.ctx._dataset(obs.dataset)
            vals = np.asarray(ds.data["values"], float)
            years = np.asarray(ds.data["years"], float)
            if obs.detrend and len(vals) > 5:
                b = np.polyfit(years, vals, 1)
                adj = vals + b[0] * (years.max() + 1 - years)
            else:
                adj = vals
            self.ctx.tracker.record(UsedInput(f"ds:{obs.dataset}", f"{len(vals)} лет", ds.provenance, "актуарная оценка"))
            for p in leg.periods:
                if p.payment <= cp.ref_date:
                    continue
                df = self._df(leg.currency, p.payment, leg)
                for c in leg.components:
                    sign = 1.0 if c.position == "long" else -1.0
                    tick = c.gearing
                    if c.kind == "call":
                        pay = np.maximum(adj - c.strike, 0) * tick
                    elif c.kind == "put":
                        pay = np.maximum(c.strike - adj, 0) * tick
                    elif c.kind == "forward":
                        pay = (adj - c.strike) * tick
                    else:
                        raise NotAnalytic(c.kind)
                    if c.cap_strike is not None:
                        pay = np.minimum(pay, c.cap_strike)
                    ev = float(np.mean(pay))
                    sd = float(np.std(pay, ddof=1))
                    v = sign * p.notional * ev * df
                    res.value += v
                    res.items.append({"leg": leg.name, "component": c.kind, "pv": v,
                                      "method": "актуарный burn analysis по детрендированной истории",
                                      "expected_payout": ev, "payout_std": sd, "years": len(vals)})
        self.ctx.tracker.warn("Погодный дериватив: нет торгуемого хеджа — оценка актуарная, в исторической мере, "
                              "без рыночной надбавки за риск")
        res.notes.append("оценка по исторической мере")
        return res
