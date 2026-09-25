"""Метрики качества маркет-мейкинга.

Разложение P&L (руб.):
    spread   = Σ side·(mid − price)·lots·mult по пассивным сделкам — заработок на
               спреде относительно mid в момент котирования;
    inventory = изменение стоимости позиции при движении цены (всё остальное);
    fees     — комиссии (пассивные и агрессивные);
    liquidation — издержки закрытия позиции по рынку относительно mid.
    total = spread + inventory + liquidation − fees.

Markout (adverse selection) на горизонте h шагов: side·(mark_{i+h} − price) в
тиках — насколько цена ушла «против» нас после исполнения (отрицательный — плохо).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def _equity(res) -> pd.Series:
    return res.steps["equity"].ffill().fillna(0.0)


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    return float((equity.cummax() - equity).max())


def markouts(res, horizons=(1, 5, 15)) -> dict[int, float]:
    f = res.fills[res.fills["liquidity"] == "maker"]
    if f.empty:
        return {h: float("nan") for h in horizons}
    marks = res.steps["mark"].to_numpy()
    sid = res.steps["session_id"].to_numpy()
    n = len(marks)
    tick = res.instrument.tick_size
    out = {}
    step = f["step"].to_numpy()
    for h in horizons:
        j = np.minimum(step + h, n - 1)
        # не переходим через границу сессии: берём последний бар своей сессии
        cross = sid[j] != sid[step]
        while cross.any():
            j[cross] -= 1
            cross = sid[j] != sid[step]
        mo = f["side"].to_numpy() * (marks[j] - f["price"].to_numpy()) / tick
        out[h] = float(np.average(mo, weights=f["lots"].to_numpy()))
    return out


def pnl_decomposition(res) -> dict[str, float]:
    f = res.fills
    mult = res.instrument.multiplier
    maker = f[f["liquidity"] == "maker"]
    taker = f[f["liquidity"] == "taker"]
    spread = float((maker["side"] * (maker["mid"] - maker["price"]) * maker["lots"]).sum() * mult)
    liquidation = float((taker["side"] * (taker["mid"] - taker["price"]) * taker["lots"]).sum() * mult)
    fees = float(f["fee"].sum())
    total = float(_equity(res).iloc[-1]) if len(res.steps) else 0.0
    return {
        "total": total,
        "spread": spread,
        "inventory": total - spread - liquidation + fees,
        "liquidation": liquidation,
        "fees": fees,
    }


def daily_table(res) -> pd.DataFrame:
    st = res.steps[res.steps["active"]]
    if st.empty:
        return pd.DataFrame(columns=["pnl", "fills", "volume_rub", "max_abs_inventory", "fees"])
    eq = _equity(res)
    day = pd.DatetimeIndex(res.steps.index).normalize()
    end_eq = eq.groupby(day).last()
    start_eq = end_eq.shift(1).fillna(0.0)
    pnl = (end_eq - start_eq).rename("pnl")
    f = res.fills.copy()
    f["day"] = pd.DatetimeIndex(f["time"]).normalize() if len(f) else pd.DatetimeIndex([])
    maker = f[f["liquidity"] == "maker"]
    out = pd.DataFrame({"pnl": pnl})
    out["fills"] = maker.groupby("day")["lots"].count().reindex(out.index).fillna(0).astype(int)
    out["volume_rub"] = f.groupby("day")["notional"].sum().reindex(out.index).fillna(0.0)
    out["fees"] = f.groupby("day")["fee"].sum().reindex(out.index).fillna(0.0)
    inv_abs = res.steps["inventory"].abs()
    out["max_abs_inventory"] = inv_abs.groupby(day).max().reindex(out.index).fillna(0.0)
    active_days = pd.DatetimeIndex(st.index).normalize().unique()
    out = out.loc[out.index.isin(active_days)]
    out.index.name = "date"
    return out


def compute_metrics(res) -> dict:
    st = res.steps
    active = st[st["active"]]
    f = res.fills
    maker = f[f["liquidity"] == "maker"]
    taker = f[f["liquidity"] == "taker"]
    daily = daily_table(res)
    dec = pnl_decomposition(res)
    tick = res.instrument.tick_size
    eq = _equity(res)
    d = daily["pnl"] if len(daily) else pd.Series(dtype=float)
    sharpe = float(d.mean() / d.std(ddof=1) * np.sqrt(TRADING_DAYS)) if len(d) > 1 and d.std(ddof=1) > 0 else float("nan")
    quoted = active[active["quoting"]]
    width = (quoted["ask"] - quoted["bid"]) / tick
    mo = markouts(res)
    volume = float(f["notional"].sum())
    inv = active["inventory"]
    m = {
        "strategy": res.strategy,
        "days": int(len(daily)),
        "pnl_total": dec["total"],
        "pnl_spread": dec["spread"],
        "pnl_inventory": dec["inventory"],
        "pnl_liquidation": dec["liquidation"],
        "fees": dec["fees"],
        "pnl_per_day_mean": float(d.mean()) if len(d) else float("nan"),
        "pnl_per_day_std": float(d.std(ddof=1)) if len(d) > 1 else float("nan"),
        "sharpe_annual": sharpe,
        "win_days_pct": float((d > 0).mean() * 100) if len(d) else float("nan"),
        "max_drawdown": max_drawdown(eq),
        "maker_fills": int(len(maker)),
        "maker_lots": int(maker["lots"].sum()) if len(maker) else 0,
        "taker_lots": int(taker["lots"].sum()) if len(taker) else 0,
        "volume_rub": volume,
        "pnl_bps_of_volume": float(dec["total"] / volume * 1e4) if volume > 0 else float("nan"),
        "spread_capture_ticks": float(
            np.average(maker["side"] * (maker["mid"] - maker["price"]), weights=maker["lots"]) / tick
        ) if len(maker) else float("nan"),
        "quoted_width_ticks_mean": float(width.mean()) if len(width) else float("nan"),
        "quoting_time_pct": float(active["quoting"].mean() * 100) if len(active) else float("nan"),
        "inventory_mean_abs": float(inv.abs().mean()) if len(inv) else float("nan"),
        "inventory_std": float(inv.std()) if len(inv) > 1 else float("nan"),
        "inventory_max_abs": float(inv.abs().max()) if len(inv) else float("nan"),
        "at_limit_pct": float((inv.abs() >= res.execution.max_inventory).mean() * 100) if len(inv) else float("nan"),
    }
    for h, v in mo.items():
        m[f"markout_{h}_ticks"] = v
    return m


METRIC_LABELS = {
    "strategy": "Стратегия",
    "days": "Торговых дней",
    "pnl_total": "P&L итого, руб.",
    "pnl_spread": "  спред, руб.",
    "pnl_inventory": "  позиция (переоценка), руб.",
    "pnl_liquidation": "  закрытие позиции, руб.",
    "fees": "  комиссии, руб.",
    "pnl_per_day_mean": "P&L в день, среднее",
    "pnl_per_day_std": "P&L в день, ст. откл.",
    "sharpe_annual": "Шарп (годовой)",
    "win_days_pct": "Прибыльных дней, %",
    "max_drawdown": "Макс. просадка, руб.",
    "maker_fills": "Пассивных исполнений",
    "maker_lots": "  лотов",
    "taker_lots": "Лотов закрыто по рынку",
    "volume_rub": "Оборот, руб.",
    "pnl_bps_of_volume": "P&L / оборот, б.п.",
    "spread_capture_ticks": "Захват спреда, тиков на лот",
    "quoted_width_ticks_mean": "Средняя ширина котировки, тиков",
    "quoting_time_pct": "Время в котировании, %",
    "inventory_mean_abs": "Средняя |позиция|, лотов",
    "inventory_std": "Ст. откл. позиции, лотов",
    "inventory_max_abs": "Макс. |позиция|, лотов",
    "at_limit_pct": "Время на лимите позиции, %",
    "markout_1_ticks": "Markout 1 шаг, тиков",
    "markout_5_ticks": "Markout 5 шагов, тиков",
    "markout_15_ticks": "Markout 15 шагов, тиков",
}


def metrics_frame(results) -> pd.DataFrame:
    """Таблица метрик: строки — метрики, столбцы — стратегии."""
    cols = {}
    for r in results:
        m = r.metrics
        cols[m["strategy"]] = {k: v for k, v in m.items() if k != "strategy"}
    df = pd.DataFrame(cols)
    df.index = [METRIC_LABELS.get(i, i) for i in df.index]
    return df


def format_metrics(m: dict) -> str:
    lines = []
    for k, label in METRIC_LABELS.items():
        if k not in m:
            continue
        v = m[k]
        if isinstance(v, float):
            v = f"{v:,.2f}".replace(",", " ")
        lines.append(f"{label:<36} {v}")
    return "\n".join(lines)
