"""Графики (matplotlib) и HTML-отчёт."""

from __future__ import annotations

import base64
import html
import io
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from mmsim.metrics import METRIC_LABELS, metrics_frame  # noqa: E402

# Палитра: категориальные цвета в фиксированном порядке, спокойные оси и сетка.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
POS, NEG = "#2a78d6", "#e34948"
SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"

plt.rcParams.update({
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "axes.edgecolor": AXIS,
    "axes.labelcolor": INK2,
    "axes.titlecolor": INK,
    "axes.titlesize": 12,
    "axes.titleweight": "bold",
    "axes.titlelocation": "left",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "axes.axisbelow": True,
    "grid.color": GRID,
    "grid.linewidth": 0.8,
    "grid.linestyle": "-",
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "xtick.labelcolor": INK2,
    "ytick.labelcolor": INK2,
    "legend.frameon": False,
    "legend.labelcolor": INK2,
    "font.size": 10,
    "lines.linewidth": 2.0,
    "lines.solid_capstyle": "round",
    "lines.solid_joinstyle": "round",
    "savefig.facecolor": SURFACE,
    "figure.dpi": 110,
})


def _fmt_rub(x, _pos=None):
    return f"{x:,.0f}".replace(",", " ")


def _png(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def _save(fig, out_dir: Path | None, name: str) -> str:
    data = _png(fig)
    if out_dir is not None:
        (out_dir / f"{name}.png").write_bytes(base64.b64decode(data))
    return data


def _end_label(ax, x, y, text):
    ax.annotate(text, (x, y), xytext=(6, 0), textcoords="offset points", va="center", color=INK2, fontsize=9)


# ------------------------------------------------------------------ графики
def plot_pnl(res):
    st = res.steps
    f = res.fills
    mult = res.instrument.multiplier
    idx = np.arange(len(st))
    total = st["equity"].ffill().fillna(0.0).to_numpy()
    spread = np.zeros(len(st))
    fees = np.zeros(len(st))
    if len(f):
        maker = f[f["liquidity"] == "maker"]
        np.add.at(spread, maker["step"].to_numpy(), (maker["side"] * (maker["mid"] - maker["price"]) * maker["lots"]).to_numpy() * mult)
        np.add.at(fees, f["step"].to_numpy(), f["fee"].to_numpy())
    spread, fees = np.cumsum(spread), np.cumsum(fees)
    inventory = total - spread + fees
    fig, ax = plt.subplots(figsize=(11, 4.2))
    series = [("Итого", total), ("Спред", spread), ("Позиция и закрытие", inventory), ("Комиссии", -fees)]
    for (name, y), color in zip(series, SERIES):
        ax.plot(idx, y, color=color, label=name, lw=2 if name == "Итого" else 1.6)
        _end_label(ax, idx[-1], y[-1], f"{name}: {_fmt_rub(y[-1])}")
    ax.axhline(0, color=AXIS, lw=1)
    _day_ticks(ax, st.index)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(_fmt_rub))
    ax.set_ylabel("руб.")
    ax.set_title(f"Накопленный P&L и его составляющие — {res.strategy}")
    ax.legend(loc="upper left", ncols=4)
    ax.margins(x=0.01)
    fig.subplots_adjust(right=0.8)
    return fig


