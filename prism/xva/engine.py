"""CVA и прочие XVA.

CVA — обязательный модуль первой очереди: он отделяет обоснованную часть
цены (кредитный риск и капитал) от наценки.

* профили экспозиции: Монте-Карло по сетке дат, EE / EPE / ENE / PFE;
  стоимость сделки на дату — AMC (регрессия будущих потоков по
  переменным состояния на тех же путях, что и выплата), поэтому подходит
  для любой композиционной структуры;
* неттинг-сет по условиям генерального соглашения: для российских
  соглашений ликвидационный неттинг применим при выполнении условий
  ст. 4.1 127-ФЗ (в т.ч. информация о договоре в репозитарии) — иначе
  экспозиция считается брутто;
* режимы обеспечения: без CSA, односторонний (вносит клиент / банк),
  двусторонний с порогом и MTA, период риска маржи (MPoR);
* прокси кредитных спредов — общий модуль кредитных кривых;
* wrong-way risk: альфа-множитель (минимум) и стохастическая интенсивность
  дефолта, коррелированная с рыночным фактором (целевой подход);
* вторая очередь: FVA (FCA/FBA), KVA (упрощённый SA-CCR-подобный капитал),
  ColVA/MVA — с явной пометкой допущений.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np

from ..core.provenance import DataKind, InputTracker, Provenance, UsedInput
from ..instruments.schema import BarrierMod, TargetMod, Trade
from ..models.mc.engine import MCConfig, MCEngine, MCMarketView, _Info, calibrate_hw
from ..models.mc.paths import Simulator
from ..payoff.compile import compile_trade
from ..payoff.evaluate import Evaluator


@dataclass
class XVAConfig:
    paths: int = 4000
    seed: int = 777
    pfe_quantile: float = 0.975
    wwr_alpha: float = 1.4
    wwr_beta: float | None = None          # чувствительность лог-интенсивности к фактору (σ-единицы); None — из карточки
    wwr_driver: str | None = None          # фактор WWR (например, USDRUB); по умолчанию — первый валютный базис
    funding_spread: float = 0.015          # спред фондирования банка к дисконтной кривой (модельное допущение)
    capital_ratio: float = 0.12            # достаточность капитала, применяемая к RWA (допущение)
    risk_weight: float = 1.0               # риск-вес контрагента (корпоративный — 100%)
    cost_of_capital: float = 0.18          # требуемая доходность на капитал
    hw_a: float = 0.10
    grid_months: int = 1


@dataclass
class XVAResult:
    times: list[float]
    dates: list[str]
    ee: list[float]
    ene: list[float]
    pfe: list[float]
    epe: float
    eepe: float
    cva: float
    dva: float
    cva_wwr_alpha: float
    cva_wwr_stochastic: float | None
    fca: float
    fba: float
    kva: float
    method: dict[str, Any]
    trade_values_t0: dict[str, float]
    netting: str
    collateral: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict
        return asdict(self)

    @property
    def total_credit_charge(self) -> float:
        """Обоснованная кредитная составляющая цены для банка (CVA с учётом WWR-минимума)."""
        return max(self.cva_wwr_stochastic or 0.0, self.cva)


def _exposure_grid(ref: date, mat: date, months: int, mpor_days: int) -> list[date]:
    out = [ref]
    d = ref
    k = 0
    while d < mat:
        k += 1
        d = ref + timedelta(days=7 * k) if k <= 4 else ref + timedelta(days=28 + 30.4 * months * (k - 4))
        out.append(min(d, mat))
    out = sorted(set(out))
    lagged = sorted({x - timedelta(days=int(mpor_days * 1.4)) for x in out[1:]} - set(out))
    return sorted(set(out) | {x for x in lagged if x > ref})


def _basis(cols: list[np.ndarray]) -> np.ndarray:
    n = len(cols[0])
    out = [np.ones(n)]
    for c in cols:
        sd = c.std()
        if sd < 1e-14:
            continue
        z = (c - c.mean()) / sd
        out += [z, z * z, z ** 3]
    if len(cols) >= 2:
        z0 = (cols[0] - cols[0].mean()) / max(cols[0].std(), 1e-14)
        z1 = (cols[1] - cols[1].mean()) / max(cols[1].std(), 1e-14)
        out.append(z0 * z1)
    return np.column_stack(out)


def compute_xva(trades: list[Trade], ctx, cfg: XVAConfig | None = None) -> XVAResult:
    cfg = cfg or XVAConfig()
    ref = ctx.ref_date
    warnings: list[str] = []
    t0 = trades[0]
    client = t0.identification.client
    bank = t0.identification.bank
    coll = t0.collateral
    ma = t0.identification.master_agreement
    netting_ok = ma.type != "NONE" and ma.close_out_netting and (ma.type == "ISDA" or ma.registered_in_repository)
    if ma.type.startswith("RU_") and not ma.registered_in_repository:
        warnings.append("Генсоглашение не зарегистрировано в репозитарии: ликвидационный неттинг (ст. 4.1 127-ФЗ) "
                        "не применим — экспозиция брутто")
    report = t0.report_currency
    mat = max(t.maturity for t in trades)
    grid_dates = _exposure_grid(ref, mat, cfg.grid_months, coll.mpor_days)
    cps = [compile_trade(t, ref) for t in trades]
    # базисы всех сделок
    infos: dict[str, _Info] = {}
    names_by_trade = []
    for t in trades:
        nm_map = {}
        for nm, spec in t.underlyings.items():
            if spec.asset_class in ("fx", "equity", "commodity"):
                key = f"{spec.asset_class}:{spec.id}"
                if key not in infos:
                    infos[key] = _Info(key, spec, ctx, ref)
                nm_map[nm] = key
        names_by_trade.append(nm_map)
    # фактор WWR — первый валютный базис (или указанный)
    fx_keys = [k for k, i in infos.items() if i.cls == "fx"]
    driver = cfg.wwr_driver or (infos[fx_keys[0]].asset_id if fx_keys else None)
    if driver and not any(i.asset_id == driver for i in infos.values()) and driver in ctx.config.get("fx", {}):
        from ..instruments.schema import UnderlyingSpec
        infos[f"fx:{driver}"] = _Info(f"fx:{driver}", UnderlyingSpec(asset_class="fx", id=driver), ctx, ref)
    # даты, нужные сделкам
    eng = MCEngine(ctx, MCConfig(paths=cfg.paths, seed=cfg.seed, vol_model="black"))
    all_dates = set(grid_dates)
    for t, cp, nm_map in zip(trades, cps, names_by_trade):
        inf_t = {nm: infos[k] for nm, k in nm_map.items()}
        ds, _, _ = eng._required_dates(cp, inf_t)
        all_dates |= ds
    t_max = max((d - ref).days for d in all_dates) / 365.0
    times = sorted({round((d - ref).days / 365.0, 10) for d in all_dates if d > ref})
    step = 1.0 / 52
    times = sorted(set(times) | set(np.round(np.arange(step, t_max + 1e-12, step), 10)))
    processes = [eng._process(k, infos[k], t_max, "black") for k in sorted(infos)]
    # ставка RUB — всегда стохастическая для экспозиции процентных сделок и дисконтирования
    has_rates = any(l.is_rate for cp in cps for l in cp.legs)
    rates, hw = [], {}
    if has_rates:
        disc = ctx.discount_curve(report, coll.collateralized)
        irv = ctx.ir_vol("RUB.KEYRATE", t_max)
        hwp = calibrate_hw(ctx, disc, irv, cfg.hw_a, t_max, "экспозиция: модель ставки RUB")
        rates.append(hwp)
        hw[report] = (hwp, disc)
    k = len(processes) + len(rates)
    ids = [infos[p.name].asset_id for p in processes] + ["KEYRATE" for _ in rates]
    corr = np.eye(k)
    for i in range(k):
        for j in range(i + 1, k):
            try:
                corr[i, j] = corr[j, i] = ctx.correlation(ids[i], ids[j], "корреляции факторов экспозиции")
            except KeyError:
                pass
    sim = Simulator(processes, rates, corr, np.array(times), cfg.paths, cfg.seed, True, martingale_correction=True)
    ps = sim.run()
    n = ps.n_paths
    disc = ctx.discount_curve(report, coll.collateralized)
    gt = np.array([(d - ref).days / 365.0 for d in grid_dates])
    # стоимости сделок на датах сетки (AMC)
    values = np.zeros((len(trades), n, len(grid_dates)))
    v0s = {}
    for ti, (t, cp, nm_map) in enumerate(zip(trades, cps, names_by_trade)):
        # пути под имена базисов сделки
        ps_t = type(ps)(ps.times, {nm: ps.values[k] for nm, k in nm_map.items()},
                        {nm: ps.step_vol[k] for nm, k in nm_map.items()}, ps.rate_x, ps.rate_intx, n, ps.seed, ps.diagnostics)
        inf_t = {nm: infos[k] for nm, k in nm_map.items()}
        mv = MCMarketView(ps_t, ref, ctx, cp, inf_t, hw, report, coll.collateralized, t.model.discount_override)
        ev = Evaluator(cp, mv, 0.0)
        flows = ev.flows()
        # PV(0) каждого потока по пути
        pv_f = []
        for f in flows:
            if f.hit_dist is not None:
                v = sum((h * ev._to_report(f.ccy, d, f) for d, h in f.hit_dist), np.zeros(n))
                pay_t = np.full(n, (f.payment - ref).days / 365.0)
            else:
                v = f.amount * ev._to_report(f.ccy, f.payment, f)
            pv_f.append(np.broadcast_to(v, (n,)).astype(float))
        pay = np.array([(f.payment - ref).days / 365.0 for f in flows])
        fix = np.array([(f.fixing - ref).days / 365.0 for f in flows])
        has_bar = any(isinstance(m, BarrierMod) for leg in t.legs for c in leg.components for m in c.modifiers) or \
            any(isinstance(m, BarrierMod) for m in t.modifiers) or any(isinstance(m, BarrierMod) for leg in t.legs for m in leg.modifiers)
        has_tgt = any(isinstance(m, TargetMod) for m in t.modifiers)
        for gi, (gd, tg) in enumerate(zip(grid_dates, gt)):
            # PV на дату tg = E[Σ_{pay>tg} PV0 / D(0,tg) | F_tg]
            if hw:
                hwp, dc = hw[report]
                j = ps.col(tg) if tg > 0 else 0
                D_t = float(dc.df(tg)) * np.exp(-ps.rate_intx[hwp.name][:, j]) if tg > 0 else np.ones(n)
            else:
                D_t = np.full(n, float(disc.df(tg)))
            fut = [i for i in range(len(flows)) if pay[i] > tg + 1e-12]
            if not fut:
                continue
            known = sum((pv_f[i] for i in fut if fix[i] <= tg + 1e-12), np.zeros(n)) / D_t
            unknown = sum((pv_f[i] for i in fut if fix[i] > tg + 1e-12), np.zeros(n)) / D_t
            if tg <= 0:
                values[ti, :, gi] = float(np.mean(known + unknown))
                continue
            cols = []
            jj = ps.col(tg)
            for nm in sorted(nm_map):
                path = ps.values[nm_map[nm]]
                cols.append(path[:, jj])
                if has_bar:
                    cols.append(path[:, : jj + 1].max(axis=1))
                    cols.append(path[:, : jj + 1].min(axis=1))
            if has_tgt:
                acc = sum((np.maximum(pv_f[i], 0) for i in range(len(flows)) if fix[i] <= tg), np.zeros(n))
                cols.append(acc)
            if hw:
                cols.append(ps.rate_x[hw[report][0].name][:, jj])
            if np.allclose(unknown, unknown[0]) or not cols:
                cond = np.full(n, float(np.mean(unknown)))
            else:
                B = _basis(cols)
                coef, *_ = np.linalg.lstsq(B, unknown, rcond=None)
                cond = B @ coef
            values[ti, :, gi] = known + cond
        v0s[t.identification.trade_id] = float(values[ti, :, 0].mean())
    # банк: стоимость = − стоимость клиента
    vb = -values
    if netting_ok:
        vb_ns = vb.sum(axis=0)[None, :, :]
    else:
        vb_ns = vb
    # обеспечение с лагом MPoR
    lag = timedelta(days=int(coll.mpor_days * 1.4))
    expo_idx = [i for i, d in enumerate(grid_dates) if d == ref or (d - lag) in grid_dates or d >= mat or True]
    main_dates = sorted(set(_exposure_grid(ref, mat, cfg.grid_months, 0)))
    main_idx = [grid_dates.index(d) for d in main_dates if d in grid_dates]

    def collateral(vlag):
        if coll.regime == "none":
            return np.zeros_like(vlag)
        c_from_client = np.maximum(vlag - coll.threshold_client, 0.0)
        c_from_bank = np.maximum(-vlag - coll.threshold_bank, 0.0)
        if coll.regime == "one_way_client":
            c = c_from_client
        elif coll.regime == "one_way_bank":
            c = -c_from_bank
        else:
            c = c_from_client - c_from_bank
        return np.where(np.abs(c) < coll.mta, 0.0, c) + coll.independent_amount

    EE, ENE, PFE = [], [], []
    E_paths, N_paths = [], []
    for gi in main_idx:
        d = grid_dates[gi]
        lag_d = d - lag
        li = max((i for i, x in enumerate(grid_dates) if x <= lag_d), default=0) if d > ref else gi
        e_tot = np.zeros(n)
        ne_tot = np.zeros(n)
        for s in range(vb_ns.shape[0]):
            v = vb_ns[s, :, gi]
            c = collateral(vb_ns[s, :, li]) if d > ref else np.zeros(n)
            e_tot += np.maximum(v - c, 0.0)
            ne_tot += np.maximum(-(v - c), 0.0)
        E_paths.append(e_tot)
        N_paths.append(ne_tot)
        EE.append(float(e_tot.mean()))
        ENE.append(float(ne_tot.mean()))
        PFE.append(float(np.quantile(e_tot, cfg.pfe_quantile)))
    mt = np.array([(grid_dates[i] - ref).days / 365.0 for i in main_idx])
    dfs = disc.df(mt)
    # кредитные кривые (общий модуль)
    hc = ctx.credit_curve(client, "CVA: дефолт клиента")
    hb = ctx.credit_curve(bank, "DVA: дефолт банка")
    surv_c = hc.survival(mt)
    surv_b = hb.survival(mt)
    dpd_c = np.concatenate([[0.0], -np.diff(surv_c)])
    dpd_b = np.concatenate([[0.0], -np.diff(surv_b)])
    ee_d = np.array(EE) * dfs
    ene_d = np.array(ENE) * dfs
    # средняя экспозиция на интервале (трапеция)
    ee_mid = np.concatenate([[0.0], 0.5 * (ee_d[1:] + ee_d[:-1])])
    ene_mid = np.concatenate([[0.0], 0.5 * (ene_d[1:] + ene_d[:-1])])
    cva = float((1 - hc.recovery) * np.sum(ee_mid * dpd_c))
    dva = float((1 - hb.recovery) * np.sum(ene_mid * dpd_b))
    # EPE / эффективная EPE (первый год)
    dt = np.diff(mt)
    yr = mt <= 1.0 + 1e-9
    def tavg(x, mask):
        xm = np.asarray(x)[mask]
        tm = mt[mask]
        if len(tm) < 2:
            return float(xm.mean()) if len(xm) else 0.0
        return float(np.trapezoid(xm, tm) / (tm[-1] - tm[0]))
    epe = tavg(EE, np.ones_like(mt, bool))
    eee = np.maximum.accumulate(EE)
    eepe = tavg(eee, yr)
    # WWR: стохастическая интенсивность, коррелированная с фактором
    beta = cfg.wwr_beta
    ent = ctx.credit_entities().get(client, {})
    if beta is None:
        beta = float(ent.get("wwr_beta", 0.0)) if ent else 0.0
        if beta == 0.0 and ent.get("sector") in ("trade", "import"):
            beta = 0.5   # импортёр: девальвация ухудшает кредитное качество (модельное допущение)
    cva_stoch = None
    drv_key = next((k for k, i in infos.items() if i.asset_id == driver), None)
    if drv_key is not None and beta:
        path = ps.values[drv_key]
        cols = [ps.col(t) if t > 0 else 0 for t in mt]
        x = np.log(path[:, cols] / path[:, [0]])
        sd = x.std(axis=0)
        z = np.where(sd > 1e-12, (x - x.mean(axis=0)) / np.maximum(sd, 1e-12), 0.0)
        lam = hc.hazard(np.maximum(mt, 1e-6))[None, :] * np.exp(beta * z - 0.5 * beta * beta)
        cum = np.cumsum(np.concatenate([np.zeros((n, 1)), lam[:, 1:] * dt[None, :]], axis=1), axis=1)
        S_path = np.exp(-cum)
        dPD = np.concatenate([np.zeros((n, 1)), -np.diff(S_path, axis=1)], axis=1)
        E = np.column_stack(E_paths) * dfs[None, :]
        Em = np.concatenate([np.zeros((n, 1)), 0.5 * (E[:, 1:] + E[:, :-1])], axis=1)
        cva_stoch = float((1 - hc.recovery) * np.mean(np.sum(Em * dPD, axis=1)))
        ctx.tracker.record(UsedInput("model:WWR_BETA", beta, Provenance(
            "WWR: чувствительность лог-интенсивности дефолта клиента к фактору", None, DataKind.MODEL,
            note=f"фактор {driver}; положительное значение — ухудшение кредита при росте курса"), "wrong-way risk"))
    # FVA и KVA (вторая очередь, допущения помечены)
    unc = coll.regime == "none"
    fca = float(cfg.funding_spread * np.sum(0.5 * (ee_d[1:] + ee_d[:-1]) * dt)) if unc else 0.0
    fba = float(cfg.funding_spread * np.sum(0.5 * (ene_d[1:] + ene_d[:-1]) * dt)) if unc else 0.0
    ead = cfg.wwr_alpha * eee
    capital = ead * cfg.risk_weight * cfg.capital_ratio
    kva = float(cfg.cost_of_capital * np.sum(0.5 * (capital[1:] * dfs[1:] + capital[:-1] * dfs[:-1]) * dt))
    for nm, val, note in (("model:FUNDING_SPREAD", cfg.funding_spread, "спред фондирования банка (FCA/FBA)"),
                          ("model:CAPITAL", {"ratio": cfg.capital_ratio, "rw": cfg.risk_weight, "coc": cfg.cost_of_capital},
                           "KVA: капитал = α·EEE·RW·норматив; требует сверки с положениями Банка России"),
                          ("model:WWR_ALPHA", cfg.wwr_alpha, "альфа-множитель WWR (минимальное требование)")):
        ctx.tracker.record(UsedInput(nm, val, Provenance(note, None, DataKind.MODEL), "XVA"))
    method = {
        "exposure": "AMC: регрессия будущих потоков по состоянию (уровни, экстремумы для барьеров, накопление для TARF, "
                    "фактор ставки)", "paths": n, "seed": cfg.seed,
        "risk_factors": [infos[p.name].asset_id for p in processes] + (["RUB rate (HW1F)"] if rates else []),
        "vol_model": "Блэк с временной структурой ATM",
        "credit_client": hc.describe(), "credit_bank": hb.describe(),
        "wwr": {"alpha": cfg.wwr_alpha, "beta": beta, "driver": driver},
    }
    return XVAResult(mt.tolist(), [grid_dates[i].isoformat() for i in main_idx], EE, ENE, PFE, epe, eepe, cva, dva,
                     cfg.wwr_alpha * cva, cva_stoch, fca, fba, kva, method, v0s,
                     "неттинг по генсоглашению" if netting_ok else "брутто (неттинг неприменим)",
                     coll.regime, warnings)
