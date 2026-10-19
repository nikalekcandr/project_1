"""Вычисление потоков композиционной выплаты на путях.

Модификаторы реализованы один раз и применяются к любому базису:
барьер (непрерывный с броуновским мостом / дискретный / терминальный,
одиночный и двойной, окно, ребейт при касании или в конце, soft barrier),
усреднение (по цене и по страйку, веса), накопление (accrual), целевое
погашение (три правила последнего платежа), плечо (с порогом включения),
локальные и глобальные кэпы/флоры, переустановка страйка, автоколл, память
купона, квантование (quanto / composite), право досрочного прекращения и
опцион на вход (LSMC — обратная индукция, не набор европейских опционов).

Все потоки — с точки зрения клиента. ``smoothing`` > 0 заменяет индикаторы
сглаженными (сигмоида) — для устойчивых греков при общих случайных числах.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np

from ..core.calendars import get_calendar
from ..core.schedule import roll_dates
from ..core.dates import BDC
from ..instruments.schema import (AccrualMod, AutocallMod, BarrierMod, CapFloorMod, Component,
                                  EarlyTerminationMod, ExerciseMod, LeverageMod, MemoryMod, StrikeResetMod, TargetMod)
from .compile import CLeg, CPeriod, CProduct


@dataclass
class Flow:
    leg: int
    comp: int
    period: int
    fixing: date
    payment: date
    start: date
    ccy: str
    amount: np.ndarray
    kind: str = "component"
    label: str = ""
    gain: np.ndarray | None = None       # положительная выплата на единицу номинала (для target)
    hit_dist: list[tuple[date, np.ndarray]] | None = None   # для ребейта при касании: (дата, вероятность касания)


class MarketView:
    """Интерфейс к путям/рынку, который использует вычислитель."""
    n: int
    ref: date

    def obs_matrix(self, obs, dates: list[date]) -> np.ndarray: ...  # (n, m)
    def obs_grid(self, obs, d0: date, d1: date) -> tuple[list[date], np.ndarray, np.ndarray | None]: ...
    def rate_period(self, obs, p: CPeriod) -> np.ndarray: ...
    def fx_value(self, pair: str, d: date, source: str) -> np.ndarray: ...
    def state_knocked(self, label: str) -> bool: ...
    def warn(self, msg: str) -> None: ...
    def df(self, ccy: str, d: date) -> np.ndarray | float: ...
    def state_vars(self, d: date) -> np.ndarray: ...


def _ind(x: np.ndarray, eps: float) -> np.ndarray:
    if eps <= 0:
        return (x > 0).astype(float)
    return 0.5 * (1 + np.tanh(x / (2 * eps)))


def _bb_cross(x0, x1, h, var, up: bool):
    """Вероятность пересечения уровня h броуновским мостом между x0 и x1 (лог-цены)."""
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        if up:
            a, b = h - x0, h - x1
        else:
            a, b = x0 - h, x1 - h
        p = np.exp(-2 * np.maximum(a, 0) * np.maximum(b, 0) / np.maximum(var, 1e-300))
    return np.where((a <= 0) | (b <= 0), 1.0, p)


@dataclass
class EvalResult:
    flows: list[Flow]
    pv_paths: np.ndarray                 # PV по путям (валюта отчёта)
    flow_pv: list[float]
    notes: list[str] = field(default_factory=list)
    exercise_info: dict[str, Any] = field(default_factory=dict)


class Evaluator:
    def __init__(self, product: CProduct, mv: MarketView, smoothing: float = 0.0):
        self.p = product
        self.mv = mv
        self.eps = smoothing
        self.ref = mv.ref

    # ------------------------------------------------------------------ барьеры
    def _window(self, m: BarrierMod, leg: CLeg, period: CPeriod | None) -> tuple[date, date]:
        if m.window_start:
            ws = m.window_start
        elif m.scope == "period" and period is not None:
            ws = period.start
        else:
            ws = self.p.start
        we = period.fixing if period is not None else leg.periods[-1].fixing
        if m.window_end:
            we = min(m.window_end, we)
        return ws, we

    def _breach(self, v: np.ndarray, m: BarrierMod, scale: float) -> np.ndarray:
        """Мера «пробоя» > 0 при пробое (для индикатора/сглаживания)."""
        if m.lower is not None or m.upper is not None:
            lo = -np.inf if m.lower is None else m.lower
            hi = np.inf if m.upper is None else m.upper
            return np.maximum(lo - v, v - hi) / scale
        if m.direction == "up":
            return (v - m.level) / scale
        return (m.level - v) / scale

    def survival_at(self, m: BarrierMod, obs, ws: date, ends: list[date], label: str,
                    need_hits: bool = False) -> tuple[np.ndarray, list[tuple[date, np.ndarray]] | None]:
        """Выживание (барьер не задет) на окне [ws, e] для каждого e из ends → (n, len(ends))."""
        n = self.mv.n
        level_scale = abs(m.level if m.level is not None else (m.upper or m.lower or 1.0))
        eps = self.eps * level_scale
        we = max(ends)
        past_knocked = False
        if ws < self.ref:
            past_knocked = self.mv.state_knocked(label)
        alive0 = np.zeros(n) if past_knocked else np.ones(n)
        out = np.empty((n, len(ends)))
        hits = [] if need_hits else None
        if m.monitoring == "terminal":
            for k, e in enumerate(ends):
                if e < self.ref:
                    v = self.mv.obs_matrix(obs, [e])[:, 0]
                else:
                    v = self.mv.obs_matrix(obs, [e])[:, 0]
                br = _ind(self._breach(v, m, 1.0), eps)
                out[:, k] = alive0 * (1 - br)
            return out, hits
        if m.monitoring == "discrete":
            if m.observation == "fixings":
                leg_fix = sorted({p.fixing for leg in self.p.legs for p in leg.periods})
                dates = [d for d in leg_fix if ws <= d <= we]
            else:
                cal = get_calendar(self.p.legs[0].spec.schedule.fixing_calendar or self.p.legs[0].spec.schedule.calendar)
                if m.observation == "daily":
                    dates = cal.business_days(ws, we)
                else:
                    dates = [cal.adjust(d, BDC.PRECEDING) for d in roll_dates(ws, we, m.observation)[1:]]
            past = [d for d in dates if d < self.ref]
            fut = [d for d in dates if d >= self.ref]
            alive = alive0.copy()
            if past:
                try:
                    vp = self.mv.obs_matrix(obs, past)
                    br = _ind(self._breach(vp, m, 1.0), 0.0)
                    alive = alive * np.prod(1 - br, axis=1)
                except KeyError:
                    self.mv.warn(f"Барьер {label}: нет исторических фиксингов — состояние взято из state")
            if m.soft_width:
                return self._soft(m, obs, fut, ends, alive), hits
            vals = self.mv.obs_matrix(obs, fut) if fut else np.zeros((n, 0))
            surv_cols = 1 - _ind(self._breach(vals, m, 1.0), eps) if fut else np.zeros((n, 0))
            cum = np.cumprod(surv_cols, axis=1) * alive[:, None] if fut else np.zeros((n, 0))
            for k, e in enumerate(ends):
                j = sum(1 for d in fut if d <= e)
                out[:, k] = cum[:, j - 1] if j > 0 else alive
            if need_hits:
                prev = alive
                for j, d in enumerate(fut):
                    hits.append((d, prev - cum[:, j]))
                    prev = cum[:, j]
            return out, hits
        # continuous: сетка симуляции + броуновский мост
        d0 = max(ws, self.ref)
        gdates, logv, var = self.mv.obs_grid(obs, d0, we)
        if m.soft_width:
            return self._soft(m, obs, gdates, ends, alive0, grid=(gdates, np.exp(logv))), hits
        if var is None:
            self.mv.warn(f"Барьер {label}: непрерывное наблюдение по составной наблюдаемой аппроксимировано сеткой без моста")
        lvl = {}
        if m.lower is not None or m.upper is not None:
            if m.lower is not None:
                lvl["down"] = np.log(m.lower)
            if m.upper is not None:
                lvl["up"] = np.log(m.upper)
        else:
            lvl[m.direction] = np.log(m.level)
        surv = alive0.copy()
        # пробой в начальной точке
        v0 = np.exp(logv[:, 0])
        surv = surv * (1 - _ind(self._breach(v0, m, 1.0), eps))
        cum = [surv.copy()]
        for j in range(1, len(gdates)):
            step_surv = 1 - _ind(self._breach(np.exp(logv[:, j]), m, 1.0), eps)
            if var is not None:
                pc = np.zeros(n)
                for dirn, h in lvl.items():
                    pc = pc + _bb_cross(logv[:, j - 1], logv[:, j], h, var[:, j - 1], dirn == "up")
                step_surv = step_surv * np.clip(1 - pc, 0.0, 1.0)
            surv = surv * step_surv
            cum.append(surv.copy())
        cum_arr = np.column_stack(cum)
        for k, e in enumerate(ends):
            if e < self.ref:
                out[:, k] = alive0
                continue
            j = max(i for i, d in enumerate(gdates) if d <= e)
            out[:, k] = cum_arr[:, j]
        if need_hits:
            for j in range(1, len(gdates)):
                hits.append((gdates[j], cum_arr[:, j - 1] - cum_arr[:, j]))
        return out, hits

    def _soft(self, m: BarrierMod, obs, dates, ends, alive, grid=None):
        """Soft barrier: доля срабатывания линейна по экстремуму пути в полосе ширины soft_width."""
        n = self.mv.n
        out = np.empty((n, len(ends)))
        if grid is not None:
            gd, vals = grid
        else:
            gd = dates
            vals = self.mv.obs_matrix(obs, dates) if dates else np.zeros((n, 0))
        w = m.soft_width
        for k, e in enumerate(ends):
            idx = [i for i, d in enumerate(gd) if d <= e]
            if not idx:
                out[:, k] = alive
                continue
            sub = vals[:, idx]
            if m.direction == "up":
                ext = sub.max(axis=1)
                frac = np.clip((ext - (m.level - w / 2)) / w, 0, 1)
            else:
                ext = sub.min(axis=1)
                frac = np.clip(((m.level + w / 2) - ext) / w, 0, 1)
            out[:, k] = alive * (1 - frac)
        return out

    # ------------------------------------------------------------------ период
    def _period_value(self, leg: CLeg, comp: Component | None, p: CPeriod) -> tuple[np.ndarray, np.ndarray | None]:
        """Наблюдаемая за период X и (для усреднения по страйку) средний страйк."""
        obs = leg.observable
        t = getattr(obs, "type", None)
        if obs is None:
            return np.zeros(self.mv.n), None
        if t == "rate":
            return self.mv.rate_period(obs, p), None
        if t in ("realized_variance", "realized_vol"):
            ds = list(p.obs_dates) or [p.fixing]
            ds = sorted(set([p.start] + ds))
            v = self.mv.obs_matrix(obs, ds)
            lr = np.diff(np.log(v), axis=1)
            rv = obs.annualization * np.mean(lr * lr, axis=1)
            return (rv if t == "realized_variance" else np.sqrt(rv)), None
        avg = leg.averaging(comp)
        if avg is not None and p.obs_dates:
            vals = self.mv.obs_matrix(obs, list(p.obs_dates))
            w = np.asarray(p.obs_weights) if p.obs_weights else np.full(len(p.obs_dates), 1 / len(p.obs_dates))
            if avg.method == "geometric":
                a = np.exp(np.log(vals) @ w)
            elif avg.method == "max":
                a = vals.max(axis=1)
            elif avg.method == "min":
                a = vals.min(axis=1)
            else:
                a = vals @ w
            if avg.average_of == "strike":
                x = self.mv.obs_matrix(obs, [p.fixing])[:, 0]
                return x, a
            return a, None
        return self.mv.obs_matrix(obs, [p.fixing])[:, 0], None

    def _raw(self, c: Component, X: np.ndarray, K: np.ndarray | float | None, p: CPeriod) -> np.ndarray:
        eps = self.eps * (abs(float(np.mean(K))) if K is not None and np.ndim(K) == 0 and K else 1.0)
        k = c.kind
        if k == "forward":
            return c.gearing * (X - K)
        if k == "call":
            v = np.maximum(X - K, 0.0)
            if c.cap_strike is not None:
                v = v - np.maximum(X - c.cap_strike, 0.0)
            return c.gearing * v
        if k == "put":
            return c.gearing * np.maximum(K - X, 0.0)
        if k == "digital_call":
            return (c.payout if c.payout is not None else 1.0) * _ind(X - K, eps)
        if k == "digital_put":
            return (c.payout if c.payout is not None else 1.0) * _ind(K - X, eps)
        if k == "range_digital":
            e2 = self.eps * abs(c.upper or 1.0)
            return (c.payout if c.payout is not None else 1.0) * _ind(X - c.lower, e2) * _ind(c.upper - X, e2)
        if k == "asset":
            return c.gearing * X
        if k in ("cash", "redemption"):
            return np.full(self.mv.n, c.payout if c.payout is not None else 1.0)
        if k == "fixed":
            return np.full(self.mv.n, (c.rate or 0.0) * p.tau)
        if k == "fixed_compounded":
            return np.full(self.mv.n, (1 + (c.rate or 0.0)) ** p.tau - 1)
        if k == "float":
            return (c.gearing * X + c.spread) * p.tau
        if k == "cap":
            return np.maximum(c.gearing * X + c.spread - K, 0.0) * p.tau
        if k == "floor":
            return np.maximum(K - c.gearing * X - c.spread, 0.0) * p.tau
        if k == "coupon":
            return np.full(self.mv.n, c.rate or 0.0)
        if k == "variance":
            return X - K
        if k == "volatility":
            return X - K
        if k == "index_ratio":
            return c.gearing * (X - 1.0)
        raise ValueError(f"компонент {k} не поддерживается движком Монте-Карло")

    def _strike(self, leg: CLeg, c: Component, p: CPeriod, avg_strike) -> np.ndarray | float | None:
        if avg_strike is not None:
            return avg_strike
        for m in list(leg.modifiers) + list(c.modifiers):
            if isinstance(m, StrikeResetMod):
                base_date = p.start
                if m.base == "previous_fixing" and p.idx > 0:
                    base_date = leg.periods[p.idx - 1].fixing
                b = self.mv.obs_matrix(leg.observable, [base_date])[:, 0]
                return m.pct * b
        return c.strike

    # ------------------------------------------------------------------ основная процедура
    def flows(self) -> list[Flow]:
        out: list[Flow] = []
        for li, leg in enumerate(self.p.legs):
            alive_periods = [p for p in leg.periods if p.payment > self.ref]
            # барьеры уровня ноги (по всем периодам сразу)
            leg_barriers = [(mi, m) for mi, m in enumerate(leg.modifiers) if isinstance(m, BarrierMod)]
            leg_surv = {}
            for mi, m in leg_barriers:
                ws = m.window_start or self.p.start
                ends = [min(p.fixing, m.window_end) if m.window_end else p.fixing for p in alive_periods]
                if not ends:
                    continue
                s, _ = self.survival_at(m, m.observable or leg.observable, ws, ends, f"{leg.name}:leg:{mi}")
                leg_surv[mi] = s
            memory_missed = {}
            global_acc = {}
            for pi, p in enumerate(alive_periods):
                for ci, c in enumerate(leg.components):
                    X, avg_k = self._period_value(leg, c, p)
                    K = self._strike(leg, c, p, avg_k)
                    raw = self._raw(c, X, K, p)
                    sign = 1.0 if c.position == "long" else -1.0
                    factor = np.ones(self.mv.n)
                    mult = c.notional_multiplier
                    rebates: list[Flow] = []
                    has_memory = any(isinstance(m, MemoryMod) for m in c.modifiers)
                    for mi, m in enumerate(c.modifiers):
                        if isinstance(m, BarrierMod):
                            ws, we = self._window(m, leg, p)
                            touch_at_hit = (m.kind == "in" and c.kind in ("cash", "redemption") and m.rebate is not None
                                            and m.rebate.timing == "at_hit")
                            need_hits = bool(m.rebate and m.rebate.timing == "at_hit" and (m.kind == "out" or touch_at_hit))
                            s, hits = self.survival_at(m, m.observable or leg.observable, ws, [we],
                                                       f"{leg.name}:{ci}:{mi}", need_hits)
                            s = s[:, 0]
                            if touch_at_hit and hits:
                                # one-touch с выплатой при касании: поток в дату касания
                                pay = (c.payout if c.payout is not None else 1.0) * p.notional * (1.0 if c.position == "long" else -1.0)
                                rebates.append(Flow(li, ci, p.idx, we, p.payment, p.start, leg.currency, np.zeros(self.mv.n),
                                                    "touch", f"касание {leg.name}/{ci}", hit_dist=[(d, pay * h) for d, h in hits]))
                                factor = factor * 0.0
                                continue
                            factor = factor * (s if m.kind == "out" else (1 - s))
                            if m.rebate and m.rebate.amount:
                                amt = m.rebate.amount * p.notional * sign
                                if m.kind == "out":
                                    if m.rebate.timing == "at_hit" and hits:
                                        rebates.append(Flow(li, ci, p.idx, we, p.payment, p.start, leg.currency,
                                                            np.zeros(self.mv.n), "rebate", f"ребейт {leg.name}/{ci}",
                                                            hit_dist=[(d, amt * h) for d, h in hits]))
                                    else:
                                        rebates.append(Flow(li, ci, p.idx, we, p.payment, p.start, leg.currency,
                                                            amt * (1 - s), "rebate", f"ребейт {leg.name}/{ci}"))
                                else:
                                    rebates.append(Flow(li, ci, p.idx, we, p.payment, p.start, leg.currency,
                                                        amt * s, "rebate", f"ребейт {leg.name}/{ci}"))
                        elif isinstance(m, LeverageMod):
                            if m.when == "always":
                                mult = mult * m.factor
                            else:
                                thr = m.threshold if m.threshold is not None else (K if np.ndim(K) == 0 else 0.0)
                                cond = _ind(thr - X, self.eps * abs(thr)) if m.when == "below" else _ind(X - thr, self.eps * abs(thr))
                                factor = factor * (1 + (m.factor - 1) * cond)
                        elif isinstance(m, AccrualMod):
                            factor = factor * self._accrual(m, leg, p)
                        elif isinstance(m, CapFloorMod):
                            unit_tau = p.tau if (m.unit == "rate" and c.kind in ("float", "fixed", "cap", "floor")) else 1.0
                            r = raw / unit_tau
                            if m.local_cap is not None:
                                r = np.minimum(r, m.local_cap)
                            if m.local_floor is not None:
                                r = np.maximum(r, m.local_floor)
                            raw = r * unit_tau
                    for mi, s in leg_surv.items():
                        lm = leg.modifiers[mi]
                        factor = factor * (s[:, pi] if lm.kind == "out" else 1 - s[:, pi])
                    unit_pay = raw * factor
                    if has_memory:
                        key = ci
                        missed = memory_missed.get(key, np.zeros(self.mv.n))
                        cond = unit_pay > 1e-15 if self.eps == 0 else np.clip(unit_pay / max(float(np.max(unit_pay)), 1e-15), 0, 1)
                        pay_mult = 1 + missed
                        unit_pay = unit_pay * pay_mult
                        memory_missed[key] = np.where(cond > 0.5, 0.0, missed + 1) if self.eps == 0 else (missed + 1) * (1 - cond)
                    # глобальные кэп/флор на сумму выплат компонента
                    for m in list(leg.modifiers) + list(c.modifiers):
                        if isinstance(m, CapFloorMod) and m.global_cap is not None:
                            acc = global_acc.get(ci, np.zeros(self.mv.n))
                            room = np.maximum(m.global_cap - acc, 0.0)
                            capped = np.minimum(unit_pay, room)
                            global_acc[ci] = acc + capped
                            unit_pay = capped
                        elif isinstance(m, CapFloorMod) and m.global_floor is not None:
                            global_acc[ci] = global_acc.get(ci, np.zeros(self.mv.n)) + unit_pay
                            if p is alive_periods[-1]:
                                unit_pay = unit_pay + np.maximum(m.global_floor - global_acc[ci], 0.0)
                    amt = sign * p.notional * self._reset_factor(leg, p) * mult * unit_pay
                    gain = np.maximum(sign * raw, 0.0) if sign > 0 else None
                    out.append(Flow(li, ci, p.idx, p.fixing, p.payment, p.start, leg.currency, amt, "component",
                                    f"{leg.name}/{c.kind}{'/' + c.label if c.label else ''}", gain))
                    out.extend(rebates)
            out.extend(self._notional_flows(li, leg))
        out = self._structure(out)
        return out

    def _accrual(self, m: AccrualMod, leg: CLeg, p: CPeriod) -> np.ndarray:
        obs = m.observable or leg.observable
        ds = list(p.obs_dates)
        if not ds:
            cal = get_calendar(leg.spec.schedule.fixing_calendar or leg.spec.schedule.calendar)
            ds = cal.business_days(p.start, p.end)
        if getattr(obs, "type", None) == "rate":
            vals = self.mv.rate_daily(obs, ds)
        else:
            vals = self.mv.obs_matrix(obs, ds)
        lo = -np.inf if m.lower is None else m.lower
        hi = np.inf if m.upper is None else m.upper
        sc = abs(hi if np.isfinite(hi) else lo) if (np.isfinite(hi) or np.isfinite(lo)) else 1.0
        inr = _ind(vals - lo, self.eps * sc) * _ind(hi - vals, self.eps * sc)
        if m.proportion == "days":
            w = np.array([((ds[i + 1] if i + 1 < len(ds) else p.end) - ds[i]).days for i in range(len(ds))], float)
            w = np.maximum(w, 0)
            w = w / w.sum() if w.sum() > 0 else np.full(len(ds), 1 / len(ds))
        else:
            w = np.full(len(ds), 1 / len(ds))
        return inr @ w

    def _reset_factor(self, leg: CLeg, p: CPeriod) -> np.ndarray | float:
        """MtM-ресет: номинал периода = N₀·X(начало периода)/X(начало первого периода) по траектории курса."""
        if not leg.spec.notional_reset:
            return 1.0
        src = (leg.settlement.fixing_source if leg.settlement else None) or "CBR"
        x0 = self.mv.fx_value(leg.spec.reset_pair, leg.periods[0].start, src)
        return self.mv.fx_value(leg.spec.reset_pair, p.start, src) / x0

    def _notional_flows(self, li: int, leg: CLeg) -> list[Flow]:
        """Обмен номиналами: −N в начале, амортизация (или MtM-ресет) и +N в конце (знак — по направлению ноги)."""
        ex = leg.spec.exchange_notional
        if ex == "none" or not leg.periods:
            return []
        sign = 1.0 if (leg.components and leg.components[0].position == "long") else -1.0
        out = []
        ps = leg.periods
        n = self.mv.n
        notional = [p.notional * self._reset_factor(leg, p) for p in ps]
        if ex in ("initial", "both") and ps[0].start > self.ref:
            out.append(Flow(li, -1, 0, ps[0].start, ps[0].start, ps[0].start, leg.currency,
                            np.broadcast_to(-sign * notional[0], (n,)).astype(float), "notional", f"{leg.name}/выдача номинала"))
        if ex in ("final", "both"):
            for i, p in enumerate(ps):
                nxt = notional[i + 1] if i + 1 < len(ps) else 0.0
                amort = np.broadcast_to(notional[i] - nxt, (n,)).astype(float)
                if np.any(np.abs(amort) > 0) and p.payment > self.ref:
                    out.append(Flow(li, -1, p.idx, p.fixing, p.payment, p.start, leg.currency, sign * amort,
                                    "notional", f"{leg.name}/{'ресет' if i + 1 < len(ps) and leg.spec.notional_reset else 'погашение'} номинала"))
        return out

    # ------------------------------------------------------------------ модификаторы уровня сделки
    def _structure(self, flows: list[Flow]) -> list[Flow]:
        mods = self.p.modifiers
        for m in mods:
            if isinstance(m, BarrierMod):
                obs = m.observable or self.p.legs[0].observable
                ends = sorted({f.fixing for f in flows if f.fixing >= self.ref} | {self.ref})
                ws = m.window_start or self.p.start
                s, _ = self.survival_at(m, obs, ws, ends, "trade:barrier")
                idx = {d: i for i, d in enumerate(ends)}
                for f in flows:
                    if f.fixing < self.ref:
                        continue
                    sv = s[:, idx[f.fixing]]
                    f.amount = f.amount * (sv if m.kind == "out" else 1 - sv)
            elif isinstance(m, TargetMod):
                flows = self._target(m, flows)
            elif isinstance(m, AutocallMod):
                flows = self._autocall(m, flows)
        return flows

    def _target(self, m: TargetMod, flows: list[Flow]) -> list[Flow]:
        n = self.mv.n
        cum = np.full(n, float(self.p.trade.state.accumulated_target))
        alive = np.ones(n)
        fixings = sorted({f.fixing for f in flows if f.kind == "component"})
        by_fix: dict[date, list[Flow]] = {}
        for f in flows:
            by_fix.setdefault(f.fixing, []).append(f)
        eps = self.eps * max(m.level, 1e-12)
        for d in fixings:
            fl = [f for f in by_fix[d] if f.kind in ("component", "rebate")]
            if m.measure == "gain_per_unit":
                g = sum((f.gain for f in fl if f.gain is not None), np.zeros(n))
            elif m.measure == "itm_count":
                g = sum(((f.gain > 0).astype(float) for f in fl if f.gain is not None), np.zeros(n))
            else:
                g = sum((np.maximum(f.amount, 0) for f in fl), np.zeros(n))
            new = cum + g
            crossed = _ind(new - m.level, eps)            # достигнута цель на этом фиксинге
            if m.last_payment == "full":
                scale_pos = np.ones(n)
            elif m.last_payment == "partial":
                with np.errstate(divide="ignore", invalid="ignore"):
                    scale_pos = np.where(g > 0, np.clip((m.level - cum) / g, 0, 1), 1.0)
                scale_pos = crossed * scale_pos + (1 - crossed)
            else:
                scale_pos = 1 - crossed
            for f in fl:
                pos = np.maximum(f.amount, 0)
                neg = np.minimum(f.amount, 0)
                if m.last_payment == "none":
                    f.amount = alive * (pos + neg) * (1 - crossed)
                else:
                    f.amount = alive * (pos * scale_pos + neg)
            alive = alive * (1 - crossed)
            cum = new
        return flows

    def _autocall(self, m: AutocallMod, flows: list[Flow]) -> list[Flow]:
        n = self.mv.n
        leg = next((l for l in self.p.legs if l.name == m.leg), self.p.legs[0])
        all_dates = sorted(m.dates) if m.dates else [p.fixing for p in leg.periods]
        levels_all = m.level if isinstance(m.level, list) else [m.level] * len(all_dates)
        pairs = list(zip(all_dates, levels_all + [levels_all[-1]] * (len(all_dates) - len(levels_all))))[m.first_date_index:]
        last_fix = max(f.fixing for f in flows)
        pairs = [(d, lv) for d, lv in pairs if self.ref <= d < last_fix]
        if self.p.trade.state.autocalled:
            for f in flows:
                f.amount = f.amount * 0
            return flows
        alive = np.ones(n)
        alive_after: list[tuple[date, np.ndarray]] = []
        new_flows = []
        notional = leg.periods[-1].notional
        for k, (d, lv) in enumerate(pairs):
            x = self.mv.obs_matrix(leg.observable, [d])[:, 0]
            call = _ind(x - lv, self.eps * abs(lv))
            pay_d = next((p.payment for p in leg.periods if p.fixing == d), d)
            new_flows.append(Flow(0, -1, k, d, pay_d, d, leg.currency, alive * call * m.redemption * notional, "autocall",
                                  f"автоколл {d.isoformat()}"))
            alive = alive * (1 - call)
            alive_after.append((d, alive.copy()))
        for f in flows:
            # поток живёт, если автоколла не было строго до его фиксинга
            a = np.ones(n)
            for d, al in alive_after:
                if d < f.fixing:
                    a = al
            f.amount = f.amount * a
        return flows + new_flows

    # ------------------------------------------------------------------ сборка PV
    def evaluate(self) -> EvalResult:
        flows = self.flows()
        n = self.mv.n
        pv = np.zeros(n)
        flow_pv = []
        for f in flows:
            if f.hit_dist is not None:
                v = np.zeros(n)
                for d, h in f.hit_dist:
                    v = v + h * self._to_report(f.ccy, d, f)
                f.amount = sum((h for _, h in f.hit_dist), np.zeros(n))
            else:
                v = f.amount * self._to_report(f.ccy, f.payment, f)
            pv += v
            flow_pv.append(float(np.mean(v)))
        notes = []
        ex_info = {}
        for m in self.p.modifiers:
            if isinstance(m, (EarlyTerminationMod, ExerciseMod)):
                pv, info = self._lsmc(m, flows)
                ex_info = info
                notes.append("право досрочного прекращения/исполнения оценено обратной индукцией (LSMC)")
        return EvalResult(flows, pv, flow_pv, notes, ex_info)

    def _to_report(self, ccy: str, d: date, f: Flow) -> np.ndarray | float:
        """PV (в валюте отчёта) единицы валюты ``ccy``, выплачиваемой в дату ``d``, с учётом квантования."""
        settle = self.p.legs[f.leg].settlement if 0 <= f.leg < len(self.p.legs) else self.p.trade.settlement
        q = settle.quanto if settle is not None else None
        if q is not None and ccy != settle.currency:
            base, quote = q.pair[:3], q.pair[3:]
            if q.type == "quanto":
                rate = q.rate if q.rate is not None else float(np.mean(self.mv.fx_value(q.pair, f.fixing, q.fixing_source)))
            else:
                rate = self.mv.fx_value(q.pair, f.fixing, q.fixing_source)
            if ccy == base and settle.currency == quote:
                conv = rate
            elif ccy == quote and settle.currency == base:
                conv = 1.0 / rate
            else:
                raise ValueError(f"квантование {ccy}→{settle.currency} по паре {q.pair} невозможно")
            return conv * self.mv.df(settle.currency, d)
        return self.mv.df(ccy, d)

    def _lsmc(self, m, flows: list[Flow]) -> tuple[np.ndarray, dict]:
        """Лонгстафф-Шварц: обратная индукция по датам исполнения."""
        n = self.mv.n
        ex_dates = sorted(d for d in m.dates if d >= self.ref)
        if not ex_dates:
            pv = sum((f.amount * self._to_report(f.ccy, f.payment, f) for f in flows), np.zeros(n))
            return pv, {}
        disc = [f.amount * self._to_report(f.ccy, f.payment, f) for f in flows]
        starts = [f.start for f in flows]
        holder_sign = 1.0 if m.holder == "client" else -1.0
        is_entry = isinstance(m, ExerciseMod)
        amount = getattr(m, "amount", 0.0)
        # value_after[e]: стоимость потоков, начинающихся не раньше e
        value = np.zeros(n)          # реализованная стоимость «с текущей даты исполнения» при оптимальной политике
        ex_prob = {}
        value = np.zeros(n)
        for k in range(len(ex_dates) - 1, -1, -1):
            e = ex_dates[k]
            nxt = ex_dates[k + 1] if k + 1 < len(ex_dates) else None
            seg = sum((v for v, s in zip(disc, starts) if s >= e and (nxt is None or s < nxt)), np.zeros(n))
            remaining_all = sum((v for v, s in zip(disc, starts) if s >= e), np.zeros(n))
            if is_entry:
                exercise_val = remaining_all
                cont = value
            else:
                exercise_val = amount * np.broadcast_to(self.mv.df(self.p.trade.report_currency, e), (n,))
                cont = seg + value
            X = self.mv.state_vars(e)
            B = _basis(X)
            itm = np.ones(n, bool)
            coef, *_ = np.linalg.lstsq(B[itm], cont[itm], rcond=None)
            c_hat = B @ coef
            ex = (holder_sign * (exercise_val - c_hat) > 0)
            value = np.where(ex, exercise_val, cont)
            ex_prob[e.isoformat()] = float(np.mean(ex))
        before = sum((v for v, s in zip(disc, starts) if s < ex_dates[0]), np.zeros(n))
        pv = value + (np.zeros(n) if is_entry else before)
        return pv, {"exercise_probability": ex_prob, "method": "LSMC, полиномиальный базис степени 3"}


def _basis(X: np.ndarray) -> np.ndarray:
    X = np.atleast_2d(X.T).T if X.ndim == 1 else X
    cols = [np.ones(X.shape[0])]
    Z = (X - X.mean(axis=0)) / np.maximum(X.std(axis=0), 1e-12)
    for j in range(Z.shape[1]):
        z = Z[:, j]
        cols += [z, z * z, z * z * z]
    if Z.shape[1] >= 2:
        cols.append(Z[:, 0] * Z[:, 1])
    return np.column_stack(cols)
