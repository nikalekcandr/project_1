"""Движок Монте-Карло для композиционных выплат.

* контроль сходимости: батчи с независимыми под-seed'ами, вывод
  доверительного интервала и таблицы сходимости; остановка по целевой
  точности;
* антитетические переменные, мост Брауна для непрерывных барьеров,
  фиксируемый seed — результат детерминирован;
* возвращает перечень фактически использованных входов (через трекер
  контекста) и признаки модельности.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np

from ...core.calendars import get_calendar
from ...core.dates import Tenor
from ...core.provenance import DataKind, Provenance, UsedInput
from ...instruments.schema import (AccrualMod, AutocallMod, BarrierMod, EarlyTerminationMod, ExerciseMod, RateObs,
                                   StrikeResetMod, Trade)
from ...payoff.compile import CPeriod, CProduct, compile_trade, observable_names
from ...payoff.evaluate import Evaluator, MarketView
from .paths import AssetProcess, HWProcess, PathSet, Simulator


@dataclass
class MCConfig:
    paths: int = 40000
    seed: int = 20261015
    antithetic: bool = True
    vol_model: str = "local_vol"      # 'local_vol' | 'black'
    steps_per_year: int = 252
    batches: int = 4
    target_stderr: float | None = None
    smoothing: float = 0.0
    hw_mean_reversion: float = 0.10


@dataclass
class MCResult:
    value: float
    stderr: float
    ci95: tuple[float, float]
    n_paths: int
    seed: int
    convergence: list[dict[str, float]]
    flows: list[dict[str, Any]]
    notes: list[str] = field(default_factory=list)
    exercise: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    pv_paths: np.ndarray | None = None


def _t(ref: date, d: date) -> float:
    return (d - ref).days / 365.0


class _Info:
    """Сведения о базисе для симуляции."""

    def __init__(self, name: str, spec, ctx, ref: date):
        self.name = name
        self.spec = spec
        self.asset_id = spec.id
        self.cls = spec.asset_class
        self.source = spec.fixing.source
        self.lag = spec.fixing.lag_days
        self.cal = get_calendar(spec.fixing.calendar or ("RU" if self.cls != "commodity" else "WEEKENDS"))
        self.ref = ref

    def sim_date(self, d: date) -> date:
        if self.lag:
            return self.cal.advance_business_days(d, self.lag)
        return d


class MCMarketView(MarketView):
    def __init__(self, ps: PathSet, ref: date, ctx, product: CProduct, infos: dict[str, _Info],
                 hw: dict[str, tuple[HWProcess, Any]], report_ccy: str, collateralized: bool, disc_override: str | None):
        self.ps = ps
        self.ref = ref
        self.ctx = ctx
        self.p = product
        self.infos = infos
        self.hw = hw
        self.n = ps.n_paths
        self.report = report_ccy
        self.collat = collateralized
        self.disc_override = disc_override
        self._disc = ctx.discount_curve(report_ccy, collateralized, override=disc_override)
        self._initial_cache: dict[str, np.ndarray] = {}
        self._df_cache: dict[tuple[str, date], Any] = {}

    def warn(self, msg: str) -> None:
        self.ctx.tracker.warn(msg)

    def state_knocked(self, label: str) -> bool:
        return bool(self.p.trade.state.knocked.get(label, False))

    # ------------------------------------------------------------ assets
    def _asset_col(self, name: str, d: date) -> np.ndarray:
        info = self.infos[name]
        if d < self.ref or (d == self.ref and self.ctx.has_fixing(info.asset_id, info.source, d)):
            if self.ctx.has_fixing(info.asset_id, info.source, d) or not self.ctx.allow_projected_fixings:
                v = self.ctx.fixing(info.asset_id, info.source, d, f"фиксинг {info.asset_id} ({info.source})")
                return np.full(self.n, v)
        sd = info.sim_date(d) if d > self.ref else d
        sd = max(sd, self.ref)
        j = self.ps.col(_t(self.ref, sd))
        return self.ps.values[name][:, j]

    def asset_matrix(self, name: str, dates: list[date]) -> np.ndarray:
        return np.column_stack([self._asset_col(name, d) for d in dates]) if dates else np.zeros((self.n, 0))

    def _initial(self, name: str, given: float | None) -> np.ndarray | float:
        if given is not None:
            return given
        if name not in self._initial_cache:
            self._initial_cache[name] = self._asset_col(name, self.p.start)
        return self._initial_cache[name]

    def _combine(self, obs, getter) -> np.ndarray:
        """Наблюдаемая из матриц базисов; getter(name) -> (n, m)."""
        t = obs.type
        if t in ("asset", "realized_variance", "realized_vol"):
            return getter(obs.name)
        if t == "performance":
            init = self._initial(obs.name, obs.initial)
            m = getter(obs.name)
            return m / (init[:, None] if np.ndim(init) else init)
        if t == "basket":
            mats = []
            for i, nm in enumerate(obs.names):
                m = getter(nm)
                if obs.performance:
                    init = self._initial(nm, obs.initials[i] if obs.initials else None)
                    m = m / (init[:, None] if np.ndim(init) else init)
                mats.append(m)
            st = np.stack(mats, axis=2)   # (n, m, k)
            w = np.asarray(obs.weights if obs.weights else [1.0 / len(obs.names)] * len(obs.names))
            if obs.rule == "sum":
                return st @ w
            if obs.rule == "worst_of":
                return st.min(axis=2)
            if obs.rule == "best_of":
                return st.max(axis=2)
            srt = -np.sort(-st, axis=2)
            rw = np.asarray(obs.rank_weights or w)
            return srt @ rw
        if t == "spread":
            return sum(float(term.get("coef", 1.0)) * getter(term["name"]) for term in obs.terms)
        raise ValueError(f"наблюдаемая {t} не поддерживается в Монте-Карло")

    def obs_matrix(self, obs, dates: list[date]) -> np.ndarray:
        if not dates:
            return np.zeros((self.n, 0))
        if obs.type == "rate":
            return self.rate_daily(obs, dates)
        return self._combine(obs, lambda nm: self.asset_matrix(nm, dates))

    def obs_grid(self, obs, d0: date, d1: date):
        t0, t1 = _t(self.ref, d0), _t(self.ref, d1)
        idx = np.where((self.ps.times >= t0 - 1e-9) & (self.ps.times <= t1 + 1e-9))[0]
        dates = [date.fromordinal(self.ref.toordinal() + int(np.ceil(self.ps.times[i] * 365 - 1e-6))) for i in idx]
        if obs.type == "rate":
            exact = [d for d, i in zip(dates, idx) if abs(_t(self.ref, d) - self.ps.times[i]) < 1e-8]
            m = self.rate_daily(obs, exact)
            return exact, np.log(np.maximum(m, 1e-12)), None
        m = self._combine(obs, lambda nm: self.ps.values[nm][:, idx])
        if obs.type in ("asset", "performance"):
            sv = self.ps.step_vol[obs.name]
            dt = np.diff(self.ps.times[idx])
            sig = sv[:, idx[:-1]]
            if sig.shape[0] == 1:
                sig = np.broadcast_to(sig, (self.n, len(idx) - 1))
            return dates, np.log(np.maximum(m, 1e-300)), sig * sig * dt[None, :]
        return dates, np.log(np.maximum(m, 1e-300)), None

    def fx_value(self, pair: str, d: date, source: str) -> np.ndarray:
        for nm, info in self.infos.items():
            if info.asset_id == pair:
                return self._asset_col(nm, d)
        raise KeyError(f"курс {pair} не смоделирован")

    # ------------------------------------------------------------ rates
    def _hw_for(self, index: str):
        idx = self.ctx.index(index)
        ccy = idx["currency"]
        if ccy in self.hw:
            return self.hw[ccy], idx
        return None, idx

    def rate_period(self, obs: RateObs, p: CPeriod) -> np.ndarray:
        (hwp_fc, idx) = self._hw_for(obs.index)
        fc = self.ctx.forecast_curve(obs.index, t_max=_t(self.ref, p.end))
        comp = obs.compounding if obs.compounding != "default" else idx.get("compounding", "compounded")
        ts, te = max(_t(self.ref, p.start), 0.0), _t(self.ref, p.end)
        if p.start < self.ref and comp in ("compounded", "simple_average"):
            self.warn(f"Период {p.start}–{p.end}: начисление начато до даты оценки — прошедшая часть по прогнозной кривой")
        if comp == "term":
            tenor = Tenor.parse(idx.get("tenor", "3M")).approx_years
            ts_f = _t(self.ref, p.fixing)
            if p.fixing < self.ref and self.ctx.has_fixing(obs.index, "CBR", p.fixing):
                return np.full(self.n, self.ctx.fixing(obs.index, "CBR", p.fixing))
            te_f = ts_f + tenor
            base = float(fc.fwd_simple(max(ts_f, 0), te_f)) + float(idx.get("spread_adjustment", 0.0) if idx.get("legacy") else 0.0)
            if hwp_fc is None or ts_f <= 0:
                return np.full(self.n, base)
            hwp, disc = hwp_fc
            x = self.ps.rate_x[hwp.name][:, self.ps.col(ts_f)]
            y = float(hwp.y(np.array([ts_f]))[0])
            P = hwp.bond(ts_f, te_f, x, y)
            sim = (1 / P - 1) / tenor
            det = float(disc.fwd_simple(ts_f, te_f))
            return sim + (base - det)
        tau = max(te - ts, 1e-10)
        if comp == "simple_average":
            base = float(fc.fwd_average(ts, te))
            base = 365.0 * np.expm1(base / 365.0)
        else:
            base = float(fc.fwd_simple(ts, te))
        if hwp_fc is None:
            return np.full(self.n, base)
        hwp, disc = hwp_fc
        i0, i1 = self.ps.col(ts), self.ps.col(te)
        I = self.ps.rate_intx[hwp.name]
        integ = I[:, i1] - I[:, i0] + float(disc.logdf_t(ts) - disc.logdf_t(te))   # ∫ r = ∫ f + ∫ x
        if comp == "simple_average":
            sim = 365.0 * np.expm1(integ / tau / 365.0)
            det = 365.0 * np.expm1(float(disc.fwd_average(ts, te)) / 365.0)
        else:
            sim = (np.exp(integ) - 1) / tau
            det = float(disc.fwd_simple(ts, te))
        return sim + (base - det)

    def rate_daily(self, obs: RateObs, dates: list[date]) -> np.ndarray:
        (hwp_fc, idx) = self._hw_for(obs.index)
        fc = self.ctx.forecast_curve(obs.index)
        cols = []
        for d in dates:
            t = _t(self.ref, d)
            if d <= self.ref:
                src = "CBR"
                if self.ctx.has_fixing(obs.index, src, d):
                    cols.append(np.full(self.n, self.ctx.fixing(obs.index, src, d)))
                    continue
            f = float(fc.inst_fwd(max(t, 0.0)))
            base = 365.0 * np.expm1(f / 365.0)
            if hwp_fc is None or t <= 0:
                cols.append(np.full(self.n, base))
                continue
            hwp, disc = hwp_fc
            x = self.ps.rate_x[hwp.name][:, self.ps.col(t)]
            cols.append(base + x)
        return np.column_stack(cols)

    # ------------------------------------------------------------ discounting
    def df(self, ccy: str, d: date):
        key = (ccy, d)
        if key in self._df_cache:
            return self._df_cache[key]
        t = _t(self.ref, d)
        if t < 0:
            return 0.0
        rep = self.report
        if ccy == rep:
            if ccy in self.hw:
                hwp, disc = self.hw[ccy]
                j = self.ps.col(t)
                v = float(disc.df(t)) * np.exp(-self.ps.rate_intx[hwp.name][:, j])
            else:
                v = float(self._disc.df(t))
        else:
            pair = f"{ccy}{rep}"
            fx = self.ctx.fx(pair)
            v = fx.forward(d) * float(self._disc.df(t))
        self._df_cache[key] = v
        return v

    def state_vars(self, d: date) -> np.ndarray:
        cols = []
        for nm in sorted(self.infos):
            cols.append(self._asset_col(nm, d))
        for ccy, (hwp, _) in sorted(self.hw.items()):
            cols.append(self.ps.rate_x[hwp.name][:, self.ps.col(_t(self.ref, d))])
        return np.column_stack(cols) if cols else np.zeros((self.n, 1))


# ---------------------------------------------------------------------------
def calibrate_hw(ctx, curve, irvol, a: float, horizon: float, tracker_role: str = "") -> HWProcess:
    """Кусочно-постоянная σ(t) Hull-White по ATM нормальной волатильности каплетов (3М)."""
    exp = [e for e in irvol.expiries if e <= max(horizon, irvol.expiries[0]) + 1e-9] or [irvol.expiries[0]]
    if exp[-1] < horizon and len(irvol.expiries) > len(exp):
        exp.append(irvol.expiries[len(exp)])
    tau = 0.25
    sig = []
    y_prev, t_prev = 0.0, 0.0
    for T in exp:
        F = float(curve.fwd_simple(T, T + tau))
        G = (1 - np.exp(-a * tau)) / a
        sn = irvol.atm_normal(T, tau)
        y_target = (sn * tau / ((1 + tau * F) * G)) ** 2 * T
        dt = T - t_prev
        e2 = np.exp(-2 * a * dt)
        s2 = (y_target - y_prev * e2) * 2 * a / (1 - e2)
        s = np.sqrt(max(s2, 1e-10))
        sig.append(s)
        y_prev = y_prev * e2 + s * s * (1 - e2) / (2 * a)
        t_prev = T
    p = HWProcess("rate:" + curve.currency, a, np.array(exp), np.array(sig),
                  lambda t, c=curve: c.logdf_t(np.asarray(t, float)), lambda t, c=curve: c.inst_fwd(np.asarray(t, float)))
    ctx.tracker.record(UsedInput(f"model:HW1F:{curve.id}", {"a": a, "sigma": [round(float(x), 6) for x in sig]},
                                 Provenance("калибровка Hull-White 1F по нормальной волатильности", None, DataKind.MODEL,
                                            note="скорость возврата к среднему — модельный параметр"),
                                 tracker_role or "модель ставки"))
    return p


class MCEngine:
    def __init__(self, ctx, config: MCConfig | None = None):
        self.ctx = ctx
        self.cfg = config or MCConfig()

    # ------------------------------------------------------------ подготовка
    def _required_dates(self, cp: CProduct, infos) -> tuple[set[date], bool, set[str]]:
        ref = cp.ref_date
        dates: set[date] = set()
        continuous = False
        names = cp.underlying_names()
        for leg in cp.legs:
            for p in leg.periods:
                if p.payment <= ref:
                    continue
                dates.add(p.fixing)
                dates.update(p.obs_dates)
                dates.add(p.payment)
                dates.add(p.start)
                dates.add(p.end)
            mods = list(leg.modifiers) + [m for c in leg.components for m in c.modifiers]
            for m in mods:
                if isinstance(m, BarrierMod):
                    if m.monitoring == "continuous":
                        continuous = True
                    if m.monitoring == "discrete":
                        cal = get_calendar(leg.spec.schedule.fixing_calendar or leg.spec.schedule.calendar)
                        ws = m.window_start or cp.start
                        we = m.window_end or leg.periods[-1].fixing
                        if m.observation == "daily":
                            dates.update(cal.business_days(max(ws, ref), we))
                        elif m.observation != "fixings":
                            from ...core.schedule import roll_dates
                            from ...core.dates import BDC
                            dates.update(cal.adjust(d, BDC.PRECEDING) for d in roll_dates(ws, we, m.observation)[1:])
                if isinstance(m, AccrualMod):
                    cal = get_calendar(leg.spec.schedule.fixing_calendar or leg.spec.schedule.calendar)
                    for p in leg.periods:
                        if p.payment > ref and not p.obs_dates:
                            dates.update(d for d in cal.business_days(max(p.start, ref), p.end))
        for m in cp.modifiers:
            if isinstance(m, BarrierMod):
                if m.monitoring == "continuous":
                    continuous = True
                elif m.monitoring == "discrete" and m.observation == "daily":
                    cal = get_calendar(cp.legs[0].spec.schedule.calendar)
                    dates.update(cal.business_days(max(m.window_start or cp.start, ref), m.window_end or cp.last_payment))
            if isinstance(m, (EarlyTerminationMod, ExerciseMod)):
                dates.update(m.dates)
            if isinstance(m, AutocallMod) and m.dates:
                dates.update(m.dates)
        dates.add(cp.start)
        # сдвиг дат фиксинга на лаг источника
        sim = set()
        for d in dates:
            if d < ref:
                continue
            sim.add(d)
            for nm in names:
                if nm in infos:
                    sd = infos[nm].sim_date(d)
                    if sd >= ref:
                        sim.add(sd)
        return sim, continuous, names

    def _process(self, name: str, info: _Info, t_max: float, vol_model: str, quanto_adj=None) -> AssetProcess:
        ctx = self.ctx
        cls = info.cls
        aid = info.asset_id
        if cls == "fx":
            fxc = ctx.fx(aid, f"форвард {aid}")
            off = (fxc.spot_date - fxc.ref_date).days / 365.0
            fwd = lambda t, c=fxc, o=off: c.forward_t(np.asarray(t, float) + o)
            surf = ctx.fx_vol(aid, t_max, None, f"волатильность {aid}")
        elif cls == "equity":
            fwd = ctx.asset_forward_fn(aid)
            surf = ctx.asset_vol(aid, t_max, None, f"волатильность {aid}")
        elif cls == "commodity":
            if info.spec.contract_month:
                y, m = map(int, info.spec.contract_month.split("-"))
                F0 = ctx.commodity(aid, f"форвард {aid} {info.spec.contract_month}").forward_month((y, m))
                fwd = lambda t, F=F0: np.full_like(np.asarray(t, float), F)
            else:
                cc = ctx.commodity(aid, f"форвардная кривая {aid}")
                fwd = lambda t, c=cc: c.forward_t(np.maximum(np.asarray(t, float), 0.0))
            surf = ctx.asset_vol(aid, t_max, None, f"волатильность {aid}")
        else:
            raise ValueError(f"класс {cls} не моделируется как актив")
        if quanto_adj is not None:
            base_fwd = fwd
            fwd = lambda t, f=base_fwd, q=quanto_adj: f(t) * np.exp(-q * np.asarray(t, float))
        if vol_model == "local_vol" and surf.kind is not DataKind.HISTORICAL and len(surf.slices) > 1:
            if cls == "fx":
                lv = ctx.local_vol(aid, t_max)
            else:
                from ...vol.localvol import dupire_grid
                lv = dupire_grid(surf, t_max)
            return AssetProcess(name, fwd, "local", None, lv)
        surf_ref = surf

        def total_var(t, s=surf_ref):
            return float(s.atm_vol(max(t, 1e-4)) ** 2 * t)
        divs = None
        disc = None
        if cls == "equity":
            eq = ctx.equity(aid)
            divs = eq.dividend_times()
            dcurve = ctx.curve(ctx.config["equities"][aid]["discount"])
            disc = lambda t, c=dcurve: c.df(np.asarray(t, float))
        return AssetProcess(name, fwd, "black", total_var, None, divs, disc)

    def price(self, trade: Trade, cp: CProduct | None = None) -> MCResult:
        ctx = self.ctx
        ref = ctx.ref_date
        cp = cp or compile_trade(trade, ref)
        infos = {nm: _Info(nm, trade.underlyings[nm], ctx, ref) for nm in trade.underlyings
                 if trade.underlyings[nm].asset_class in ("fx", "equity", "commodity")}
        # квантованные/композитные курсы должны моделироваться
        for leg in cp.legs:
            q = leg.settlement.quanto if leg.settlement else None
            if q is not None and q.type == "composite" and not any(i.asset_id == q.pair for i in infos.values()):
                from ...instruments.schema import UnderlyingSpec, FixingSpec
                spec = UnderlyingSpec(asset_class="fx", id=q.pair, fixing=FixingSpec(source=q.fixing_source))
                infos[f"__fx_{q.pair}"] = _Info(f"__fx_{q.pair}", spec, ctx, ref)
        dates, continuous, names = self._required_dates(cp, infos)
        t_max = max(_t(ref, d) for d in dates) if dates else 0.0
        t_max = max(t_max, 1 / 365)
        vol_model = self.cfg.vol_model
        grid = {round(_t(ref, d), 10) for d in dates if d > ref}
        refine = continuous or vol_model == "local_vol"
        if refine:
            step = 1.0 / self.cfg.steps_per_year if vol_model == "local_vol" else 1.0 / 52
            grid |= set(np.round(np.arange(step, t_max + 1e-12, step), 10))
        rate_ccys = sorted({ctx.index(n[5:])["currency"] for n in names if n.startswith("rate:")})
        need_rate_sim = bool(rate_ccys) and self._rate_path_dependent(cp)
        if need_rate_sim:
            step = 1.0 / 52
            grid |= set(np.round(np.arange(step, t_max + 1e-12, step), 10))
        grid = np.array(sorted(g for g in grid if g > 0))
        if len(grid) == 0:
            grid = np.array([1.0 / 365])
        # процессы
        quanto_adj: dict[str, float] = {}
        for leg in cp.legs:
            q = leg.settlement.quanto if leg.settlement else None
            if q is not None and q.type == "quanto":
                for nm in observable_names(leg.observable):
                    if nm in infos:
                        aid = infos[nm].asset_id
                        rho = ctx.correlation(aid, q.pair, "квантовая поправка сноса")
                        fxs = ctx.fx_vol(q.pair, t_max, None, "квантовая поправка")
                        s_x = fxs.atm_vol(t_max)
                        s_s = (ctx.fx_vol(aid) if infos[nm].cls == "fx" else ctx.asset_vol(aid)).atm_vol(t_max)
                        quanto_adj[nm] = rho * s_s * s_x
        processes = [self._process(nm, infos[nm], t_max, vol_model, quanto_adj.get(nm)) for nm in sorted(infos)]
        hw: dict[str, tuple[HWProcess, Any]] = {}
        rates = []
        if need_rate_sim:
            for ccy in rate_ccys:
                disc = ctx.discount_curve(ccy, trade.collateral.collateralized, override=trade.model.discount_override)
                irv = ctx.ir_vol(ctx.index(next(n[5:] for n in names if n.startswith("rate:")))["curve"], t_max)
                hwp = calibrate_hw(ctx, disc, irv, self.cfg.hw_mean_reversion, t_max)
                hw[ccy] = (hwp, disc)
                rates.append(hwp)
        k = len(processes) + len(rates)
        corr = np.eye(k)
        ids = [infos[p.name].asset_id for p in processes] + [f"KEYRATE" if h.name.endswith("RUB") else h.name for h in rates]
        for i in range(k):
            for j in range(i + 1, k):
                try:
                    corr[i, j] = corr[j, i] = ctx.correlation(ids[i], ids[j], "корреляция факторов MC")
                except KeyError:
                    if ids[i] != ids[j]:
                        ctx.tracker.warn(f"Нет корреляции {ids[i]}/{ids[j]} — принята нулевая (модельное допущение)")
        # батчи
        n_total = max(int(self.cfg.paths), 1000)
        nb = max(int(self.cfg.batches), 1)
        per = n_total // nb
        sums, sq, cnt = 0.0, 0.0, 0
        conv = []
        flow_acc: dict[int, float] = {}
        flows_meta = None
        ex_info: dict[str, Any] = {}
        notes: list[str] = []
        all_pv = []
        diag: dict[str, Any] = {}
        for b in range(nb):
            seed_b = int((self.cfg.seed * 1000003 + b * 7919) % (2 ** 63 - 1))
            sim = Simulator(processes, rates, corr, grid, per, seed_b, self.cfg.antithetic)
            ps = sim.run()
            diag = ps.diagnostics
            mv = MCMarketView(ps, ref, ctx, cp, infos, hw, trade.report_currency, trade.collateral.collateralized,
                              trade.model.discount_override)
            res = Evaluator(cp, mv, self.cfg.smoothing).evaluate()
            pv = res.pv_paths
            if self.cfg.antithetic:
                h = len(pv) // 2
                pv_pairs = 0.5 * (pv[:h] + pv[h:])
            else:
                pv_pairs = pv
            all_pv.append(pv_pairs)
            sums += float(pv_pairs.sum())
            sq += float((pv_pairs ** 2).sum())
            cnt += len(pv_pairs)
            mean = sums / cnt
            var = max(sq / cnt - mean * mean, 0.0)
            se = np.sqrt(var / cnt)
            conv.append({"paths": cnt * (2 if self.cfg.antithetic else 1), "value": mean, "stderr": se})
            if flows_meta is None:
                flows_meta = res.flows
            for i, v in enumerate(res.flow_pv):
                flow_acc[i] = flow_acc.get(i, 0.0) + v
            ex_info = res.exercise_info or ex_info
            notes = res.notes
            if self.cfg.target_stderr is not None and se < self.cfg.target_stderr and b >= 1:
                break
        nb_done = len(conv)
        pv_all = np.concatenate(all_pv)
        mean = float(pv_all.mean())
        se = float(pv_all.std(ddof=1) / np.sqrt(len(pv_all)))
        flows_out = []
        for i, f in enumerate(flows_meta or []):
            flows_out.append({"leg": cp.legs[f.leg].name if 0 <= f.leg < len(cp.legs) else "структура",
                              "label": f.label, "kind": f.kind, "fixing": f.fixing.isoformat(), "payment": f.payment.isoformat(),
                              "currency": f.ccy, "expected_amount": float(np.mean(f.amount)),
                              "pv": flow_acc.get(i, 0.0) / nb_done})
        diag["grid_points"] = int(len(grid))
        diag["vol_model"] = vol_model
        diag["rate_model"] = "Hull-White 1F" if hw else "детерминированные ставки"
        diag["quanto_adjustments"] = quanto_adj
        if diag.get("correlation_repaired"):
            ctx.tracker.warn("Корреляционная матрица не была положительно определённой — исправлена (Higham)")
        return MCResult(mean, se, (mean - 1.96 * se, mean + 1.96 * se), int(len(pv_all) * (2 if self.cfg.antithetic else 1)),
                        self.cfg.seed, conv, flows_out, notes, ex_info, diag, pv_all)

    @staticmethod
    def _rate_path_dependent(cp: CProduct) -> bool:
        """Нужна ли стохастическая модель ставки (иначе — детерминированные форварды)."""
        for leg in cp.legs:
            if not isinstance(leg.observable, RateObs):
                continue
            for c in leg.components:
                if c.kind not in ("fixed", "float", "fixed_compounded") or c.modifiers:
                    return True
            if leg.modifiers:
                return True
        return bool(cp.modifiers)
