"""Hull-White 1F: триномиальное дерево (Hull & White, 1994) и бермудские структуры.

Бермудское расписание оценивается обратной индукцией, а не набором
европейских опционов. Мультикривая: дерево строится на дисконтной кривой,
плавающие купоны реплицируются как (+N в начале, −N в конце) плюс базисный
спред прогнозной кривой к дисконтной (детерминированный).

Калибровка σ — по ATM нормальной волатильности ко-терминальных свопционов
(приближение ∂S/∂x), скорость возврата к среднему — модельный параметр.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np

from ...core.provenance import DataKind, Provenance, UsedInput
from ...instruments.schema import EarlyTerminationMod, ExerciseMod, Trade


class HWTree:
    def __init__(self, logdf, a: float, sigma: float, T_end: float, steps_per_year: int = 120):
        self.a = a
        self.sigma = sigma
        n = max(int(np.ceil(T_end * steps_per_year)), 4)
        self.N = n
        self.dt = dt = T_end / n
        self.times = np.arange(n + 1) * dt
        e = np.exp(-a * dt)
        M = e - 1.0
        V = sigma * sigma * (1 - e * e) / (2 * a) if a > 1e-10 else sigma * sigma * dt
        self.dx = dx = np.sqrt(3 * V)
        jmax = max(int(np.ceil(0.1835 / max(a * dt, 1e-12))), 1)
        self.jmax = jmax
        js = np.arange(-jmax, jmax + 1)
        self.js = js
        pu = np.empty(len(js))
        pm = np.empty(len(js))
        pd = np.empty(len(js))
        k = np.empty(len(js), dtype=int)   # средний узел ветвления
        for i, j in enumerate(js):
            jM = j * M
            j2 = jM * jM
            if j == jmax:
                pu[i] = 7 / 6 + (j2 + 3 * jM) / 2
                pm[i] = -1 / 3 - j2 - 2 * jM
                pd[i] = 1 / 6 + (j2 + jM) / 2
                k[i] = j - 1
            elif j == -jmax:
                pu[i] = 1 / 6 + (j2 - jM) / 2
                pm[i] = -1 / 3 - j2 + 2 * jM
                pd[i] = 7 / 6 + (j2 - 3 * jM) / 2
                k[i] = j + 1
            else:
                pu[i] = 1 / 6 + (j2 + jM) / 2
                pm[i] = 2 / 3 - j2
                pd[i] = 1 / 6 + (j2 - jM) / 2
                k[i] = j
        self.pu, self.pm, self.pd, self.k = pu, pm, pd, k
        # подгонка α к кривой
        ln_p = lambda t: float(logdf(np.array([t]))[0])
        alpha = np.empty(n)
        Q = np.zeros(len(js))
        Q[jmax] = 1.0
        width = lambda i: min(i, jmax)
        for i in range(n):
            w = width(i)
            sl = slice(jmax - w, jmax + w + 1)
            jj = js[sl]
            s = np.sum(Q[sl] * np.exp(-jj * dx * dt))
            alpha[i] = (np.log(s) - ln_p(self.times[i + 1])) / dt
            disc = Q[sl] * np.exp(-(alpha[i] + jj * dx) * dt)
            Qn = np.zeros(len(js))
            for idx, j in zip(range(sl.start, sl.stop), jj):
                d = disc[idx - sl.start]
                kk = k[idx] + jmax
                Qn[kk + 1] += d * pu[idx]
                Qn[kk] += d * pm[idx]
                Qn[kk - 1] += d * pd[idx]
            Q = Qn
        self.alpha = alpha

    def step_back(self, V_next: np.ndarray, i: int) -> np.ndarray:
        """Значения в узлах шага i по значениям шага i+1 (массивы длины 2·jmax+1)."""
        kk = self.k + self.jmax
        cont = self.pu * V_next[np.clip(kk + 1, 0, len(V_next) - 1)] + self.pm * V_next[kk] + \
            self.pd * V_next[np.clip(kk - 1, 0, len(V_next) - 1)]
        return cont * np.exp(-(self.alpha[i] + self.js * self.dx) * self.dt)


def hw_swaption_normal_vol(curve, a: float, sigma: float, T_ex: float, pays: list[tuple[float, float]]) -> float:
    """Приближённая нормальная волатильность своп-ставки под HW: |∂S/∂x|·σ·√((1−e^{−2aT})/(2aT))."""
    B = lambda t: (1 - np.exp(-a * (t - T_ex))) / a
    P0 = float(curve.df(T_ex))
    Ps = np.array([float(curve.df(t)) for t, _ in pays])
    taus = np.array([tau for _, tau in pays])
    A = float(np.sum(taus * Ps))
    S = (P0 - Ps[-1]) / A
    Bs = np.array([B(t) for t, _ in pays])
    dSdx = (Bs[-1] * Ps[-1] + S * np.sum(taus * Bs * Ps)) / A
    scale = np.sqrt((1 - np.exp(-2 * a * T_ex)) / (2 * a * T_ex)) if a > 1e-10 else 1.0
    return float(dSdx * sigma * scale), S


def price_bermudan(trade: Trade, cp, ctx, a: float | None = None, steps_per_year: int = 120) -> dict[str, Any]:
    ref = cp.ref_date
    mod = cp.modifiers[0]
    is_entry = isinstance(mod, ExerciseMod)
    a = a if a is not None else float(ctx.config.get("models", {}).get("hw_mean_reversion", 0.10))
    rep = trade.report_currency
    disc = ctx.discount_curve(rep, trade.collateral.collateralized, override=trade.model.discount_override,
                              t_max=(cp.last_payment - ref).days / 365.0)
    tt = lambda d: (d - ref).days / 365.0
    flows: list[tuple[float, float, date]] = []   # (время, сумма, дата начала периода)
    fixed_pays: list[tuple[float, float]] = []
    index = None
    for leg in cp.legs:
        obs = leg.observable
        if index is None:
            index = obs.index
        fc = ctx.forecast_curve(obs.index, t_max=tt(cp.last_payment))
        for p in leg.periods:
            if p.payment <= ref:
                continue
            for c in leg.components:
                sign = 1.0 if c.position == "long" else -1.0
                N = p.notional
                if c.kind == "fixed":
                    flows.append((tt(p.payment), sign * N * (c.rate or 0.0) * p.tau, p.start))
                    fixed_pays.append((tt(p.payment), p.tau))
                elif c.kind == "float":
                    if abs(c.gearing - 1.0) > 1e-12:
                        raise ValueError("дерево HW: плавающая нога с коэффициентом ≠ 1 не поддерживается")
                    ts, te = tt(p.start), tt(p.end)
                    if ts < 0:
                        F = float(fc.fwd_simple(0.0, te))
                        flows.append((tt(p.payment), sign * N * (F + c.spread) * p.tau, p.start))
                        continue
                    basis = float(fc.fwd_simple(ts, te) - disc.fwd_simple(ts, te))
                    flows.append((ts, sign * N, p.start))
                    flows.append((te, -sign * N, p.start))
                    flows.append((tt(p.payment), sign * N * (basis + c.spread) * p.tau, p.start))
    ex_dates = sorted(d for d in mod.dates if d >= ref)
    ex_t = [tt(d) for d in ex_dates]
    T_end = max(t for t, _, _ in flows)
    # калибровка σ по ко-терминальным свопционам
    irv = ctx.ir_vol(ctx.index(index)["curve"], ex_t[0] if ex_t else 1.0, "калибровка Hull-White (ко-терминальные свопционы)")
    sig_list = []
    for te_, d in zip(ex_t, ex_dates):
        pays = [(t, tau) for t, tau in fixed_pays if t > te_ + 1e-9]
        if not pays or te_ <= 0:
            continue
        target = irv.normal_vol(0.0, 0.0, te_, T_end - te_)
        unit, S = hw_swaption_normal_vol(disc, a, 1.0, te_, sorted(pays))
        sig_list.append(target / unit)
    sigma = float(np.mean(sig_list)) if sig_list else 0.01
    ctx.tracker.record(UsedInput("model:HW1F_TREE", {"a": a, "sigma": round(sigma, 6), "calib": [round(x, 6) for x in sig_list]},
                                 Provenance("Hull-White 1F (дерево): σ по ко-терминальным свопционам", None, DataKind.MODEL,
                                            note="скорость возврата к среднему — модельный параметр"), "модель ставки"))
    tree = HWTree(disc.logdf_t, a, sigma, T_end, steps_per_year)
    snap = lambda t: int(round(t / tree.dt))
    # денежные суммы по шагам (с поправкой за привязку к сетке: сохраняется PV детерминированных сумм)
    cash: dict[int, list[tuple[float, date]]] = {}
    for t, amt, st in flows:
        i = min(snap(t), tree.N)
        adj = float(disc.df(t) / disc.df(tree.times[i]))
        cash.setdefault(i, []).append((amt * adj, st))
    ex_steps = {min(snap(t), tree.N): d for t, d in zip(ex_t, ex_dates)}
    width = len(tree.js)
    holder = 1.0 if mod.holder == "client" else -1.0
    U = np.zeros(width)   # стоимость потоков периодов, начинающихся не раньше текущей даты исполнения
    W = np.zeros(width)   # стоимость структуры (опцион / отменяемый своп)
    pre = np.zeros(width)  # потоки периодов, начавшихся до первой даты исполнения
    first_ex = ex_dates[0] if ex_dates else None
    amount = getattr(mod, "amount", 0.0)
    for i in range(tree.N, -1, -1):
        e_here = ex_steps.get(i)
        later = []
        for amt, st in cash.get(i, []):
            if e_here is not None and st < e_here:
                later.append((amt, st))     # потоки периодов, начавшихся до этой даты исполнения, — после решения
                continue
            if first_ex is not None and st < first_ex:
                pre += amt
            else:
                U += amt
                if not is_entry:
                    W += amt
        if e_here is not None:
            if is_entry:
                W = np.where(holder * (U - W) > 0, U, W)
            else:
                term = np.full(width, amount)
                W = np.where(holder * (term - W) > 0, term, W)
        for amt, st in later:
            if first_ex is not None and st < first_ex:
                pre += amt
            else:
                U += amt
                if not is_entry:
                    W += amt
        if i > 0:
            U = tree.step_back(U, i - 1)
            W = tree.step_back(W, i - 1)
            pre = tree.step_back(pre, i - 1)
    value = float(W[tree.jmax] + (0.0 if is_entry else 0.0) + pre[tree.jmax])
    under = float(U[tree.jmax] + pre[tree.jmax])
    items = [{"component": "bermudan", "pv": value, "method": "дерево Hull-White 1F, обратная индукция",
              "underlying_pv": under, "sigma": sigma, "a": a, "steps": tree.N, "exercise_dates": [d.isoformat() for d in ex_dates]}]
    return {"value": value, "model": f"Hull-White 1F, триномиальное дерево (a={a}, σ={sigma:.4f})", "items": items,
            "exercise": {"type": "entry" if is_entry else "termination", "holder": mod.holder}}