def _day_ticks(ax, index):
    days = pd.DatetimeIndex(index).normalize()
    starts = np.flatnonzero(np.r_[True, days[1:] != days[:-1]])
    step = max(1, len(starts) // 12)
    ax.set_xticks(starts[::step])
    ax.set_xticklabels([f"{index[i]:%d.%m}" for i in starts[::step]])
    ax.grid(axis="x", visible=False)


def plot_inventory(res):
    st = res.steps
    idx = np.arange(len(st))
    fig, ax = plt.subplots(figsize=(11, 2.8))
    ax.step(idx, st["inventory"].fillna(0).to_numpy(), where="post", color=SERIES[0], lw=1.4)
    lim = res.execution.max_inventory
    for y in (lim, -lim):
        ax.axhline(y, color=MUTED, lw=1)
    _end_label(ax, idx[-1], lim, f"лимит ±{lim}")
    ax.axhline(0, color=AXIS, lw=1)
    _day_ticks(ax, st.index)
    ax.set_ylabel("лотов")
    ax.set_title("Позиция маркет-мейкера")
    ax.margins(x=0.01)
    return fig


def plot_daily(res):
    d = res.daily
    fig, ax = plt.subplots(figsize=(11, 3.2))
    if d.empty:
        ax.text(0.5, 0.5, "нет торговых дней", ha="center", transform=ax.transAxes, color=INK2)
        return fig
    x = np.arange(len(d))
    colors = [POS if v >= 0 else NEG for v in d["pnl"]]
    width = min(0.8, 24 / max(1, len(d)) * 0.8)
    ax.bar(x, d["pnl"], color=colors, width=width)
    ax.axhline(0, color=AXIS, lw=1)
    step = max(1, len(d) // 15)
    ax.set_xticks(x[::step])
    ax.set_xticklabels([f"{t:%d.%m}" for t in d.index[::step]])
    ax.grid(axis="x", visible=False)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(_fmt_rub))
    ax.set_ylabel("руб.")
    ax.set_title("P&L по дням (синий — прибыль, красный — убыток)")
    return fig


def plot_day_detail(res, day: str | None = None, window_seconds: float = 7200):
    st = res.steps[res.steps["quoting"]]
    if st.empty:
        fig, ax = plt.subplots(figsize=(11, 4))
        ax.text(0.5, 0.5, "нет котировок", ha="center", transform=ax.transAxes)
        return fig
    days = pd.DatetimeIndex(st.index).normalize()
    target = pd.Timestamp(day) if day else days[len(days) // 2]
    one = res.steps[pd.DatetimeIndex(res.steps.index).normalize() == target]
    if one.empty:
        one = res.steps[pd.DatetimeIndex(res.steps.index).normalize() == days[0]]
        target = days[0]
    max_steps = max(20, int(window_seconds / res.meta["step_seconds"]))
    if len(one) > max_steps:  # окно вокруг середины дня, иначе котировки сливаются
        mid_i = len(one) // 2
        one = one.iloc[mid_i - max_steps // 2: mid_i + max_steps // 2]
    fig, ax = plt.subplots(figsize=(11, 4.6))
    t = one.index
    ax.plot(t, one["mark"], color=INK2, lw=1.2, label="Цена (close бара)")
    ax.step(t, one["bid"], where="post", color=SERIES[0], lw=1.4, label="Наш bid")
    ax.step(t, one["ask"], where="post", color=SERIES[1], lw=1.4, label="Наш ask")
    if one["reservation"].notna().any():
        ax.plot(t, one["reservation"], color=SERIES[2], lw=1.2, label="Резервационная цена")
    f = res.fills
    f = f[(f["liquidity"] == "maker") & f["time"].between(t[0], t[-1] + pd.Timedelta(seconds=res.meta["step_seconds"]))]
    buys, sells = f[f["side"] > 0], f[f["side"] < 0]
    ax.scatter(buys["time"], buys["price"], s=42, marker="^", color=SERIES[0], edgecolors=SURFACE, linewidths=1.5, zorder=5, label="Покупка")
    ax.scatter(sells["time"], sells["price"], s=42, marker="v", color=SERIES[1], edgecolors=SURFACE, linewidths=1.5, zorder=5, label="Продажа")
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%H:%M"))
    ax.set_ylabel("руб.")
    ax.set_title(f"Котировки и исполнения, {target:%d.%m.%Y} {t[0]:%H:%M}–{t[-1]:%H:%M}")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.1), ncols=6)
    return fig


def plot_equity_compare(results):
    fig, ax = plt.subplots(figsize=(11, 4.4))
    for r, color in zip(results, SERIES):
        eq = r.steps["equity"].ffill().fillna(0.0).to_numpy()
        x = np.arange(len(eq))
        ax.plot(x, eq, color=color, label=r.strategy)
        if len(results) <= 4:
            _end_label(ax, x[-1], eq[-1], _fmt_rub(eq[-1]))
    ax.axhline(0, color=AXIS, lw=1)
    _day_ticks(ax, results[0].steps.index)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(_fmt_rub))
    ax.set_ylabel("руб.")
    ax.set_title("Накопленный P&L стратегий")
    ax.legend(loc="upper left")
    ax.margins(x=0.01)
    fig.subplots_adjust(right=0.88)
    return fig


def plot_sweep(table: pd.DataFrame, param: str):
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.4))
    specs = [
        ("pnl_total", "P&L итого, руб."),
        ("sharpe_annual", "Шарп (годовой)"),
        ("inventory_std", "Ст. откл. позиции, лотов"),
    ]
    x = table[param].to_numpy(float)
    for ax, (col, title) in zip(axes, specs):
        ax.plot(x, table[col], color=SERIES[0], marker="o", ms=5, mec=SURFACE, mew=1.5)
        ax.set_title(title, fontsize=11)
        ax.set_xlabel(param)
        if np.all(x > 0) and x.max() / x.min() > 20:
            ax.set_xscale("log")
    axes[0].yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(_fmt_rub))
    fig.tight_layout()
    return fig


