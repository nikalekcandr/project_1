"""Поверхности волатильности.

* хранение — по срезам (экспирациям) в координатах k = ln(K/F), модель среза
  SVI (по умолчанию) или SABR;
* интерполяция по времени — по общей дисперсии w = σ²T при фиксированном k;
* проверки при каждом построении: выпуклость по страйку (butterfly, g(k) ≥ 0),
  неубывание общей дисперсии по времени (calendar), неотрицательная
  форвардная дисперсия между любыми двумя сроками;
* режим sticky-delta / sticky-strike — параметр, влияющий на греки;
* происхождение каждого столпа; экстраполяция по страйку/времени и
  исторический фоллбэк помечаются и доходят до отчёта.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Callable, Sequence

import numpy as np

from ..core.dates import Tenor, add_tenor
from ..core.provenance import DataKind, InputTracker, Provenance, UsedInput, worst_kind
from ..models.analytic.black import atm_strike, strike_from_delta
from .sabr import SABR, fit_sabr
from .svi import SVI, fit_svi


@dataclass
class Pillar:
    label: str           # ATM, 25C, 25P, 10C, 10P, K=...
    strike: float
    k: float
    vol: float
    kind: DataKind
    quote_ids: tuple[str, ...] = ()
    halfspread: float = 0.0


@dataclass
class SmileSlice:
    expiry: date
    T: float
    forward: float
    model: Any                     # SVI | SABR | None (плоская)
    flat_vol: float | None
    pillars: list[Pillar]
    fit_rmse: float = 0.0
    delivery: date | None = None
    tenor: str = ""

    def w(self, k) -> np.ndarray:
        k = np.asarray(k, float)
        if self.model is None:
            return np.full_like(k, self.flat_vol ** 2 * self.T)
        if isinstance(self.model, SVI):
            return np.maximum(self.model.w(k), 1e-10)
        v = self.model.lognormal_vol(self.forward, self.forward * np.exp(k), self.T)
        return v * v * self.T

    def vol_k(self, k) -> np.ndarray:
        return np.sqrt(self.w(k) / self.T)

    @property
    def kind(self) -> DataKind:
        return worst_kind(p.kind for p in self.pillars) if self.pillars else DataKind.MODEL

    @property
    def k_range(self) -> tuple[float, float]:
        if not self.pillars:
            return (0.0, 0.0)
        ks = [p.k for p in self.pillars]
        return (min(ks), max(ks))


@dataclass
class VolSurface:
    id: str
    asset: str
    ref_date: date
    slices: list[SmileSlice]
    forward_fn: Callable[[np.ndarray], np.ndarray]     # T -> форвард (текущий, с учётом шоков)
    ref_forward_fn: Callable[[np.ndarray], np.ndarray] | None = None   # форвард на момент построения
    sticky: str = "delta"           # 'delta' | 'strike'
    vol_shift: float = 0.0
    method: str = ""
    conventions: dict[str, Any] = field(default_factory=dict)
    inputs: list[UsedInput] = field(default_factory=list)
    arbitrage: list[dict[str, Any]] = field(default_factory=list)
    base_kind: DataKind | None = None

    def __post_init__(self):
        self.slices = sorted(self.slices, key=lambda s: s.T)
        if self.ref_forward_fn is None:
            self.ref_forward_fn = self.forward_fn
        self._T = np.array([s.T for s in self.slices])

    # ------------------------------------------------------------ core
    def total_variance(self, k, T: float) -> np.ndarray:
        k = np.asarray(k, float)
        Ts = self._T
        if T <= Ts[0]:
            w = self.slices[0].w(k) * (T / Ts[0])
        elif T >= Ts[-1]:
            w = self.slices[-1].w(k) * (T / Ts[-1])
        else:
            i = int(np.searchsorted(Ts, T)) - 1
            a = (T - Ts[i]) / (Ts[i + 1] - Ts[i])
            w = (1 - a) * self.slices[i].w(k) + a * self.slices[i + 1].w(k)
        if self.vol_shift:
            v = np.sqrt(np.maximum(w, 0) / max(T, 1e-12)) + self.vol_shift
            w = np.maximum(v, 1e-4) ** 2 * T
        return w

    def vol_k(self, k, T: float) -> np.ndarray:
        T = max(float(T), 1e-6)
        return np.sqrt(np.maximum(self.total_variance(k, T), 1e-14) / T)

    def moneyness(self, K, T: float) -> np.ndarray:
        F = float(np.atleast_1d(self.forward_fn(np.array([T])))[0])
        if self.sticky == "strike":
            Fr = float(np.atleast_1d(self.ref_forward_fn(np.array([T])))[0])
            return np.log(np.asarray(K, float) / Fr)
        return np.log(np.asarray(K, float) / F)

    def vol(self, K, T: float) -> np.ndarray | float:
        r = self.vol_k(self.moneyness(K, T), T)
        return float(r) if np.ndim(r) == 0 else r

    def atm_vol(self, T: float) -> float:
        F = float(np.atleast_1d(self.forward_fn(np.array([T])))[0])
        return float(self.vol(F, T))

    def forward(self, T: float) -> float:
        return float(np.atleast_1d(self.forward_fn(np.array([T])))[0])

    # ------------------------------------------------------------ flags
    def flags_for(self, T: float, K: float | None = None) -> tuple[str, ...]:
        f = []
        if T > self._T[-1] + 1e-9:
            f.append("extrapolated")
        if K is not None:
            k = float(self.moneyness(K, T))
            lo = min(s.k_range[0] for s in self.slices)
            hi = max(s.k_range[1] for s in self.slices)
            scale = np.sqrt(max(T, 1e-4) / max(self._T[0], 1e-4))
            if k < lo * max(scale, 1.0) - 1e-9 or k > hi * max(scale, 1.0) + 1e-9:
                f.append("strike_extrapolated")
        return tuple(f)

    @property
    def kind(self) -> DataKind:
        if self.base_kind is not None:
            return self.base_kind
        return worst_kind(s.kind for s in self.slices)

    def kind_at(self, T: float) -> DataKind:
        """Вид данных срезов, участвующих в интерполяции на сроке T."""
        if self.base_kind is not None:
            return self.base_kind
        i = int(np.searchsorted(self._T, T))
        used = [self.slices[min(max(i - 1, 0), len(self.slices) - 1)], self.slices[min(i, len(self.slices) - 1)]]
        k = worst_kind(s.kind for s in used)
        if T > self._T[-1] + 1e-9 and k is DataKind.MARKET:
            return DataKind.EXTRAPOLATED
        return k

    def pillars_at(self, T: float, delta: float = 0.25) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        """Страйки и волатильности 25Δ-пута, ATM (DNS) и 25Δ-колла на сроке T (по улыбке поверхности)."""
        from ..models.analytic.black import strike_from_delta
        F = self.forward(T)
        atm = float(self.vol(F, T))
        Ka = F * np.exp(0.5 * atm * atm * T)
        va = float(self.vol(Ka, T))
        Ka = F * np.exp(0.5 * va * va * T)
        Kc, Kp = F * 1.05, F * 0.95
        for _ in range(12):
            vc = float(self.vol(Kc, T))
            vp = float(self.vol(Kp, T))
            Kc = strike_from_delta(delta, F, T, vc, 1)
            Kp = strike_from_delta(-delta, F, T, vp, -1)
        return (Kp, Ka, Kc), (float(self.vol(Kp, T)), float(self.vol(Ka, T)), float(self.vol(Kc, T)))

    def register(self, tracker: InputTracker | None, T: float, K: float | None = None, role: str = "") -> None:
        if tracker is None:
            return
        flags = self.flags_for(T, K)
        kind = self.kind_at(T)
        used_q = self.quotes_at(T)
        prov = Provenance(f"поверхность волатильности {self.id}: {self.method}", None,
                          kind if kind.is_model_based else DataKind.DERIVED,
                          note=f"режим sticky-{self.sticky}; срезов {len(self.slices)}",
                          derived_from=tuple(u.id for u in self.inputs if used_q is None or u.id in used_q))
        tracker.record(UsedInput(f"vol:{self.id}", f"T={T:.3f}" + (f", K={K:.6g}" if K is not None else ""),
                                 prov, role, flags))
        if "extrapolated" in flags:
            tracker.warn(f"Волатильность {self.id}: срок {T:.2f} г. за последним столпом — экстраполяция плоской волатильностью")
        if "strike_extrapolated" in flags:
            tracker.warn(f"Волатильность {self.id}: страйк {K:.6g} вне диапазона котируемых дельт — экстраполяция крыла SVI")
        if kind.is_model_based:
            tracker.warn(f"Поверхность {self.id} модельная ({kind.label_ru}): нет рыночного якоря")
        used_q = self.quotes_at(T)
        for u in self.inputs:
            if used_q is None or u.id in used_q:
                tracker.record(u)

    def quotes_at(self, T: float) -> set[str] | None:
        """Котировки срезов, участвующих в интерполяции на сроке T (None — все)."""
        if not any(p.quote_ids for s in self.slices for p in s.pillars):
            return None
        i = int(np.searchsorted(self._T, T))
        idx = {min(max(i - 1, 0), len(self.slices) - 1), min(i, len(self.slices) - 1)}
        return {q for j in idx for p in self.slices[j].pillars for q in p.quote_ids}

    # ------------------------------------------------------------ transforms
    def shifted(self, dv: float) -> "VolSurface":
        return replace(self, vol_shift=self.vol_shift + dv, slices=list(self.slices))

    def with_forward(self, forward_fn: Callable, sticky: str | None = None) -> "VolSurface":
        return replace(self, forward_fn=forward_fn, ref_forward_fn=self.ref_forward_fn,
                       sticky=sticky or self.sticky, slices=list(self.slices))

    def with_slice_shift(self, idx: int, dv: float) -> "VolSurface":
        """Сдвиг одного среза на dv (вега по срокам). Остальные срезы не меняются."""
        s = self.slices[idx]
        w0 = s.w
        new = SmileSlice(s.expiry, s.T, s.forward, None, None, s.pillars, s.fit_rmse, s.delivery, s.tenor)
        T = s.T

        def w_shift(k, _w0=w0, _T=T, _dv=dv):
            v = np.sqrt(np.maximum(_w0(k), 0) / _T) + _dv
            return np.maximum(v, 1e-4) ** 2 * _T
        new.w = w_shift  # type: ignore[method-assign]
        slices = list(self.slices)
        slices[idx] = new
        return replace(self, slices=slices)

    def rolled(self, new_ref: date) -> "VolSurface":
        """Тета: экспирации фиксированы по датам, время до них уменьшается;
        общая дисперсия до экспирации берётся как форвардная дисперсия."""
        d = (new_ref - self.ref_date).days / 365.0
        slices = []
        for s in self.slices:
            if s.T - d <= 1e-6:
                continue
            ns = SmileSlice(s.expiry, s.T - d, s.forward, None, None, s.pillars, s.fit_rmse, s.delivery, s.tenor)
            ratio = (s.T - d) / s.T

            def w_r(k, _w=s.w, _r=ratio):
                return _w(k) * _r
            ns.w = w_r  # type: ignore[method-assign]
            slices.append(ns)
        fwd = self.forward_fn
        rfwd = self.ref_forward_fn
        return replace(self, ref_date=new_ref, slices=slices,
                       forward_fn=lambda T, _f=fwd: _f(np.asarray(T) + d),
                       ref_forward_fn=lambda T, _f=rfwd: _f(np.asarray(T) + d))

    # ------------------------------------------------------------ checks
    def check_arbitrage(self, tol: float = 1e-8) -> list[dict[str, Any]]:
        out = []
        kg = np.linspace(-1.5, 1.5, 121)
        for s in self.slices:
            if isinstance(s.model, SVI):
                sd = np.sqrt(max(float(s.w(0.0)), 1e-8))
                kk = np.linspace(-4 * sd, 4 * sd, 161)
                g = s.model.g(kk)
                if g.min() < -1e-6:
                    out.append({"check": "butterfly", "expiry": s.expiry.isoformat(), "ok": False,
                                "detail": f"min g(k) = {g.min():.2e}: отрицательная плотность"})
                else:
                    out.append({"check": "butterfly", "expiry": s.expiry.isoformat(), "ok": True,
                                "detail": f"min g(k) = {g.min():.3f}"})
        for a, b in zip(self.slices, self.slices[1:]):
            dw = b.w(kg) - a.w(kg)
            ok = bool(dw.min() >= -tol)
            out.append({"check": "calendar", "expiry": f"{a.expiry.isoformat()}→{b.expiry.isoformat()}", "ok": ok,
                        "detail": f"min Δw = {dw.min():.2e}" + ("" if ok else ": общая дисперсия убывает")})
            fv = (b.w(0.0) - a.w(0.0)) / (b.T - a.T)
            out.append({"check": "forward_variance", "expiry": f"{a.expiry.isoformat()}→{b.expiry.isoformat()}",
                        "ok": bool(fv >= -tol), "detail": f"форвардная ATM-волатильность {np.sqrt(max(float(fv), 0)):.4f}"})
        self.arbitrage = out
        return out

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id, "asset": self.asset, "method": self.method, "sticky": self.sticky, "kind": self.kind.value,
            "conventions": self.conventions,
            "slices": [{"expiry": s.expiry.isoformat(), "tenor": s.tenor, "T": s.T, "forward": s.forward,
                        "model": (s.model.params() if isinstance(s.model, SVI) else
                                  {"alpha": s.model.alpha, "beta": s.model.beta, "rho": s.model.rho, "nu": s.model.nu}
                                  if isinstance(s.model, SABR) else {"flat": s.flat_vol}),
                        "fit_rmse": s.fit_rmse,
                        "pillars": [{"label": p.label, "strike": p.strike, "vol": p.vol, "kind": p.kind.value,
                                     "quotes": list(p.quote_ids)} for p in s.pillars]} for s in self.slices],
            "arbitrage": self.arbitrage,
        }


# ---------------------------------------------------------------------------
# Построители
# ---------------------------------------------------------------------------

def _fit_slice(pillars: list[Pillar], T: float, F: float, model: str) -> tuple[Any, float | None, float]:
    if len(pillars) == 1:
        return None, pillars[0].vol, 0.0
    ks = np.array([p.k for p in pillars])
    vs = np.array([p.vol for p in pillars])
    order = np.argsort(ks)
    ks, vs = ks[order], vs[order]
    if model == "sabr":
        s, rmse = fit_sabr(F, T, F * np.exp(ks), vs, beta=1.0)
        return s, None, rmse
    w = vs * vs * T
    if len(pillars) < 5:
        # недоопределённая подгонка: SVI с m=0 и умеренной кривизной (через SABR β=1 как опору)
        s, rmse = fit_sabr(F, T, F * np.exp(ks), vs, beta=1.0)
        kk = np.linspace(ks.min() * 1.5, ks.max() * 1.5, 9)
        vv = s.lognormal_vol(F, F * np.exp(kk), T)
        svi, _ = fit_svi(kk, vv * vv * T)
    else:
        svi, _ = fit_svi(ks, w)
    rmse = float(np.sqrt(np.mean((np.sqrt(svi.w(ks) / T) - vs) ** 2)))
    return svi, None, rmse


def build_fx_surface(
    pair: str,
    ref: date,
    fx_curve,
    domestic,
    pillars: dict[str, dict[str, tuple[float, DataKind, str, float]]],
    *,
    delta_type: str = "spot",
    premium_adjusted: bool = False,
    atm_type: str = "dns",
    long_delta_type: str = "forward",
    long_cutoff_years: float = 1.0,
    model: str = "svi",
    sticky: str = "delta",
    calendar=None,
    inputs: list[UsedInput] | None = None,
) -> VolSurface:
    """FX-поверхность из котировок ATM / RR / BF на 25 и 10 дельт.

    ``pillars[tenor][name] = (значение, вид данных, id котировки, полуспред)``,
    name ∈ {ATM, RR25, BF25, RR10, BF10}. Используется smile-strangle
    конвенция: σ25C = ATM + BF25 + RR25/2, σ25P = ATM + BF25 − RR25/2.
    """
    slices: list[SmileSlice] = []
    s_today = fx_curve.spot_today()
    lag_bd = calendar.business_days_between(ref, fx_curve.spot_date) if calendar else 0
    for tenor, q in sorted(pillars.items(), key=lambda kv: Tenor.parse(kv[0]).approx_years):
        delivery = add_tenor(fx_curve.spot_date, tenor, calendar) if calendar else add_tenor(fx_curve.spot_date, tenor)
        expiry = calendar.advance_business_days(delivery, -lag_bd) if (calendar and lag_bd) else delivery
        if expiry <= ref:
            continue
        T = (expiry - ref).days / 365.0
        F = fx_curve.forward(delivery)
        df_d = float(domestic.df(domestic.time(delivery)))
        df_f = F * df_d / s_today
        dtype = delta_type if T <= long_cutoff_years + 1e-9 else long_delta_type
        atm, ka, qa, ha = q["ATM"]
        pl: list[Pillar] = []
        K_atm = atm_strike(F, T, atm, atm_type, premium_adjusted)
        pl.append(Pillar("ATM", K_atm, np.log(K_atm / F), atm, ka, (qa,), ha))
        for dlt in ("25", "10"):
            if f"RR{dlt}" in q and f"BF{dlt}" in q:
                rr, krr, qrr, hrr = q[f"RR{dlt}"]
                bf, kbf, qbf, hbf = q[f"BF{dlt}"]
                vc = atm + bf + 0.5 * rr
                vp = atm + bf - 0.5 * rr
                d = int(dlt) / 100.0
                Kc = strike_from_delta(d, F, T, vc, 1, dtype, premium_adjusted, df_f)
                Kp = strike_from_delta(-d, F, T, vp, -1, dtype, premium_adjusted, df_f)
                kind = worst_kind([ka, krr, kbf])
                hs = ha + 0.5 * hrr + hbf
                pl.append(Pillar(f"{dlt}C", Kc, np.log(Kc / F), vc, kind, (qa, qrr, qbf), hs))
                pl.append(Pillar(f"{dlt}P", Kp, np.log(Kp / F), vp, kind, (qa, qrr, qbf), hs))
        mdl, flat, rmse = _fit_slice(pl, T, F, model)
        slices.append(SmileSlice(expiry, T, F, mdl, flat, pl, rmse, delivery, tenor))

    def fwd_fn(T, _fx=fx_curve):
        return _fx.forward_t(np.asarray(T, float) + (_fx.spot_date - _fx.ref_date).days / 365.0)

    surf = VolSurface(f"FX.{pair}", pair, ref, slices, fwd_fn, None, sticky,
                      method=f"дельта-столпы ATM/RR/BF, {model.upper()} по срезам, интерполяция по общей дисперсии",
                      conventions={"delta_type": delta_type, "long_delta_type": long_delta_type,
                                   "premium_adjusted": premium_adjusted, "atm_type": atm_type,
                                   "butterfly": "smile strangle"},
                      inputs=list(inputs or []))
    surf.check_arbitrage()
    return surf


def build_strike_surface(asset: str, ref: date, forward_fn: Callable, data: Sequence[tuple[date, Sequence[float], Sequence[float], DataKind, str]],
                         model: str = "svi", sticky: str = "strike", inputs: list[UsedInput] | None = None,
                         sid: str | None = None) -> VolSurface:
    """Поверхность из срезов (экспирация, страйки, волатильности) — например, опционы Мосбиржи."""
    slices = []
    for expiry, strikes, vols, kind, qid in data:
        T = (expiry - ref).days / 365.0
        F = float(np.atleast_1d(forward_fn(np.array([T])))[0])
        pl = [Pillar(f"K={K:g}", float(K), float(np.log(K / F)), float(v), kind, (qid,)) for K, v in zip(strikes, vols)]
        mdl, flat, rmse = _fit_slice(pl, T, F, model)
        slices.append(SmileSlice(expiry, T, F, mdl, flat, pl, rmse))
    surf = VolSurface(sid or f"VOL.{asset}", asset, ref, slices, forward_fn, None, sticky,
                      method=f"срезы по страйкам, {model.upper()}", inputs=list(inputs or []))
    surf.check_arbitrage()
    return surf


def flat_surface(asset: str, ref: date, forward_fn: Callable, vol: float, kind: DataKind, note: str,
                 inputs: list[UsedInput] | None = None, term: Sequence[tuple[float, float]] | None = None,
                 sid: str | None = None) -> VolSurface:
    """Плоская (по страйку) поверхность — фоллбэк (историческая оценка/модель), помечается."""
    pts = term or [(1.0, vol)]
    slices = []
    for T, v in pts:
        d = date.fromordinal(ref.toordinal() + max(int(round(T * 365)), 1))
        slices.append(SmileSlice(d, T, float(np.atleast_1d(forward_fn(np.array([T])))[0]), None, v,
                                 [Pillar("ATM", 0.0, 0.0, v, kind)]))
    return VolSurface(sid or f"VOL.{asset}", asset, ref, slices, forward_fn, None, "strike", method=note,
                      inputs=list(inputs or []), base_kind=kind)
