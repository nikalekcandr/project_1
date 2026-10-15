"""Самодостаточные SVG-графики для отчёта (без внешних библиотек).

Правила оформления: тонкие марки (линии 2px, маркеры ≥ 8px), волосяная
сетка, одна ось Y, категориальные цвета в фиксированном порядке, легенда при
двух и более сериях, текст — цветами текста, а не серий. Цвета — через
CSS-переменные (светлая и тёмная темы). Данные графика вложены в разметку
для всплывающих подсказок.
"""
from __future__ import annotations

import html
import json
import math
from typing import Any, Callable, Sequence

SERIES = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)", "var(--s6)"]


def esc(s: Any) -> str:
    return html.escape(str(s), quote=True)


def nice_ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    if not math.isfinite(lo) or not math.isfinite(hi):
        return [0.0]
    if hi - lo < 1e-12:
        d = abs(hi) * 0.1 or 1.0
        lo, hi = lo - d, hi + d
    raw = (hi - lo) / max(n, 1)
    mag = 10 ** math.floor(math.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=raw)
    start = math.floor(lo / step) * step
    out = []
    v = start
    while v <= hi + step * 0.5 and len(out) < 50:
        out.append(round(v, 12))
        v += step
    return out


def fmt_num(v: float, digits: int | None = None) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    a = abs(v)
    if digits is not None:
        s = f"{v:,.{digits}f}"
    elif a >= 1e9:
        s = f"{v / 1e9:,.2f} млрд"
    elif a >= 1e6:
        s = f"{v / 1e6:,.2f} млн"
    elif a >= 1e4:
        s = f"{v / 1e3:,.0f} тыс."
    elif a >= 100:
        s = f"{v:,.0f}"
    elif a >= 1:
        s = f"{v:,.2f}"
    elif a == 0:
        s = "0"
    else:
        s = f"{v:.4f}"
    return s.replace(",", " ")


def _axis_fmt(ticks: Sequence[float], pct: bool = False) -> Callable[[float], str]:
    if pct:
        span = max(ticks) - min(ticks) if ticks else 1
        d = 1 if span < 0.05 else 0
        return lambda v: f"{v * 100:.{d}f}%"
    m = max((abs(t) for t in ticks), default=1)
    if m >= 1e9:
        return lambda v: f"{v / 1e9:g}".replace(".", ",") + " млрд"
    if m >= 1e6:
        return lambda v: f"{v / 1e6:g}".replace(".", ",") + " млн"
    if m >= 1e4:
        return lambda v: f"{v / 1e3:g}".replace(".", ",") + " тыс."
    step = (ticks[1] - ticks[0]) if len(ticks) > 1 else 1
    dec = max(0, -int(math.floor(math.log10(step)))) if step < 1 else 0
    return lambda v: f"{v:,.{dec}f}".replace(",", " ")


def legend(items: Sequence[tuple[str, str]], dashed: Sequence[bool] | None = None) -> str:
    parts = []
    for i, (label, color) in enumerate(items):
        d = dashed[i] if dashed else False
        key = (f'<svg width="18" height="10" aria-hidden="true"><line x1="1" y1="5" x2="17" y2="5" stroke="{color}" '
               f'stroke-width="2" stroke-linecap="round"{" stroke-dasharray=\"3 3\"" if d else ""}/></svg>')
        parts.append(f'<span class="lg-item">{key}<span>{esc(label)}</span></span>')
    return f'<div class="legend">{"".join(parts)}</div>'