def plot_intensity(table: pd.DataFrame, A: float, k: float, tick: float):
    fig, ax = plt.subplots(figsize=(7, 3.6))
    ok = (table["p_hit"] > 0) & (table["p_hit"] < 1)
    t = table[ok]
    ax.scatter(t["delta"] / tick, t["lambda"], s=30, color=SERIES[0], edgecolors=SURFACE, linewidths=1.5, label="Эмпирическая λ(δ)", zorder=3)
    d = np.linspace(0, t["delta"].max(), 100)
    ax.plot(d / tick, A * np.exp(-k * d), color=SERIES[1], label=f"A·exp(−kδ): A={A:.3g}, k={k:.3g}")
    ax.set_yscale("log")
    ax.set_xlabel("δ, тиков от цены")
    ax.set_ylabel("λ, 1/с")
    ax.set_title("Интенсивность исполнения в зависимости от глубины")
    ax.legend()
    return fig


def plot_paper(tbl: pd.DataFrame, profits: dict, path: pd.DataFrame | None):
    fig, axes = plt.subplots(1, 2, figsize=(12, 3.8))
    ax = axes[0]
    for (name, p), color in zip(profits.items(), SERIES):
        ax.hist(p, bins=50, histtype="step", lw=2, color=color, label=name)
    ax.set_title("Распределение прибыли (γ = 0.1)")
    ax.set_xlabel("прибыль")
    ax.legend()
    ax = axes[1]
    if path is not None:
        ax.plot(path["t"], path["mid"], color=INK2, lw=1.2, label="mid")
        ax.plot(path["t"], path["reservation"], color=SERIES[2], lw=1.4, label="резервационная")
        ax.plot(path["t"], path["bid"], color=SERIES[0], lw=1.2, label="bid")
        ax.plot(path["t"], path["ask"], color=SERIES[1], lw=1.2, label="ask")
        ax.set_title("Пример траектории (inventory-стратегия)")
        ax.set_xlabel("t")
        ax.legend(ncols=2)
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------- HTML
CSS = """
:root{color-scheme:light;--surface:#fcfcfb;--page:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--grid:#e1e0d9;--border:rgba(11,11,11,.10);--good:#006300;--bad:#d03b3b}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:32px 0 12px}
.sub{color:var(--ink2);margin:0 0 20px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 14px}
.tile .l{color:var(--ink2);font-size:13px}.tile .v{font-size:22px;font-weight:600}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px;margin:12px 0;overflow-x:auto}
img{max-width:100%;height:auto;display:block}
table{border-collapse:collapse;font-size:13px;width:100%}
th,td{padding:5px 10px;border-bottom:1px solid var(--grid);text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th{color:var(--ink2);font-weight:600}
.pos{color:var(--good)}.neg{color:var(--bad)}
.note{color:var(--ink2);font-size:13px}
code{background:#f0efec;padding:1px 4px;border-radius:4px}
"""


def _num(v, digits=2):
    if isinstance(v, (int, np.integer)) and not isinstance(v, bool):
        return f"{v:,}".replace(",", " ")
    if isinstance(v, (float, np.floating)):
        if not np.isfinite(v):
            return "—"
        return f"{v:,.{digits}f}".replace(",", " ")
    return html.escape(str(v))


