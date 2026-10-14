"""Market analytics over the collected postings.

All functions work on *canonical* active postings (one per dedup cluster) unless
stated otherwise, so a role cross-posted to five sites is counted once.

Salaries are analysed in two separate markets because mixing them is misleading:
  * domestic  (RUB, KZT, BYN, UZS, ...) — monthly take-home RUB
  * global    (USD, EUR, GBP, CHF, AED, ...) — annual gross USD
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from finradar.storage import Store, parse_ts
from finradar.taxonomy import DOMAIN_LABELS, DOMAIN_SHORT

DOMESTIC_CURRENCIES = ("RUB", "KZT", "BYN", "UZS", "AMD", "GEL")
ACTIVE = "is_active=1 AND is_canonical=1"


def quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    vals = sorted(values)
    pos = (len(vals) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _since(days: float) -> str:
    return (_now() - timedelta(days=days)).isoformat()


def overview(store: Store) -> dict[str, Any]:
    c = store.conn
    one = lambda sql, *p: c.execute(sql, p).fetchone()[0]  # noqa: E731
    active_rows = one("SELECT COUNT(*) FROM vacancies WHERE is_active=1")
    active = one(f"SELECT COUNT(*) FROM vacancies WHERE {ACTIVE}")
    with_salary = one(f"SELECT COUNT(*) FROM vacancies WHERE {ACTIVE} AND (salary_min IS NOT NULL OR salary_max IS NOT NULL)")
    remote = one(f"SELECT COUNT(*) FROM vacancies WHERE {ACTIVE} AND work_format='remote'")
    return {
        "active": active,
        "active_rows": active_rows,
        "duplicates": active_rows - active,
        "dup_share": round((active_rows - active) / active_rows, 3) if active_rows else 0.0,
        "new_24h": one("SELECT COUNT(*) FROM vacancies WHERE is_canonical=1 AND first_seen >= ?", _since(1)),
        "new_7d": one("SELECT COUNT(*) FROM vacancies WHERE is_canonical=1 AND first_seen >= ?", _since(7)),
        "new_30d": one("SELECT COUNT(*) FROM vacancies WHERE is_canonical=1 AND first_seen >= ?", _since(30)),
        "closed_7d": one("SELECT COUNT(*) FROM vacancies WHERE is_active=0 AND closed_at >= ?", _since(7)),
        "salary_share": round(with_salary / active, 3) if active else 0.0,
        "remote_share": round(remote / active, 3) if active else 0.0,
        "sources": one("SELECT COUNT(DISTINCT source) FROM vacancies WHERE is_active=1"),
        "companies": one(f"SELECT COUNT(DISTINCT company_key) FROM vacancies WHERE {ACTIVE} AND company_key != ''"),
        "total_seen": one("SELECT COUNT(*) FROM vacancies"),
    }


def distribution(store: Store, field: str, limit: int = 20, where: str = ACTIVE) -> list[tuple[str, int]]:
    allowed = {"primary_domain", "kind", "seniority", "work_format", "city", "country", "language", "source", "employment"}
    if field not in allowed:
        raise ValueError(field)
    rows = store.conn.execute(
        f"SELECT COALESCE({field}, '—') k, COUNT(*) n FROM vacancies WHERE {where} GROUP BY k ORDER BY n DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [(r["k"], r["n"]) for r in rows]


def domain_label(key: str | None, short: bool = False) -> str:
    labels = DOMAIN_SHORT if short else DOMAIN_LABELS
    return labels.get(key or "", key or "—")


def salary_stats(store: Store, by: str = "primary_domain", market: str = "domestic", min_n: int = 3) -> list[dict[str, Any]]:
    """Median / quartiles of normalized salary per group for one market."""
    if by not in {"primary_domain", "seniority", "city", "kind", "work_format", "source"}:
        raise ValueError(by)
    placeholders = ",".join("?" * len(DOMESTIC_CURRENCIES))
    if market == "domestic":
        sql = f"SELECT {by} g, salary_month_rub v FROM vacancies WHERE {ACTIVE} AND salary_month_rub IS NOT NULL AND salary_currency IN ({placeholders})"
    else:
        sql = f"SELECT {by} g, salary_year_usd v FROM vacancies WHERE {ACTIVE} AND salary_year_usd IS NOT NULL AND salary_currency NOT IN ({placeholders})"
    groups: dict[str, list[float]] = defaultdict(list)
    for r in store.conn.execute(sql, DOMESTIC_CURRENCIES):
        groups[r["g"] or "—"].append(float(r["v"]))
    out = []
    for g, vals in groups.items():
        if len(vals) < min_n:
            continue
        out.append({
            "group": g, "n": len(vals), "p25": quantile(vals, 0.25), "median": quantile(vals, 0.5),
            "p75": quantile(vals, 0.75), "max": max(vals),
        })
    return sorted(out, key=lambda x: x["median"] or 0, reverse=True)


def salary_matrix(store: Store, market: str = "domestic", min_n: int = 2) -> dict[str, dict[str, float]]:
    """Median salary per (domain, seniority) — a compact compensation map."""
    placeholders = ",".join("?" * len(DOMESTIC_CURRENCIES))
    col, op = ("salary_month_rub", "IN") if market == "domestic" else ("salary_year_usd", "NOT IN")
    groups: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in store.conn.execute(
        f"SELECT primary_domain d, seniority s, {col} v FROM vacancies WHERE {ACTIVE} AND {col} IS NOT NULL "
        f"AND salary_currency {op} ({placeholders})",
        DOMESTIC_CURRENCIES,
    ):
        groups[(r["d"] or "—", r["s"] or "—")].append(float(r["v"]))
    matrix: dict[str, dict[str, float]] = defaultdict(dict)
    for (d, s), vals in groups.items():
        if len(vals) >= min_n:
            matrix[d][s] = quantile(vals, 0.5)
    return dict(matrix)


def weekly_trend(store: Store, weeks: int = 12, top: int = 6) -> dict[str, Any]:
    """New canonical postings per ISO week, split by primary domain."""
    start = _now() - timedelta(weeks=weeks)
    rows = store.conn.execute(
        "SELECT primary_domain d, COALESCE(published_at, first_seen) t FROM vacancies WHERE is_canonical=1 "
        "AND COALESCE(published_at, first_seen) >= ?",
        (start.isoformat(),),
    ).fetchall()
    week_keys = []
    cursor = start - timedelta(days=start.weekday())
    while cursor <= _now():
        y, w, _ = cursor.isocalendar()
        week_keys.append(f"{y}-W{w:02d}")
        cursor += timedelta(weeks=1)
    totals = Counter(r["d"] or "other" for r in rows)
    leaders = [d for d, _ in totals.most_common(top)]
    series: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        ts = parse_ts(r["t"])
        if not ts:
            continue
        y, w, _ = ts.isocalendar()
        key = f"{y}-W{w:02d}"
        d = r["d"] or "other"
        series[d if d in leaders else "rest"][key] += 1
    return {
        "weeks": week_keys,
        "series": {d: [series[d].get(k, 0) for k in week_keys] for d in [*leaders, "rest"] if d in series},
    }


def market_heat(store: Store, top: int = 12) -> list[dict[str, Any]]:
    """Last 7 days of new postings vs the average week of the previous 8 weeks."""
    rows = store.conn.execute(
        "SELECT primary_domain d, first_seen t FROM vacancies WHERE is_canonical=1 AND first_seen >= ?", (_since(63),)
    ).fetchall()
    recent, base = Counter(), Counter()
    cutoff = _now() - timedelta(days=7)
    for r in rows:
        ts = parse_ts(r["t"])
        (recent if ts and ts >= cutoff else base)[r["d"] or "other"] += 1
    out = []
    for d in set(recent) | set(base):
        avg = base[d] / 8
        out.append({"domain": d, "last_7d": recent[d], "avg_week": round(avg, 1),
                    "heat": round(recent[d] / avg, 2) if avg else None})
    return sorted(out, key=lambda x: x["last_7d"], reverse=True)[:top]


def top_companies(store: Store, n: int = 25) -> list[dict[str, Any]]:
    rows = store.conn.execute(
        f"SELECT company, company_key, first_seen, primary_domain, salary_month_rub, salary_year_usd FROM vacancies "
        f"WHERE {ACTIVE} AND company_key != '' AND company_key IS NOT NULL"
    ).fetchall()
    agg: dict[str, dict[str, Any]] = {}
    now = _now()
    for r in rows:
        a = agg.setdefault(r["company_key"], {"company": r["company"], "active": 0, "new_14d": 0, "prev_14d": 0,
                                              "domains": Counter(), "rub": [], "usd": []})
        a["active"] += 1
        ts = parse_ts(r["first_seen"])
        if ts and ts >= now - timedelta(days=14):
            a["new_14d"] += 1
        elif ts and ts >= now - timedelta(days=28):
            a["prev_14d"] += 1
        a["domains"][r["primary_domain"] or "other"] += 1
        if r["salary_month_rub"]:
            a["rub"].append(r["salary_month_rub"])
    out = []
    for a in agg.values():
        out.append({
            "company": a["company"], "active": a["active"], "new_14d": a["new_14d"], "prev_14d": a["prev_14d"],
            "momentum": a["new_14d"] - a["prev_14d"],
            "top_domain": a["domains"].most_common(1)[0][0],
            "median_rub": quantile(a["rub"], 0.5),
        })
    return sorted(out, key=lambda x: (x["active"], x["new_14d"]), reverse=True)[:n]


def skills_demand(store: Store, n: int = 25, domain: str | None = None) -> list[dict[str, Any]]:
    where = ACTIVE + (" AND primary_domain=?" if domain else "")
    params = (domain,) if domain else ()
    rows = store.conn.execute(f"SELECT skills, salary_month_rub, salary_currency FROM vacancies WHERE {where}", params).fetchall()
    total = len(rows)
    counts: Counter = Counter()
    with_sal: dict[str, list[float]] = defaultdict(list)
    all_sal: list[float] = []
    for r in rows:
        skills = json.loads(r["skills"] or "[]")
        counts.update(skills)
        if r["salary_month_rub"] and r["salary_currency"] in DOMESTIC_CURRENCIES:
            all_sal.append(r["salary_month_rub"])
            for s in skills:
                with_sal[s].append(r["salary_month_rub"])
    base = quantile(all_sal, 0.5)
    out = []
    for skill, cnt in counts.most_common(n):
        med = quantile(with_sal[skill], 0.5) if len(with_sal[skill]) >= 5 else None
        out.append({
            "skill": skill, "count": cnt, "share": round(cnt / total, 3) if total else 0,
            "median_rub": med, "premium": round(med / base - 1, 3) if med and base else None,
        })
    return out


def source_quality(store: Store) -> list[dict[str, Any]]:
    """Which sources actually matter: volume, unique contribution, salary disclosure, freshness."""
    rows = store.conn.execute(
        "SELECT source, cluster_id, is_canonical, salary_min, salary_max, relevance, "
        "COALESCE(published_at, first_seen) t FROM vacancies WHERE is_active=1"
    ).fetchall()
    cluster_sizes = Counter(r["cluster_id"] for r in rows)
    agg: dict[str, dict[str, Any]] = {}
    now = _now()
    for r in rows:
        a = agg.setdefault(r["source"], {"active": 0, "exclusive": 0, "salary": 0, "ages": [], "relevance": []})
        a["active"] += 1
        if cluster_sizes[r["cluster_id"]] == 1:
            a["exclusive"] += 1
        if r["salary_min"] or r["salary_max"]:
            a["salary"] += 1
        ts = parse_ts(r["t"])
        if ts:
            a["ages"].append((now - ts).total_seconds() / 86400)
        a["relevance"].append(r["relevance"] or 0)
    last_runs = store.last_runs()
    out = []
    for src, a in agg.items():
        run = last_runs.get(src)
        out.append({
            "source": src, "active": a["active"],
            "exclusive_share": round(a["exclusive"] / a["active"], 3),
            "salary_share": round(a["salary"] / a["active"], 3),
            "median_age_days": round(quantile(a["ages"], 0.5) or 0, 1),
            "avg_relevance": round(sum(a["relevance"]) / len(a["relevance"]), 1),
            "last_status": run["status"] if run else None,
            "last_run": run["finished_at"] if run else None,
        })
    for src, run in last_runs.items():
        if src not in agg:
            out.append({"source": src, "active": 0, "exclusive_share": 0, "salary_share": 0, "median_age_days": None,
                        "avg_relevance": None, "last_status": run["status"], "last_run": run["finished_at"]})
    return sorted(out, key=lambda x: x["active"], reverse=True)


def lifetime(store: Store, min_n: int = 3) -> list[dict[str, Any]]:
    """How long postings stay open before disappearing (time-to-fill proxy) per domain."""
    rows = store.conn.execute(
        "SELECT primary_domain d, COALESCE(published_at, first_seen) s, closed_at c FROM vacancies "
        "WHERE is_active=0 AND closed_at IS NOT NULL AND is_canonical=1"
    ).fetchall()
    groups: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        s, c = parse_ts(r["s"]), parse_ts(r["c"])
        if s and c and c >= s:
            groups[r["d"] or "other"].append((c - s).total_seconds() / 86400)
    out = [
        {"domain": d, "n": len(v), "median_days": round(quantile(v, 0.5), 1), "closed_within_7d": round(sum(x <= 7 for x in v) / len(v), 2)}
        for d, v in groups.items() if len(v) >= min_n
    ]
    return sorted(out, key=lambda x: x["median_days"])


def salary_changes(store: Store, days: int = 60) -> dict[str, Any]:
    """Salary edits on live postings — a signal of roles that are hard to fill."""
    rows = store.conn.execute(
        "SELECT uid, field, old, new FROM changes WHERE field IN ('salary_min','salary_max') AND at >= ?", (_since(days),)
    ).fetchall()
    deltas = []
    for r in rows:
        try:
            old, new = float(r["old"]), float(r["new"])
        except (TypeError, ValueError):
            continue
        if old > 0:
            deltas.append(new / old - 1)
    return {
        "changes": len(rows), "postings": len({r["uid"] for r in rows}),
        "median_change": round(quantile(deltas, 0.5), 3) if deltas else None,
        "raised": sum(d > 0 for d in deltas), "lowered": sum(d < 0 for d in deltas),
    }


def full_report(store: Store) -> dict[str, Any]:
    return {
        "generated_at": _now().isoformat(),
        "overview": overview(store),
        "domains": distribution(store, "primary_domain"),
        "kinds": distribution(store, "kind"),
        "seniority": distribution(store, "seniority"),
        "work_format": distribution(store, "work_format"),
        "cities": distribution(store, "city", limit=15),
        "countries": distribution(store, "country", limit=15),
        "sources": source_quality(store),
        "salary_domestic": salary_stats(store, "primary_domain", "domestic"),
        "salary_global": salary_stats(store, "primary_domain", "global"),
        "salary_by_seniority": salary_stats(store, "seniority", "domestic"),
        "salary_matrix": salary_matrix(store, "domestic"),
        "trend": weekly_trend(store),
        "heat": market_heat(store),
        "companies": top_companies(store),
        "skills": skills_demand(store),
        "lifetime": lifetime(store),
        "salary_changes": salary_changes(store),
    }