def line_chart(x: Sequence[float], series: Sequence[dict[str, Any]], *, cid: str, x_label: str = "", y_label: str = "",
               zones: Sequence[dict[str, Any]] = (), vlines: Sequence[tuple[float, str]] = (), pct_y: bool = False,
               pct_x: bool = False, width: int = 860, height: int = 320, step: bool = False, x_fmt: Callable | None = None) -> str:
    """Линейный график: series = [{label, y, color?, dashed?, muted?}]."""
    ml, mr, mt, mb = 70, 24, 14, 46
    w, h = width - ml - mr, height - mt - mb
    xs = [float(v) for v in x]
    allys = [float(v) for s in series for v in s["y"] if v is not None and math.isfinite(float(v))]
    if not xs or not allys:
        return '<p class="muted">нет данных для графика</p>'
    x0, x1 = min(xs), max(xs)
    yt = nice_ticks(min(allys), max(allys), 5)
    y0, y1 = min(yt), max(yt)
    xt = nice_ticks(x0, x1, 6)
    xt = [v for v in xt if x0 - 1e-12 <= v <= x1 + 1e-12]
    sx = lambda v: ml + (v - x0) / ((x1 - x0) or 1) * w
    sy = lambda v: mt + h - (v - y0) / ((y1 - y0) or 1) * h
    fy = _axis_fmt(yt, pct_y)
    fx = x_fmt or _axis_fmt(xt or [x0, x1], pct_x)
    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(y_label)}" data-chart="{cid}">']
    for z in zones:
        a, b = max(z["from"], x0), min(z["to"], x1)
        if b <= a:
            continue
        cls = "zone-crit" if z.get("type") == "worse_than_unhedged" else "zone-warn"
        out.append(f'<rect class="{cls}" x="{sx(a):.1f}" y="{mt}" width="{sx(b) - sx(a):.1f}" height="{h}"/>')
    for v in yt:
        out.append(f'<line class="grid" x1="{ml}" x2="{ml + w}" y1="{sy(v):.1f}" y2="{sy(v):.1f}"/>')
        out.append(f'<text class="tick" x="{ml - 8}" y="{sy(v) + 4:.1f}" text-anchor="end">{esc(fy(v))}</text>')
    for v in xt:
        out.append(f'<text class="tick" x="{sx(v):.1f}" y="{mt + h + 18}" text-anchor="middle">{esc(fx(v))}</text>')
    out.append(f'<line class="axis" x1="{ml}" x2="{ml + w}" y1="{mt + h}" y2="{mt + h}"/>')
    for xv, lab in vlines:
        if x0 <= xv <= x1:
            out.append(f'<line class="vref" x1="{sx(xv):.1f}" x2="{sx(xv):.1f}" y1="{mt}" y2="{mt + h}"/>')
            out.append(f'<text class="vref-t" x="{sx(xv) + 4:.1f}" y="{mt + 12}">{esc(lab)}</text>')
    for i, s in enumerate(series):
        color = s.get("color") or SERIES[i % len(SERIES)]
        pts = [(sx(a), sy(float(b))) for a, b in zip(xs, s["y"]) if b is not None and math.isfinite(float(b))]
        if not pts:
            continue
        if step:
            d = f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"
            for (px, py), (qx, qy) in zip(pts, pts[1:]):
                d += f" H{qx:.1f} V{qy:.1f}"
        else:
            d = "M" + " L".join(f"{px:.1f},{py:.1f}" for px, py in pts)
        cls = "ln-muted" if s.get("muted") else "ln"
        dash = ' stroke-dasharray="4 4"' if s.get("dashed") else ""
        out.append(f'<path class="{cls}" d="{d}" stroke="{color}"{dash}/>')
    out.append(f'<text class="axis-label" x="{ml + w / 2:.1f}" y="{height - 6}" text-anchor="middle">{esc(x_label)}</text>')
    out.append(f'<line class="xhair" x1="0" x2="0" y1="{mt}" y2="{mt + h}" visibility="hidden"/>')
    out.append(f'<rect class="hit" x="{ml}" y="{mt}" width="{w}" height="{h}"/>')
    out.append("</svg>")
    data = {"x": xs, "series": [{"label": s["label"], "y": [None if v is None else float(v) for v in s["y"]],
                                 "color": s.get("color") or SERIES[i % len(SERIES)]} for i, s in enumerate(series)],
            "geom": {"ml": ml, "w": w, "x0": x0, "x1": x1, "width": width}, "pct_y": pct_y, "pct_x": pct_x}
    leg = legend([(s["label"], s.get("color") or SERIES[i % len(SERIES)]) for i, s in enumerate(series)],
                 [bool(s.get("dashed")) for s in series]) if len(series) >= 2 else ""
    ylab = f'<div class="y-label">{esc(y_label)}</div>' if y_label else ""
    return (f'<figure class="fig">{leg}{ylab}<div class="chart-wrap">{"".join(out)}<div class="tip" hidden></div></div>'
            f'<script type="application/json" class="chart-data">{json.dumps(data, ensure_ascii=False)}</script></figure>')