def _table(df: pd.DataFrame, index_label: str = "", digits=2) -> str:
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in [index_label, *df.columns])
    rows = []
    for idx, row in df.iterrows():
        label = f"{idx:%d.%m.%Y}" if isinstance(idx, pd.Timestamp) else html.escape(str(idx))
        cells = "".join(f"<td>{_num(v, digits)}</td>" for v in row)
        rows.append(f"<tr><td>{label}</td>{cells}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _tile(label, value, cls=""):
    return f'<div class="tile"><div class="l">{html.escape(label)}</div><div class="v {cls}">{value}</div></div>'


def _img(b64: str, alt: str) -> str:
    return f'<div class="card"><img alt="{html.escape(alt)}" src="data:image/png;base64,{b64}"></div>'


def _page(title: str, subtitle: str, body: str) -> str:
    return (
        f'<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body><main>"
        f"<h1>{html.escape(title)}</h1><p class=\"sub\">{subtitle}</p>{body}</main></body></html>"
    )


def _config_note(res) -> str:
    ex = res.execution
    cal = res.calibration
    inst = res.instrument
    parts = [
        f"Инструмент <b>{html.escape(inst.secid)}</b> ({html.escape(inst.board)}), лот {inst.lot_size}, шаг цены {inst.tick_size}",
        f"данные: {html.escape(res.meta.get('source', ''))}",
        f"исполнение: <code>{ex.fill_model}</code>, шаг {res.meta.get('step_seconds', 0):g} с",
        f"комиссии maker/taker {ex.maker_fee_bps:g}/{ex.taker_fee_bps:g} б.п.",
        f"лимит позиции ±{ex.max_inventory} лотов",
        f"калибровка <code>{cal.mode}</code>" + (f" ({cal.window_days} дн.)" if cal.mode == "walk_forward" else ""),
    ]
    return " · ".join(parts)


def write_report(res, out_dir: str | Path, plot_day: str | None = None) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    m = res.metrics
    imgs = {
        "pnl": _save(plot_pnl(res), out, "pnl"),
        "inventory": _save(plot_inventory(res), out, "inventory"),
        "daily": _save(plot_daily(res), out, "daily"),
        "detail": _save(plot_day_detail(res, plot_day), out, "day_detail"),
    }
    res.steps.to_csv(out / "steps.csv")
    res.fills.to_csv(out / "fills.csv", index=False)
    res.daily.to_csv(out / "daily.csv")
    res.params.to_csv(out / "params.csv", index=False)
    (out / "metrics.json").write_text(json.dumps(m, ensure_ascii=False, indent=2, default=float), encoding="utf-8")

    pnl_cls = "pos" if m["pnl_total"] >= 0 else "neg"
    tiles = "".join([
        _tile("P&L итого, руб.", _num(m["pnl_total"], 0), pnl_cls),
        _tile("Шарп (годовой)", _num(m["sharpe_annual"])),
        _tile("Макс. просадка, руб.", _num(m["max_drawdown"], 0)),
        _tile("Пассивных исполнений", _num(m["maker_fills"])),
        _tile("Захват спреда, тиков", _num(m["spread_capture_ticks"])),
        _tile("Средняя |позиция|, лотов", _num(m["inventory_mean_abs"])),
    ])
    metrics_tbl = pd.DataFrame({"значение": pd.Series(
        {METRIC_LABELS.get(k, k): v for k, v in m.items() if k != "strategy"}, dtype=object)})
    params = res.params.copy()
    if not params.empty:
        params = params.set_index("start")[["sigma", "A", "k", "r2"]]
        params.index = [f"{t:%d.%m.%Y %H:%M}" for t in params.index]
        params.columns = ["σ, руб./√с", "A, 1/с", "k, 1/руб.", "R²"]
    daily = res.daily.rename(columns={
        "pnl": "P&L, руб.", "fills": "исполнений", "volume_rub": "оборот, руб.",
        "fees": "комиссии, руб.", "max_abs_inventory": "макс. |позиция|",
    })
    body = (
        f'<div class="tiles">{tiles}</div>'
        f"<h2>P&L</h2>{_img(imgs['pnl'], 'Накопленный P&L')}{_img(imgs['daily'], 'P&L по дням')}"
        f"<h2>Позиция</h2>{_img(imgs['inventory'], 'Позиция')}"
        f"<h2>Котировки внутри дня</h2>{_img(imgs['detail'], 'Котировки')}"
        f'<h2>Метрики</h2><div class="card">{_table(metrics_tbl)}</div>'
        f'<h2>По дням</h2><div class="card">{_table(daily, "дата", 0)}</div>'
        + (f'<h2>Калибровка по сессиям</h2><div class="card">{_table(params, "начало сессии", 5)}</div>' if not params.empty else "")
        + '<p class="note">Разложение P&amp;L: «спред» — выигрыш относительно mid в момент котирования; '
        "«позиция» — переоценка удерживаемой позиции (включает adverse selection); комиссии вычтены. "
        "Markout — движение цены после исполнения в нашу пользу (в тиках), отрицательный означает, что нас «переехали».</p>"
    )
    page = _page(f"Бэктест: {res.strategy}", _config_note(res), body)
    path = out / "report.html"
    path.write_text(page, encoding="utf-8")
    return path


def write_compare_report(results, out_dir: str | Path, title: str = "Сравнение стратегий") -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    eq = _save(plot_equity_compare(results), out, "equity_compare")
    mf = metrics_frame(results)
    mf.to_csv(out / "metrics_compare.csv")
    details = "".join(
        f"<h2>{html.escape(r.strategy)}</h2>{_img(_save(plot_inventory(r), None, ''), 'Позиция')}" for r in results
    )
    body = f"{_img(eq, 'Накопленный P&L')}<h2>Метрики</h2><div class=\"card\">{_table(mf)}</div>{details}"
    path = out / "compare.html"
    path.write_text(_page(title, _config_note(results[0]), body), encoding="utf-8")
    return path


def write_sweep_report(table: pd.DataFrame, param: str, base_res, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    img = _save(plot_sweep(table, param), out, "sweep")
    table.to_csv(out / "sweep.csv", index=False)
    cols = [param, "pnl_total", "pnl_spread", "pnl_inventory", "fees", "sharpe_annual", "maker_fills",
            "quoted_width_ticks_mean", "inventory_std", "max_drawdown"]
    show = table[cols].set_index(param)
    show.columns = [METRIC_LABELS.get(c, c).strip() for c in show.columns]
    body = f"{_img(img, 'Перебор параметра')}<div class=\"card\">{_table(show, param)}</div>"
    path = out / "sweep.html"
    path.write_text(_page(f"Перебор параметра {param}", _config_note(base_res), body), encoding="utf-8")
    return path
