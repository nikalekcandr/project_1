"""Self-contained HTML report: market analytics + a filterable explorer of postings.

Charts are inline SVG generated here (no CDN, works offline, prints well).
Visual rules: one series colour, thin bars with rounded data-ends, hairline grids,
values at bar tips, hover/focus tooltips and a table twin for every chart.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from finradar import analytics
from finradar.storage import Store, parse_ts, row_to_dict
from finradar.taxonomy import DOMAIN_LABELS, DOMAIN_SHORT

KIND_LABELS = {
    "vacancy": "Вакансия", "internship": "Стажировка", "graduate_program": "Программа для выпускников",
    "fellowship": "Fellowship", "academic": "Академическая позиция", "grant": "Грант / стипендия",
    "competition": "Кейс-чемпионат / конкурс", "event": "Событие",
}
SENIORITY_LABELS = {
    "intern": "Стажёр", "junior": "Junior", "middle": "Middle", "senior": "Senior",
    "lead": "Lead / VP", "head": "Head / Director", "c_level": "C-level",
}
FORMAT_LABELS = {"remote": "Удалённо", "hybrid": "Гибрид", "office": "Офис"}
CURRENCY_SIGN = {"RUB": "₽", "USD": "$", "EUR": "€", "GBP": "£", "KZT": "₸", "AED": "AED", "CHF": "CHF"}
PERIOD_LABEL = {"month": "мес", "year": "год", "hour": "час", "day": "день"}

SENIORITY_ORDER = ["intern", "junior", "middle", "senior", "lead", "head", "c_level"]


# --------------------------------------------------------------------------- formatting

def fmt_int(n: float | int | None) -> str:
    if n is None:
        return "—"
    return f"{int(round(n)):,}".replace(",", " ")


def fmt_compact(n: float | None, currency: str = "RUB") -> str:
    if n is None:
        return "—"
    if currency == "RUB":
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}".replace(".", ",").replace(",0", "") + " млн ₽"
        return f"{round(n / 1000):.0f} тыс. ₽"
    sign = CURRENCY_SIGN.get(currency, currency + " ")
    if n >= 1_000_000:
        return f"{sign}{n / 1_000_000:.1f}M"
    if n >= 1000:
        return f"{sign}{round(n / 1000):.0f}K"
    return f"{sign}{n:.0f}"


def fmt_pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.0f}%"


def format_salary(d: dict[str, Any]) -> str:
    lo, hi, cur, period = d.get("salary_min"), d.get("salary_max"), d.get("salary_currency"), d.get("salary_period")
    if not (lo or hi):
        return ""
    sign = CURRENCY_SIGN.get(cur or "", cur or "")

    def short(v: float) -> str:
        if v >= 1_000_000:
            return f"{v / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"
        if v >= 10_000:
            return f"{v / 1000:.0f}K"
        return f"{v:,.0f}".replace(",", " ")

    if lo and hi and lo != hi:
        body = f"{short(lo)}–{short(hi)}"
    elif lo and hi:
        body = short(lo)
    elif lo:
        body = f"от {short(lo)}"
    else:
        body = f"до {short(hi)}"
    per = f"/{PERIOD_LABEL[period]}" if period in PERIOD_LABEL else ""
    net = " net" if d.get("salary_gross") is False else (" gross" if d.get("salary_gross") else "")
    return f"{body} {sign}{per}{net}".strip()


def nice_max(v: float) -> float:
    if v <= 0:
        return 1
    exp = 10 ** math.floor(math.log10(v))
    for m in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if v <= m * exp:
            return m * exp
    return 10 * exp


# --------------------------------------------------------------------------- SVG helpers

def _bar_path(x: float, y: float, w: float, h: float, r: float = 4) -> str:
    """Horizontal bar: square at the baseline (left), rounded data-end (right)."""
    if w <= r:
        return f"M{x:.1f},{y:.1f}h{max(w, 1):.1f}v{h:.1f}h{-max(w, 1):.1f}z"
    return (
        f"M{x:.1f},{y:.1f}h{w - r:.1f}a{r},{r} 0 0 1 {r},{r}v{h - 2 * r:.1f}"
        f"a{r},{r} 0 0 1 {-r},{r}h{-(w - r):.1f}z"
    )


def _col_path(x: float, base: float, w: float, h: float, r: float = 3) -> str:
    """Vertical column grown from the baseline with a rounded top."""
    if h <= r:
        return f"M{x:.1f},{base:.1f}v{-max(h, 1):.1f}h{w:.1f}v{max(h, 1):.1f}z"
    return (
        f"M{x:.1f},{base:.1f}v{-(h - r):.1f}a{r},{r} 0 0 1 {r},{-r}h{w - 2 * r:.1f}"
        f"a{r},{r} 0 0 1 {r},{r}v{h - r:.1f}z"
    )


def _trunc(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def bar_chart(rows: list[tuple[str, float]], *, value_fmt=fmt_int, label_width: int = 230, width: int = 640,
              row_h: int = 28, label_chars: int = 34, aria: str = "") -> Markup:
    if not rows:
        return Markup('<p class="empty">Пока нет данных</p>')
    vmax = nice_max(max(v for _, v in rows))
    plot_w = width - label_width - 90
    height = row_h * len(rows) + 8
    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(aria)}">']
    for frac in (0.25, 0.5, 0.75, 1.0):
        gx = label_width + plot_w * frac
        parts.append(f'<line class="grid" x1="{gx:.1f}" y1="0" x2="{gx:.1f}" y2="{height - 4}"/>')
    parts.append(f'<line class="axis" x1="{label_width}" y1="0" x2="{label_width}" y2="{height - 4}"/>')
    for i, (label, value) in enumerate(rows):
        y = i * row_h + 4
        bar_h = 16
        w = plot_w * (value / vmax) if vmax else 0
        tip = f"{label}: {value_fmt(value)}"
        parts.append(f'<g class="mark" tabindex="0" data-tip="{escape(tip)}">')
        parts.append(f'<rect class="hit" x="0" y="{y - 2}" width="{width}" height="{row_h}"/>')
        parts.append(f'<text class="lbl" x="{label_width - 10}" y="{y + bar_h / 2 + 4}" text-anchor="end">{escape(_trunc(label, label_chars))}</text>')
        parts.append(f'<path class="bar" d="{_bar_path(label_width, y, w, bar_h)}"/>')
        parts.append(f'<text class="val" x="{label_width + w + 6:.1f}" y="{y + bar_h / 2 + 4}">{escape(value_fmt(value))}</text>')
        parts.append("</g>")
    parts.append("</svg>")
    return Markup("".join(parts))


def range_chart(rows: list[dict[str, Any]], *, label_of, fmt, width: int = 640, label_width: int = 230,
                row_h: int = 30, aria: str = "") -> Markup:
    """p25–p75 band with a median marker per group."""
    if not rows:
        return Markup('<p class="empty">Недостаточно вакансий с зарплатой (нужно ≥3 в группе)</p>')
    vmax = nice_max(max(r["p75"] or r["median"] for r in rows))
    plot_w = width - label_width - 100
    axis_h = 22
    height = row_h * len(rows) + axis_h + 6
    x = lambda v: label_width + plot_w * (v / vmax)  # noqa: E731
    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(aria)}">']
    for frac in (0, 0.25, 0.5, 0.75, 1.0):
        gx = label_width + plot_w * frac
        parts.append(f'<line class="grid" x1="{gx:.1f}" y1="0" x2="{gx:.1f}" y2="{height - axis_h}"/>')
        tick = "0" if frac == 0 else fmt(vmax * frac)
        parts.append(f'<text class="tick" x="{gx:.1f}" y="{height - 6}" text-anchor="middle">{escape(tick)}</text>')
    for i, r in enumerate(rows):
        y = i * row_h + 6
        label = label_of(r["group"])
        tip = f"{label}: медиана {fmt(r['median'])}, P25–P75 {fmt(r['p25'])} – {fmt(r['p75'])}, n={r['n']}"
        x25, x50, x75 = x(r["p25"]), x(r["median"]), x(r["p75"])
        parts.append(f'<g class="mark" tabindex="0" data-tip="{escape(tip)}">')
        parts.append(f'<rect class="hit" x="0" y="{y - 3}" width="{width}" height="{row_h}"/>')
        parts.append(f'<text class="lbl" x="{label_width - 10}" y="{y + 12}" text-anchor="end">{escape(_trunc(label, 34))}</text>')
        parts.append(f'<rect class="band" x="{x25:.1f}" y="{y + 3}" width="{max(x75 - x25, 2):.1f}" height="12" rx="4"/>')
        parts.append(f'<circle class="dot" cx="{x50:.1f}" cy="{y + 9}" r="5"/>')
        parts.append(f'<text class="val" x="{x75 + 8:.1f}" y="{y + 13}">{escape(fmt(r["median"]))} · n={r["n"]}</text>')
        parts.append("</g>")
    parts.append("</svg>")
    return Markup("".join(parts))


def small_multiples(trend: dict[str, Any], *, width: int = 200, height: int = 70) -> Markup:
    weeks: list[str] = trend.get("weeks", [])
    series: dict[str, list[int]] = trend.get("series", {})
    if not weeks or not series:
        return Markup('<p class="empty">Тренд появится после нескольких дней сбора</p>')
    cards = []
    n = len(weeks)
    gap = 2
    col_w = (width - gap * (n - 1)) / n
    for key, values in series.items():
        label = "Остальные направления" if key == "rest" else analytics.domain_label(key, short=True)
        peak = max(values) or 1
        total = sum(values)
        parts = [f'<svg class="spark" viewBox="0 0 {width} {height + 4}" role="img" aria-label="{escape(label)}">']
        parts.append(f'<line class="axis" x1="0" y1="{height}" x2="{width}" y2="{height}"/>')
        for i, (wk, v) in enumerate(zip(weeks, values)):
            h = (height - 6) * v / peak
            cx = i * (col_w + gap)
            cls = "bar accent" if i == n - 1 else "bar"
            parts.append(f'<g class="mark" tabindex="0" data-tip="{escape(f"{label} · {wk}: {v}")}">')
            parts.append(f'<rect class="hit" x="{cx:.1f}" y="0" width="{col_w + gap:.1f}" height="{height}"/>')
            if v:
                parts.append(f'<path class="{cls}" d="{_col_path(cx, height, col_w, h, r=min(3, col_w / 2))}"/>')
            parts.append("</g>")
        parts.append("</svg>")
        cards.append(
            f'<figure class="sm"><figcaption><span>{escape(_trunc(label, 40))}</span>'
            f'<span class="muted">{fmt_int(total)} за {n} нед. · пик {peak}/нед.</span></figcaption>{"".join(parts)}</figure>'
        )
    return Markup('<div class="sm-grid">' + "".join(cards) + "</div>")


_SEQ = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab"]


def heat_cell(value: float | None, vmin: float, vmax: float) -> Markup:
    if value is None:
        return Markup('<td class="num muted">—</td>')
    t = 0.0 if vmax == vmin else (value - vmin) / (vmax - vmin)
    idx = min(len(_SEQ) - 1, int(t * (len(_SEQ) - 1) + 0.5))
    ink = "#ffffff" if idx >= 6 else "#0b0b0b"
    return Markup(f'<td class="num heat" style="background:{_SEQ[idx]};color:{ink}">{escape(fmt_compact(value))}</td>')


# --------------------------------------------------------------------------- data for the page

def explorer_rows(store: Store, limit: int = 3000) -> list[dict[str, Any]]:
    out = []
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    for row in store.iter_rows("is_active=1 AND is_canonical=1", order="COALESCE(score,0) DESC, first_seen DESC", limit=limit):
        d = row_to_dict(row)
        first_seen = parse_ts(d["first_seen"])
        pub = parse_ts(d.get("published_at")) or first_seen
        out.append({
            "t": d["title"], "c": d.get("company") or "", "u": d["url"],
            "dk": d.get("primary_domain") or "", "d": DOMAIN_SHORT.get(d.get("primary_domain") or "", ""),
            "s": d.get("seniority") or "", "k": d.get("kind") or "vacancy", "f": d.get("work_format") or "",
            "l": d.get("city") or d.get("location") or d.get("country") or "",
            "sal": format_salary(d), "rub": d.get("salary_month_rub"), "usd": d.get("salary_year_usd"),
            "src": d["source"], "pub": pub.date().isoformat() if pub else "",
            "score": d.get("score") or 0, "new": bool(first_seen and first_seen >= week_ago),
            "why": d.get("score_reasons") or [], "sk": (d.get("skills") or [])[:6],
        })
    return out


def build_context(store: Store, title: str = "FinRadar") -> dict[str, Any]:
    rep = analytics.full_report(store)
    ov = rep["overview"]
    dom_label = analytics.domain_label

    def short(k: str | None) -> str:
        return analytics.domain_label(k, short=True)

    domains = [(short(k), v) for k, v in rep["domains"]]
    kinds = [(KIND_LABELS.get(k, k), v) for k, v in rep["kinds"]]
    seniority = sorted(rep["seniority"], key=lambda kv: SENIORITY_ORDER.index(kv[0]) if kv[0] in SENIORITY_ORDER else 99)
    seniority = [(SENIORITY_LABELS.get(k, "Не указан" if k == "—" else k), v) for k, v in seniority]
    formats = [(FORMAT_LABELS.get(k, "Не указан" if k == "—" else k), v) for k, v in rep["work_format"]]
    cities = [(k if k != "—" else "Не определён", v) for k, v in rep["cities"]]
    skills = rep["skills"]

    matrix = rep["salary_matrix"]
    all_vals = [v for row in matrix.values() for v in row.values()]
    vmin, vmax = (min(all_vals), max(all_vals)) if all_vals else (0, 0)
    matrix_rows = []
    for dkey in sorted(matrix, key=lambda d: -max(matrix[d].values())):
        matrix_rows.append({
            "label": short(dkey),
            "cells": [heat_cell(matrix[dkey].get(s), vmin, vmax) for s in SENIORITY_ORDER],
        })

    top = [row_to_dict(r) for r in store.iter_rows("is_active=1 AND is_canonical=1 AND kind='vacancy'", order="score DESC", limit=15)]
    for t in top:
        t["salary_fmt"] = format_salary(t)
        t["domain_label"] = DOMAIN_SHORT.get(t.get("primary_domain") or "", "")

    explorer = explorer_rows(store)
    return {
        "title": title,
        "generated": datetime.now(timezone.utc).astimezone().strftime("%d.%m.%Y %H:%M"),
        "ov": ov,
        "fmt_int": fmt_int, "fmt_pct": fmt_pct, "fmt_compact": fmt_compact,
        "domain_label": dom_label,
        "short_label": short,
        "charts": {
            "domains": bar_chart(domains, aria="Активные вакансии по направлениям"),
            "kinds": bar_chart(kinds, aria="Типы возможностей"),
            "seniority": bar_chart(seniority, aria="Уровни позиций"),
            "formats": bar_chart(formats, aria="Формат работы"),
            "cities": bar_chart(cities, aria="Города"),
            "skills": bar_chart([(s["skill"], s["share"] * 100) for s in skills], value_fmt=lambda v: f"{v:.0f}%", aria="Навыки"),
            "salary_domestic": range_chart(rep["salary_domestic"], label_of=short, fmt=lambda v: fmt_compact(v, "RUB"),
                                           aria="Зарплаты по направлениям, ₽/мес на руки"),
            "salary_global": range_chart(rep["salary_global"], label_of=short, fmt=lambda v: fmt_compact(v, "USD"),
                                         aria="Зарплаты по направлениям, USD/год"),
            "salary_seniority": range_chart(
                sorted(rep["salary_by_seniority"], key=lambda r: SENIORITY_ORDER.index(r["group"]) if r["group"] in SENIORITY_ORDER else 99),
                label_of=lambda k: SENIORITY_LABELS.get(k, k), fmt=lambda v: fmt_compact(v, "RUB"), aria="Зарплаты по уровням"),
            "trend": small_multiples(rep["trend"]),
        },
        "tables": {
            "domains": domains, "kinds": kinds, "seniority": seniority, "formats": formats, "cities": cities,
        },
        "rep": rep,
        "skills": skills,
        "matrix_rows": matrix_rows,
        "seniority_cols": [SENIORITY_LABELS[s] for s in SENIORITY_ORDER],
        "top": top,
        "explorer_json": Markup(json.dumps(explorer, ensure_ascii=False).replace("</", "<\\/")),
        "explorer_count": len(explorer),
        "domain_options": sorted({(r["dk"], DOMAIN_LABELS.get(r["dk"], r["dk"])) for r in explorer if r["dk"]}, key=lambda x: x[1]),
        "source_options": sorted({r["src"] for r in explorer}),
        "kind_labels": KIND_LABELS, "seniority_labels": SENIORITY_LABELS, "format_labels": FORMAT_LABELS,
        "labels_json": Markup(json.dumps({"k": KIND_LABELS, "s": SENIORITY_LABELS, "f": FORMAT_LABELS}, ensure_ascii=False)),
    }


def render(store: Store, out_path: str | Path, title: str = "FinRadar") -> Path:
    env = Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True, lstrip_blocks=True,
    )
    html = env.get_template("report.html.j2").render(**build_context(store, title))
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out
