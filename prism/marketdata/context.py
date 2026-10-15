"""Контекст рынка: собранные из снапшота кривые, поверхности и т.д.

Движок оценки не ходит за данными сам: он получает контекст, а контекст
регистрирует каждое обращение в :class:`InputTracker`.

Производные контексты:

* :meth:`MarketContext.bumped` — перекотировка отдельных котировок с
  пересборкой только зависимых объектов (ключевые сроки DV01, вега по
  столпам);
* :meth:`MarketContext.with_shocks` — сценарные шоки поверх собранных
  объектов (курс, параллельные/непараллельные сдвиги кривых, волатильность);
* :meth:`MarketContext.rolled` — сдвиг даты (тета).
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import yaml

from ..core.calendars import get_calendar
from ..core.dates import Tenor, add_tenor
from ..core.daycount import DayCount
from ..core.provenance import DataKind, InputTracker, Provenance, UsedInput
from ..curves.base import YieldCurve
from ..curves.bootstrap import (SELF, BasisSwapInstrument, DepositInstrument, deposit_from_tenor, fit_curve,
                                swap_from_tenor)
from ..curves.cbr import Meeting, check_meeting_coverage, implied_meeting_path, load_meetings
from ..curves.commodity import CommodityCurve, EquityForward
from ..curves.credit import BondObs, HazardCurve, from_bond_spreads, from_rating
from ..curves.fx import FXForwardCurve, cip_diagnostics
from ..curves.inflation import CPICurve, estimate_seasonality
from ..curves.kbd import kbd_curve
from ..vol.ir import RateVol, historical_normal_vol
from ..vol.localvol import LocalVolGrid, dupire_grid
from ..vol.surface import VolSurface, build_fx_surface, build_strike_surface, flat_surface
from .snapshot import MarketSnapshot, Quote

CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "market_config.yaml"


@lru_cache(maxsize=4)
def _load_config(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def default_config() -> dict:
    return _load_config(str(CONFIG_PATH))


class MissingMarketData(KeyError):
    pass


class MissingFixing(MissingMarketData):
    pass


@dataclass(frozen=True)
class Shock:
    """Сценарный шок.

    kind: fx | curve | vol | irvol | credit | cpi | commodity | equity | corr
    target: шаблон с * (например, '*RUB', 'RUB.*', 'USDRUB')
    value: величина; mode: 'relative' (множитель 1+value) | 'absolute'
    fn: для непараллельных сдвигов кривой — функция t -> Δz(t)
    """
    kind: str
    target: str
    value: float = 0.0
    mode: str = "absolute"
    fn: Callable | None = None
    label: str = ""

    def matches(self, name: str) -> bool:
        return fnmatch.fnmatch(name, self.target)


class MarketContext:
    def __init__(self, snapshot: MarketSnapshot, config: dict | None = None, *, tracker: InputTracker | None = None,
                 overrides: dict[str, float] | None = None, shocks: tuple[Shock, ...] = (),
                 ref_date: date | None = None, sticky: str | None = None, _cache: dict | None = None,
                 _deps: dict | None = None, allow_projected_fixings: bool = False, _warm: dict | None = None):
        self.snapshot = snapshot
        self.config = config or default_config()
        self.tracker = tracker if tracker is not None else InputTracker()
        self.overrides = dict(overrides or {})
        self.shocks = tuple(shocks)
        self.base_date = snapshot.as_of.date()
        self.ref_date = ref_date or self.base_date
        self.sticky_override = sticky
        self.allow_projected_fixings = allow_projected_fixings
        self._cache: dict[str, Any] = dict(_cache or {})
        self._deps: dict[str, set[str]] = {k: set(v) for k, v in (_deps or {}).items()}
        self._building: list[str] = []
        self._warm: dict[str, Any] = _warm if _warm is not None else {}   # тёплый старт калибровок (общий для производных контекстов)

    # ================================================================ quotes
    @property
    def as_of(self) -> datetime:
        return self.snapshot.as_of

    def _quote(self, qid: str) -> Quote:
        for b in self._building:
            self._deps.setdefault(b, set()).add(qid)
        q = self.snapshot.get(qid)
        if q is None:
            raise MissingMarketData(f"нет котировки {qid} в снапшоте {self.snapshot.id}")
        if qid in self.overrides:
            q = q.with_value(self.overrides[qid], note="перекотировка (бамп)")
        return q

    def _quotes(self, prefix: str) -> list[Quote]:
        for b in self._building:
            self._deps.setdefault(b, set()).add(prefix + "*")
        out = []
        for q in self.snapshot.find(prefix):
            if q.id in self.overrides:
                q = q.with_value(self.overrides[q.id], note="перекотировка (бамп)")
            out.append(q)
        return out

    def _dataset(self, name: str):
        for b in self._building:
            self._deps.setdefault(b, set()).add("ds:" + name)
        return self.snapshot.dataset(name)

    def has_quote(self, qid: str) -> bool:
        return self.snapshot.get(qid) is not None

    def quote_value(self, qid: str, role: str = "") -> float:
        q = self._quote(qid)
        self.tracker.record(UsedInput(q.id, q.value, q.provenance, role))
        return float(q.value)

    @staticmethod
    def _used(q: Quote, role: str = "") -> UsedInput:
        return UsedInput(q.id, q.value, q.provenance, role)

    def _cached(self, key: str, builder: Callable[[], Any]):
        for b in self._building:
            if b != key:
                self._deps.setdefault(b, set()).add("obj:" + key)
        if key in self._cache:
            return self._cache[key]
        if key in self._building:
            raise RuntimeError(f"циклическая зависимость при построении {key}")
        self._building.append(key)
        try:
            obj = builder()
        finally:
            self._building.pop()
        # зависимости вложенных объектов наследуются
        self._cache[key] = obj
        return obj

    # ================================================================ derived contexts
    def _child(self, **kw) -> "MarketContext":
        args = dict(snapshot=self.snapshot, config=self.config, tracker=self.tracker, overrides=self.overrides,
                    shocks=self.shocks, ref_date=self.ref_date, sticky=self.sticky_override,
                    allow_projected_fixings=self.allow_projected_fixings, _warm=self._warm)
        args.update(kw)
        return MarketContext(**args)

    def bumped(self, bumps: dict[str, float], tracker: InputTracker | None = None) -> "MarketContext":
        """Новый контекст с абсолютными сдвигами котировок; пересобираются только зависимые объекты."""
        ov = dict(self.overrides)
        for qid, dv in bumps.items():
            base = ov.get(qid, self.snapshot.quote(qid).value)
            ov[qid] = float(base) + dv
        memo: dict[str, bool] = {}

        def invalid(key: str, depth: int = 0) -> bool:
            if key in memo:
                return memo[key]
            memo[key] = False
            hit = False
            for dep in self._deps.get(key, set()):
                if dep.startswith("obj:"):
                    if depth < 20 and invalid(dep[4:], depth + 1):
                        hit = True
                        break
                    continue
                for qid in bumps:
                    if dep == qid or (dep.endswith("*") and qid.startswith(dep[:-1])):
                        hit = True
                        break
                if hit:
                    break
            memo[key] = hit
            return hit

        cache = {k: v for k, v in self._cache.items() if not invalid(k)}
        deps = {k: set(v) for k, v in self._deps.items() if k in cache}
        return self._child(overrides=ov, tracker=tracker or InputTracker(), _cache=cache, _deps=deps)

    def with_shocks(self, shocks: Iterable[Shock], tracker: InputTracker | None = None) -> "MarketContext":
        return self._child(shocks=self.shocks + tuple(shocks), tracker=tracker or InputTracker(), _cache=self._cache,
                           _deps=self._deps)

    def with_sticky(self, sticky: str) -> "MarketContext":
        return self._child(sticky=sticky, _cache=self._cache, _deps=self._deps)

    def rolled(self, days: int = 1, tracker: InputTracker | None = None) -> "MarketContext":
        new = date.fromordinal(self.ref_date.toordinal() + days)
        return self._child(ref_date=new, tracker=tracker or InputTracker(), _cache=self._cache, _deps=self._deps,
                           allow_projected_fixings=True)

    def with_tracker(self, tracker: InputTracker) -> "MarketContext":
        return self._child(tracker=tracker, _cache=self._cache, _deps=self._deps)

    def _shocks(self, kind: str, name: str) -> list[Shock]:
        return [s for s in self.shocks if s.kind == kind and s.matches(name)]

    @property
    def is_rolled(self) -> bool:
        return self.ref_date != self.base_date

    # ================================================================ calendars / meetings
    def meetings(self) -> list[Meeting]:
        def build():
            ds = self._dataset("cbr_meetings")
            return load_meetings(ds.data), ds.provenance
        ms, prov = self._cached("meetings", build)
        self.tracker.record(UsedInput("ds:cbr_meetings", f"{len(ms)} заседаний", prov, "календарь заседаний Банка России"))
        msg = check_meeting_coverage(ms, self.base_date)
        if msg:
            self.tracker.warn("Календарь заседаний ЦБ: " + msg)
        return ms

    # ================================================================ curves
    def curve(self, cid: str, role: str = "", t_max: float | None = None, purpose: str = "") -> YieldCurve:
        base = self._cached(f"curve:{cid}", lambda: self._build_curve(cid))
        c = base
        kinds = ["curve"] + ([f"curve_{purpose}"] if purpose else [])
        for kind in kinds:
            for s in self._shocks(kind, cid):
                if s.fn is not None and c.shift_fn is not None:
                    f0, f1 = c.shift_fn, s.fn
                    c = c.shifted(dz=s.value, fn=lambda t, a=f0, b=f1: a(t) + b(t))
                else:
                    c = c.shifted(dz=s.value if s.fn is None else 0.0, fn=s.fn if s.fn is not None else None)
        if self.is_rolled:
            c = c.rolled(self.ref_date)
        if role or t_max is not None:
            c.register(self.tracker, t_max if t_max is not None else 0.0, role)
        return c

    def curve_fit_report(self, cid: str) -> dict[str, Any]:
        c = self._cached(f"curve:{cid}", lambda: self._build_curve(cid))
        return {"id": c.id, "method": c.method, "interpolation": c.interpolation,
                "calibration": [r.to_dict() for r in c.calibration],
                "max_error_bp": max((abs(r.error_bp) for r in c.calibration if r.unit == "rate"), default=0.0),
                "nodes": c.node_table(), "meta": c.meta}

    def _build_curve(self, cid: str) -> YieldCurve:
        if cid == "RUB.OFZ" or cid == "CURVE.RUB.KBD":
            q = self._quote("CURVE.RUB.KBD")
            return kbd_curve(self.base_date, dict(q.value), [self._used(q, "КБД ОФЗ")])
        cfg = self.config["curves"].get(cid)
        if cfg is None:
            raise MissingMarketData(f"кривая {cid} не описана в конфигурации")
        ccy = cfg["currency"]
        cal = get_calendar(cfg.get("calendar", ccy))
        ref = self.base_date
        insts, used = [], []
        others: dict[str, YieldCurve] = {}
        for spec in cfg["instruments"]:
            typ = spec["type"]
            quotes = [self._quote(spec["quote"])] if "quote" in spec else self._quotes(spec["prefix"])
            for q in quotes:
                tenor = spec.get("tenor") or q.meta.get("tenor") or q.id.rsplit(".", 1)[-1]
                dc = DayCount.parse(spec.get("daycount", q.meta.get("daycount", "ACT/365F")))
                lag = int(spec.get("start_lag", 0))
                if typ == "deposit":
                    ins = deposit_from_tenor(f"{q.id}", q.id, float(q.value), ref, lag, tenor, cal, dc)
                elif typ == "swap":
                    ins = swap_from_tenor(q.id, q.id, float(q.value), ref, lag, tenor, cal,
                                          spec.get("fixed_freq", "1Y"), spec.get("float_freq", "3M"), dc, dc,
                                          compounding=spec.get("compounding", "compounded"))
                elif typ == "basis":
                    other = spec["other"]
                    if other not in others:
                        others[other] = self._cached(f"curve:{other}", lambda o=other: self._build_curve(o))
                    sw = swap_from_tenor(q.id, q.id, float(q.value), ref, lag, tenor, cal, spec.get("freq", "3M"),
                                         spec.get("freq", "3M"), dc, dc)
                    ins = BasisSwapInstrument(q.id, q.id, float(q.value), sw.maturity, sw.float_periods, SELF, other,
                                              other, spec.get("comp_a", "compounded"), spec.get("comp_b", "compounded"))
                else:
                    raise ValueError(f"неизвестный тип инструмента {typ}")
                insts.append(ins)
                used.append(self._used(q, f"калибровка кривой {cid}"))
        step_nodes = []
        if cfg.get("meeting_steps"):
            ms = self._cached("meetings", lambda: (load_meetings(self._dataset("cbr_meetings").data),
                                                    self._dataset("cbr_meetings").provenance))[0]
            horizon = add_tenor(ref, f"{int(cfg.get('step_horizon_months', 18))}M")
            step_nodes = [m.effective for m in ms if ref < m.effective <= horizon]
            ds = self.snapshot.dataset("cbr_meetings")
            used.append(UsedInput("ds:cbr_meetings", f"{len(step_nodes)} дат в горизонте", ds.provenance,
                                  "ступени короткого конца"))
        method = "бутстрэп по " + ", ".join(sorted({type(i).__name__.replace("Instrument", "") for i in insts}))
        if step_nodes:
            method += "; ступенчатый короткий конец на датах вступления в силу решений ЦБ"
        res = fit_curve(cid, ref, insts, others=others, interpolation=cfg.get("interpolation", "log_linear"),
                        step_nodes=step_nodes, currency=ccy, method=method, inputs=used, x0=self._warm.get(cid))
        self._warm.setdefault(cid, res.curve.meta["fit_params"])
        res.curve.meta["fit_max_error_bp"] = res.max_error_bp
        if res.max_error_bp > 0.5:
            self.tracker.warn(f"Кривая {cid}: репрайсинг калибровочных инструментов с ошибкой {res.max_error_bp:.2f} б.п. (> 0.5)")
        return res.curve

    def discount_curve(self, ccy: str, collateralized: bool = False, role: str = "", t_max: float = 0.0,
                       override: str | None = None) -> YieldCurve:
        """Выбор дисконтной кривой — параметр: RUSFAR под обеспечением, КС без обеспечения."""
        if override:
            cid = override
        else:
            d = self.config["discounting"].get(ccy.upper())
            if d is None:
                raise MissingMarketData(f"нет дисконтной кривой для {ccy}")
            cid = d["collateralized" if collateralized else "uncollateralized"]
        return self.curve(cid, role or f"дисконтирование {ccy} ({'под обеспечением' if collateralized else 'без обеспечения'})",
                          t_max, purpose="disc")

    def index(self, name: str) -> dict:
        idx = self.config["indices"].get(name.upper())
        if idx is None:
            raise MissingMarketData(f"индекс {name} не описан в конфигурации")
        if idx.get("legacy"):
            self.tracker.warn(f"Индекс {name}: {idx.get('fallback_note', 'унаследованный индикатор')}")
        return idx

    def forecast_curve(self, index: str, role: str = "", t_max: float = 0.0) -> YieldCurve:
        return self.curve(self.index(index)["curve"], role or f"прогноз индекса {index}", t_max, purpose="fcst")

    def meeting_path(self, cid: str = "RUB.KEYRATE", increment_bp: float = 50.0) -> list[dict]:
        c = self.curve(cid)
        spread = 0.0
        return [m.to_dict() for m in implied_meeting_path(c, self.meetings(), spread_to_key=spread, increment_bp=increment_bp)]

    # ================================================================ FX
    def fx(self, pair: str, role: str = "") -> FXForwardCurve:
        pair = pair.upper()
        base = self._cached(f"fx:{pair}", lambda: self._build_fx(pair))
        c = base
        for s in self._shocks("fx", pair):
            c = c.with_shock(1.0 + s.value if s.mode == "relative" else (c.spot_value + s.value) / c.spot_value)
        for s in self._shocks("fx_carry", pair):
            c = c.with_carry(s.value)
        if self.is_rolled:
            c = c.rolled(self.ref_date)
        c.register(self.tracker, role)
        return c

    def _build_fx(self, pair: str) -> FXForwardCurve:
        cfg = self.config["fx"].get(pair)
        if cfg is None:
            raise MissingMarketData(f"валютная пара {pair} не описана в конфигурации")
        cal = get_calendar(cfg.get("calendar", f"{pair[:3]}+{pair[3:]}"))
        ref = self.base_date
        sq = self._quote(cfg["spot"])
        spot_date = cal.advance_business_days(ref, int(cfg.get("spot_lag", 1)))
        pts = self._quotes(cfg["points_prefix"])
        rows = []
        hs = {}
        for q in pts:
            tenor = q.meta.get("tenor") or q.id.rsplit(".", 1)[-1]
            d = add_tenor(spot_date, tenor, cal)
            rows.append((d, float(sq.value) + float(q.value), q))
            if q.bid is not None and q.ask is not None:
                hs[tenor] = 0.5 * (q.ask - q.bid)
        rows.sort(key=lambda r: r[0])
        used = [self._used(sq, f"спот {pair}")] + [self._used(q, f"форвардные пункты {pair}") for _, _, q in rows]
        return FXForwardCurve(pair, ref, float(sq.value), spot_date, [r[0] for r in rows], np.array([r[1] for r in rows]),
                              cal, used, sq.bid, sq.ask, hs)

    def fx_foreign_curve(self, pair: str, domestic: YieldCurve) -> YieldCurve:
        """Иностранная кривая, согласованная с форвардами пары и рублёвой кривой дисконтирования."""
        return self.fx(pair).implied_foreign_curve(domestic)

    def cip_table(self, pair: str, onshore: str = "RUB.KEYRATE") -> list[dict]:
        cfg = self.config["fx"][pair.upper()]
        return cip_diagnostics(self.fx(pair), self.curve(cfg["foreign_curve"]), self.curve(onshore))

    # ================================================================ volatility
    def fx_vol(self, pair: str, T: float | None = None, K: float | None = None, role: str = "") -> VolSurface:
        pair = pair.upper()
        base = self._cached(f"fxvol:{pair}", lambda: self._build_fx_vol(pair))
        fxc = self.fx(pair)
        ts_off = (fxc.spot_date - fxc.ref_date).days / 365.0
        sticky = self.sticky_override or base.sticky
        s = base.with_forward(lambda T, _c=fxc, _o=ts_off: _c.forward_t(np.asarray(T, float) + _o), sticky)
        for sh in self._shocks("vol", pair):
            s = s.shifted(sh.value)
        for sh in self._shocks("vol_slice", pair):
            s = s.with_slice_shift(int(sh.mode), sh.value)
        if self.is_rolled:
            s = s.rolled(self.ref_date)
        if T is not None:
            s.register(self.tracker, T, K, role or f"волатильность {pair}")
        return s

    def _build_fx_vol(self, pair: str) -> VolSurface:
        cfg = self.config["fx_vol"].get(pair)
        fxc = self._cached(f"fx:{pair}", lambda: self._build_fx(pair))
        dom = self._cached("curve:" + self.config["discounting"]["RUB"]["uncollateralized"],
                           lambda: self._build_curve(self.config["discounting"]["RUB"]["uncollateralized"]))
        if cfg is None or not self._quotes(cfg["prefix"]):
            return self._historical_fx_vol(pair, fxc)
        pillars: dict[str, dict] = {}
        used = []
        for q in self._quotes(cfg["prefix"]):
            parts = q.id[len(cfg["prefix"]):].split(".")
            if len(parts) != 2:
                continue
            name, tenor = parts
            hs = 0.5 * (q.ask - q.bid) if (q.bid is not None and q.ask is not None) else 0.0
            pillars.setdefault(tenor, {})[name] = (float(q.value), q.provenance.kind, q.id, hs)
            used.append(self._used(q, f"столп волатильности {pair}"))
        pillars = {t: p for t, p in pillars.items() if "ATM" in p}
        return build_fx_surface(pair, self.base_date, fxc, dom, pillars, delta_type=cfg.get("delta_type", "spot"),
                                premium_adjusted=cfg.get("premium_adjusted", False), atm_type=cfg.get("atm_type", "dns"),
                                long_delta_type=cfg.get("long_delta_type", "forward"), model=cfg.get("model", "svi"),
                                sticky=cfg.get("sticky", "delta"), calendar=fxc.calendar, inputs=used)

    def _historical_fx_vol(self, pair: str, fxc: FXForwardCurve) -> VolSurface:
        name = f"hist_fx_{pair.lower()}"
        ds = self._dataset(name)
        xs = np.asarray(ds.data["spot"], float)
        r = np.diff(np.log(xs))[-250:]
        w = 0.97 ** np.arange(len(r))[::-1]
        vol = float(np.sqrt(np.sum(w * r * r) / np.sum(w) * 252))
        prov = Provenance(ds.provenance.source, ds.provenance.as_of, DataKind.HISTORICAL,
                          note="EWMA λ=0.97 по дневным доходностям — фоллбэк при отсутствии котировок опционов")
        u = UsedInput(f"hist:{pair}", round(vol, 4), prov, f"историческая волатильность {pair}")
        ts_off = (fxc.spot_date - fxc.ref_date).days / 365.0
        return flat_surface(pair, self.base_date, lambda T: fxc.forward_t(np.asarray(T) + ts_off), vol,
                            DataKind.HISTORICAL, "историческая волатильность (фоллбэк, без улыбки)", [u], sid=f"FX.{pair}")

    def local_vol(self, pair: str, t_max: float) -> LocalVolGrid:
        is_fx = pair.upper() in self.config.get("fx_vol", {}) or self.has_hist(pair)
        shocks = tuple((s.kind, s.target, s.value, s.mode) for s in self.shocks if s.matches(pair))
        key = f"lv:{pair}:{round(t_max, 3)}:{self.sticky_override}:{shocks}:{self.ref_date.isoformat()}"
        return self._cached(key, lambda: dupire_grid(self.fx_vol(pair) if is_fx else self.asset_vol(pair), t_max))

    def has_hist(self, pair: str) -> bool:
        return f"hist_fx_{pair.lower()}" in self.snapshot.datasets

    def ir_vol(self, curve_id: str = "RUB.KEYRATE", T: float | None = None, role: str = "") -> RateVol:
        base = self._cached(f"irvol:{curve_id}", lambda: self._build_ir_vol(curve_id))
        v = base
        for s in self._shocks("irvol", curve_id):
            v = v.shifted(s.value)
        for s in self._shocks("irvol_bucket", curve_id):
            i, j = (int(x) for x in s.mode.split(","))
            v = v.bucket_shifted(i, j, s.value)
        if T is not None:
            v.register(self.tracker, T, role)
        return v

    def _build_ir_vol(self, curve_id: str) -> RateVol:
        cfg = self.config["ir_vol"].get(curve_id, {})
        qs = self._quotes(cfg.get("quotes_prefix", "VOL.__none__."))
        if qs:
            rows = sorted((Tenor.parse(q.id.rsplit(".", 1)[-1]).approx_years, float(q.value), q) for q in qs)
            hs = [0.5 * (q.ask - q.bid) for *_, q in rows if q.bid is not None and q.ask is not None]
            return RateVol(f"IR.{curve_id}", self.base_date, np.array([r[0] for r in rows]), np.array([0.25]),
                           np.array([[r[1]] for r in rows]), DataKind.MARKET, "котировки нормальной волатильности",
                           inputs=[self._used(r[2], "волатильность ставки") for r in rows],
                           halfspread_bp=float(np.mean(hs)) * 1e4 if hs else 0.0)
        ds = self._dataset(cfg["historical_dataset"])
        hv = historical_normal_vol(ds.data["series"], ewma_lambda=cfg.get("ewma_lambda", 0.97))
        tenors = sorted(hv, key=lambda t: Tenor.parse(t).approx_years)
        tvals = np.array([Tenor.parse(t).approx_years for t in tenors])
        vols = np.array([hv[t] for t in tenors])
        # нормальная волатильность форвардной ставки ≈ волатильность свопа близкого срока; один ряд по сроку экспирации
        expiries = np.array([0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0])
        grid = np.array([[float(np.interp(max(e, tt), tvals, vols)) for tt in tvals] for e in expiries])
        prov = Provenance(ds.provenance.source, ds.provenance.as_of, DataKind.HISTORICAL,
                          note="EWMA по дневным изменениям ставок свопов на КС; рынка опционов на ставку нет")
        used = [UsedInput(f"hist:{curve_id}:{t}", round(hv[t] * 1e4, 1), prov, "историческая нормальная волатильность, б.п.") for t in tenors]
        return RateVol(f"IR.{curve_id}", self.base_date, expiries, tvals, grid, DataKind.HISTORICAL,
                       "историческая оценка (фоллбэк): нет публичных котировок кэпов/свопционов", inputs=used,
                       halfspread_bp=float(cfg.get("assumed_halfspread_bp", 5.0)))

    # ================================================================ credit
    def credit_curve(self, entity: str, role: str = "") -> HazardCurve:
        base = self._cached(f"credit:{entity}", lambda: self._build_credit(entity))
        c = base
        for s in self._shocks("credit", entity):
            c = c.shocked(1.0 + s.value)
        c.register(self.tracker, role or f"кредитный риск {entity}")
        return c

    def credit_entities(self) -> dict:
        return self._dataset(self.config["credit"]["entities_dataset"]).data

    def _build_credit(self, entity: str) -> HazardCurve:
        cfg = self.config["credit"]
        ents = self._dataset(cfg["entities_dataset"]).data
        if entity not in ents:
            raise MissingMarketData(f"контрагент {entity} не описан в датасете {cfg['entities_dataset']}")
        e = ents[entity]
        rec = float(e.get("recovery", cfg.get("default_recovery", 0.4)))
        ofz = self._cached("curve:RUB.OFZ", lambda: self._build_curve("RUB.OFZ"))
        all_bonds = [q for q in self._quotes("CREDIT.BOND.")]

        def obs(q: Quote) -> BondObs:
            return BondObs(q.id.split(".", 2)[2], q.meta.get("issuer", ""), float(q.value), float(q.meta["duration"]),
                           q.meta.get("sector", ""), q.meta.get("rating", ""), q.provenance)
        override = e.get("method")
        own = [obs(q) for q in all_bonds if q.meta.get("issuer") == entity]
        if own and override in (None, "bonds"):
            return from_bond_spreads(entity, self.base_date, own, ofz, rec, 1)
        peers = [obs(q) for q in all_bonds if q.meta.get("sector") == e.get("sector") and q.meta.get("rating") == e.get("rating")
                 and q.meta.get("issuer") != entity]
        if len(peers) >= 2 and override in (None, "peers"):
            c = from_bond_spreads(entity, self.base_date, peers, ofz, rec, 2)
            c.details["peer_group"] = {"sector": e.get("sector"), "rating": e.get("rating"), "n": len(peers)}
            return c
        tables = self._dataset(cfg["rating_tables_dataset"])
        agency = e.get("agency", "AKRA")
        table = tables.data[agency]
        return from_rating(entity, self.base_date, e["rating"], table, tables.provenance, rec,
                           float(e.get("risk_premium_mult", table.get("default_risk_premium_mult", 1.0))))

    # ================================================================ inflation
    def cpi(self, name: str = "RU.CPI", role: str = "") -> CPICurve:
        base = self._cached(f"cpi:{name}", lambda: self._build_cpi(name))
        c = base
        for s in self._shocks("cpi", name):
            c = c.with_shock(s.value)
        c.register(self.tracker, role or "прогноз ИПЦ")
        return c

    def _build_cpi(self, name: str) -> CPICurve:
        cfg = self.config["inflation"][name]
        ds = self._dataset(cfg["dataset"])
        d = ds.data
        qs = self._quotes(cfg["pillars_prefix"])
        rows = sorted((Tenor.parse(q.id.rsplit(".", 1)[-1]).approx_years, float(q.value), q) for q in qs)
        seas = estimate_seasonality(d["index_revised"], cfg.get("seasonality_years", 5))
        used = [UsedInput(f"ds:{cfg['dataset']}", f"{len(d['index_first'])} мес.", ds.provenance, "история ИПЦ Росстата")]
        used += [self._used(q, "инфляционные ожидания (ZCIS / ОФЗ-ИН)") for *_, q in rows]
        return CPICurve(self.base_date, d["index_first"], d["index_revised"], d["published"],
                        np.array([r[0] for r in rows]), np.array([r[1] for r in rows]), seas, used)

    # ================================================================ commodities / equities
    def commodity(self, asset: str, role: str = "") -> CommodityCurve:
        base = self._cached(f"cmdty:{asset}", lambda: self._build_commodity(asset))
        c = base
        for s in self._shocks("commodity", asset):
            c = c.with_shock(1 + s.value)
        c.register(self.tracker, role)
        return c

    def _build_commodity(self, asset: str) -> CommodityCurve:
        cfg = self.config["commodities"][asset]
        qs = self._quotes(cfg["prefix"])
        rows = sorted(((int(q.id[-7:-3]), int(q.id[-2:])), float(q.value), q) for q in qs)
        seas = np.ones(12)
        if cfg.get("seasonality_dataset") and cfg["seasonality_dataset"] in self.snapshot.datasets:
            seas = np.asarray(self._dataset(cfg["seasonality_dataset"]).data["factors"], float)
        used = [self._used(q, f"форвард {asset}") for *_, q in rows]
        note = "" if cfg.get("tradeable_hedge", True) else "нет ликвидного торгуемого хеджа"
        return CommodityCurve(asset, self.base_date, cfg["currency"], cfg["unit"], [r[0] for r in rows],
                              np.array([r[1] for r in rows]), seas, cfg.get("tradeable_hedge", True), note, used)

    def equity(self, asset: str, role: str = "") -> EquityForward:
        base = self._cached(f"eq:{asset}", lambda: self._build_equity(asset))
        c = base
        for s in self._shocks("equity", asset):
            c = c.with_shock(1 + s.value)
        c.register(self.tracker, role)
        return c

    def _build_equity(self, asset: str) -> EquityForward:
        cfg = self.config["equities"][asset]
        sq = self._quote(cfg["spot"])
        divs = sorted((date.fromisoformat(q.id[len(cfg["dividends_prefix"]):]), float(q.value), q)
                      for q in self._quotes(cfg["dividends_prefix"]))
        bq = self._quote(cfg["borrow"]) if self.has_quote(cfg["borrow"]) else None
        used = [self._used(sq, f"спот {asset}")] + [self._used(q, "дискретный дивиденд") for *_, q in divs]
        if bq:
            used.append(self._used(bq, "ставка заимствования бумаги"))
        return EquityForward(asset, self.base_date, float(sq.value), cfg["currency"], [(d, a) for d, a, _ in divs],
                             float(bq.value) if bq else 0.0, used)

    def asset_vol(self, asset: str, T: float | None = None, K: float | None = None, role: str = "") -> VolSurface:
        """Волатильность товарного или долевого базиса (срезы по страйкам)."""
        base = self._cached(f"assetvol:{asset}", lambda: self._build_asset_vol(asset))
        fwd = self.asset_forward_fn(asset)
        s = base.with_forward(fwd, self.sticky_override or base.sticky)
        for sh in self._shocks("vol", asset):
            s = s.shifted(sh.value)
        if self.is_rolled:
            s = s.rolled(self.ref_date)
        if T is not None:
            s.register(self.tracker, T, K, role or f"волатильность {asset}")
        return s

    def asset_forward_fn(self, asset: str) -> Callable:
        if asset in self.config.get("equities", {}):
            eq = self.equity(asset)
            disc = self.curve(self.config["equities"][asset]["discount"])
            return lambda T, _e=eq, _d=disc: _e.forward_t(T, _d)
        if asset in self.config.get("commodities", {}):
            c = self.commodity(asset)
            return lambda T, _c=c: _c.forward_t(np.asarray(T, float))
        fxc = self.fx(asset)
        off = (fxc.spot_date - fxc.ref_date).days / 365.0
        return lambda T, _c=fxc, _o=off: _c.forward_t(np.asarray(T, float) + _o)

    def _build_asset_vol(self, asset: str) -> VolSurface:
        if asset in self.config.get("equities", {}):
            prefix = self.config["equities"][asset]["vol_prefix"]
        else:
            prefix = self.config["commodities"][asset]["vol_prefix"]
        fwd = self._asset_forward_base(asset)
        qs = self._quotes(prefix)
        if not qs:
            ds_name = f"hist_{asset.lower()}"
            ds = self._dataset(ds_name)
            xs = np.asarray(ds.data["spot"], float)
            r = np.diff(np.log(xs))[-250:]
            vol = float(np.std(r, ddof=1) * np.sqrt(252))
            prov = Provenance(ds.provenance.source, ds.provenance.as_of, DataKind.HISTORICAL, note="фоллбэк: историческая волатильность")
            return flat_surface(asset, self.base_date, fwd, vol, DataKind.HISTORICAL,
                                "историческая волатильность (фоллбэк)", [UsedInput(f"hist:{asset}", vol, prov)])
        data = []
        used = []
        for q in qs:
            exp = date.fromisoformat(q.id[len(prefix):])
            if exp <= self.base_date:
                continue
            data.append((exp, q.value["strikes"], q.value["vols"], q.provenance.kind, q.id))
            used.append(self._used(q, f"срез волатильности {asset}"))
        data.sort(key=lambda x: x[0])
        return build_strike_surface(asset, self.base_date, fwd, data, inputs=used, sticky="strike")

    def _asset_forward_base(self, asset: str) -> Callable:
        if asset in self.config.get("equities", {}):
            eq = self._cached(f"eq:{asset}", lambda: self._build_equity(asset))
            cid = self.config["equities"][asset]["discount"]
            disc = self._cached(f"curve:{cid}", lambda: self._build_curve(cid))
            return lambda T, _e=eq, _d=disc: _e.forward_t(T, _d)
        c = self._cached(f"cmdty:{asset}", lambda: self._build_commodity(asset))
        return lambda T, _c=c: _c.forward_t(np.asarray(T, float))

    # ================================================================ correlations & fixings
    def correlation(self, a: str, b: str, role: str = "") -> float:
        if a == b:
            return 1.0
        ds = self._dataset("correlations")
        key1, key2 = f"{a}|{b}", f"{b}|{a}"
        val = ds.data.get(key1, ds.data.get(key2))
        if val is None:
            raise MissingMarketData(f"нет корреляции {a}/{b} в датасете correlations")
        v = float(val)
        for s in self._shocks("corr", f"{a}|{b}") + self._shocks("corr", f"{b}|{a}"):
            v = float(np.clip(v + s.value, -0.999, 0.999))
        self.tracker.record(UsedInput(f"corr:{a}|{b}", v, ds.provenance, role or "корреляция"))
        return v

    def fixing(self, asset: str, source: str, d: date, role: str = "") -> float:
        """Исторический фиксинг строго из указанного в контракте источника — без подстановок.

        В производном контексте со сдвигом даты (тета, профиль «через N дней») фиксинги
        между исходной и новой датой ещё не наблюдались: они проецируются форвардом
        исходной даты и помечаются как модельные."""
        ds = self._dataset("fixings")
        try:
            v = ds.data[source][asset][d.isoformat()]
        except KeyError:
            if self.allow_projected_fixings and d >= self.base_date and asset.upper() in self.config.get("fx", {}):
                fx = self._cached(f"fx:{asset.upper()}", lambda: self._build_fx(asset.upper()))
                v = fx.forward(d)
                self.tracker.record(UsedInput(f"PROJ.{source}.{asset}.{d.isoformat()}", v,
                                              Provenance("проекция фиксинга форвардом на исходную дату", None, DataKind.MODEL),
                                              role or "фиксинг в сдвинутом контексте"))
                return float(v)
            raise MissingFixing(f"нет фиксинга {asset} по источнику {source} на {d.isoformat()} "
                                f"(подстановка другого источника запрещена)") from None
        self.tracker.record(UsedInput(f"FIX.{source}.{asset}.{d.isoformat()}", v, ds.provenance, role or "исторический фиксинг"))
        return float(v)

    def has_fixing(self, asset: str, source: str, d: date) -> bool:
        if "fixings" not in self.snapshot.datasets:
            return False
        if d.isoformat() in self.snapshot.dataset("fixings").data.get(source, {}).get(asset, {}):
            return True
        return bool(self.allow_projected_fixings and self.base_date <= d < self.ref_date
                    and asset.upper() in self.config.get("fx", {}))