def hbar_chart(items: Sequence[tuple[str, float]], *, highlight: set[int] = frozenset(), width: int = 860, unit: str = "",
               value_fmt: Callable[[float], str] = fmt_num) -> str:
    """Горизонтальные столбики от общей нулевой линии (значения со знаком)."""
    n = len(items)
    if n == 0:
        return ""
    row = 34
    ml, mr = 250, 130
    height = 16 + n * row + 8
    w = width - ml - mr
    vals = [v for _, v in items]
    lo, hi = min(0.0, min(vals)), max(0.0, max(vals))
    span = (hi - lo) or 1.0
    sx = lambda v: ml + (v - lo) / span * w
    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img">']
    out.append(f'<line class="axis" x1="{sx(0):.1f}" x2="{sx(0):.1f}" y1="8" y2="{height - 8}"/>')
    for i, (lab, v) in enumerate(items):
        y = 12 + i * row
        x_a, x_b = sorted((sx(0), sx(v)))
        bw = max(x_b - x_a, 1.0)
        color = "var(--s2)" if i in highlight else "var(--s1)"
        bh = 20
        r = min(4, bw / 2)
        if v >= 0:
            path = (f"M{x_a:.1f},{y} H{x_a + bw - r:.1f} Q{x_a + bw:.1f},{y} {x_a + bw:.1f},{y + r} V{y + bh - r} "
                    f"Q{x_a + bw:.1f},{y + bh} {x_a + bw - r:.1f},{y + bh} H{x_a:.1f} Z")
        else:
            path = (f"M{x_b:.1f},{y} H{x_a + r:.1f} Q{x_a:.1f},{y} {x_a:.1f},{y + r} V{y + bh - r} "
                    f"Q{x_a:.1f},{y + bh} {x_a + r:.1f},{y + bh} H{x_b:.1f} Z")
        out.append(f'<path d="{path}" fill="{color}"><title>{esc(lab)}: {esc(value_fmt(v))}{esc(unit)}</title></path>')
        out.append(f'<text class="bar-l" x="{ml - 10}" y="{y + 14}" text-anchor="end">{esc(lab)}</text>')
        # подпись значения — у конца столбика; для отрицательных — справа от нулевой линии, чтобы не налезать на категорию
        tx = (x_b + 6) if v >= 0 else (sx(0) + 6)
        anchor = "start"
        out.append(f'<text class="bar-v" x="{tx:.1f}" y="{y + 14}" text-anchor="{anchor}">{esc(value_fmt(v))}{esc(unit)}</text>')
    out.append("</svg>")
    return f'<figure class="fig"><div class="chart-wrap">{"".join(out)}</div></figure>'


def column_chart(labels: Sequence[str], values: Sequence[float], *, width: int = 860, height: int = 240, y_label: str = "") -> str:
    n = len(labels)
    if n == 0:
        return ""
    ml, mr, mt, mb = 70, 16, 16, 40
    w, h = width - ml - mr, height - mt - mb
    yt = nice_ticks(min(0.0, min(values)), max(0.0, max(values)), 4)
    y0, y1 = min(yt), max(yt)
    sy = lambda v: mt + h - (v - y0) / ((y1 - y0) or 1) * h
    band = w / n
    bw = min(24.0, band * 0.6)
    fy = _axis_fmt(yt)
    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img">']
    for v in yt:
        out.append(f'<line class="grid" x1="{ml}" x2="{ml + w}" y1="{sy(v):.1f}" y2="{sy(v):.1f}"/>')
        out.append(f'<text class="tick" x="{ml - 8}" y="{sy(v) + 4:.1f}" text-anchor="end">{esc(fy(v))}</text>')
    for i, (lab, v) in enumerate(zip(labels, values)):
        cx = ml + band * (i + 0.5)
        ya, yb = sorted((sy(0), sy(v)))
        hh = max(yb - ya, 1.0)
        r = min(4, hh / 2)
        if v >= 0:
            path = (f"M{cx - bw / 2:.1f},{yb:.1f} V{ya + r:.1f} Q{cx - bw / 2:.1f},{ya:.1f} {cx - bw / 2 + r:.1f},{ya:.1f} "
                    f"H{cx + bw / 2 - r:.1f} Q{cx + bw / 2:.1f},{ya:.1f} {cx + bw / 2:.1f},{ya + r:.1f} V{yb:.1f} Z")
        else:
            path = (f"M{cx - bw / 2:.1f},{ya:.1f} V{yb - r:.1f} Q{cx - bw / 2:.1f},{yb:.1f} {cx - bw / 2 + r:.1f},{yb:.1f} "
                    f"H{cx + bw / 2 - r:.1f} Q{cx + bw / 2:.1f},{yb:.1f} {cx + bw / 2:.1f},{yb - r:.1f} V{ya:.1f} Z")
        out.append(f'<path d="{path}" fill="var(--s1)"><title>{esc(lab)}: {esc(fmt_num(v))}</title></path>')
        out.append(f'<text class="tick" x="{cx:.1f}" y="{mt + h + 18}" text-anchor="middle">{esc(lab)}</text>')
    out.append(f'<line class="axis" x1="{ml}" x2="{ml + w}" y1="{sy(0):.1f}" y2="{sy(0):.1f}"/>')
    out.append("</svg>")
    ylab = f'<div class="y-label">{esc(y_label)}</div>' if y_label else ""
    return f'<figure class="fig">{ylab}<div class="chart-wrap">{"".join(out)}</div></figure>'


def diverging_cell(v: float, vmax: float) -> str:
    """Стиль ячейки тепловой карты: синий (выгода клиента) ↔ серый ↔ красный (потеря)."""
    if vmax <= 0 or v is None or not math.isfinite(v):
        return ""
    a = max(-1.0, min(1.0, v / vmax))
    alpha = abs(a) * 0.85
    var = "--div-pos" if a > 0 else "--div-neg"
    ink = "#fff" if alpha > 0.55 else "var(--text)"
    return f'style="background: color-mix(in srgb, var({var}) {alpha * 100:.0f}%, var(--div-mid)); color:{ink}"'
