"""Digest of new, best-matching postings — as Markdown/plain text and Telegram HTML."""

from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from typing import Any

from finradar.report import FORMAT_LABELS, KIND_LABELS, format_salary
from finradar.storage import Store, row_to_dict
from finradar.taxonomy import DOMAIN_LABELS


def select(store: Store, *, days: float = 1.0, min_score: float = 0.0, limit: int = 30,
           only_unsent: bool = True) -> list[dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    where = "is_active=1 AND is_canonical=1 AND first_seen >= ? AND COALESCE(score,0) >= ?"
    if only_unsent:
        where += " AND notified_at IS NULL"
    rows = store.iter_rows(where, (since, min_score), order="score DESC, first_seen DESC", limit=limit)
    return [row_to_dict(r) for r in rows]


def mark_sent(store: Store, items: list[dict[str, Any]]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    # Mark the whole cluster so the same role from another source is not re-sent.
    clusters = [(now, it["cluster_id"]) for it in items]
    store.bulk_update("UPDATE vacancies SET notified_at=? WHERE cluster_id=?", clusters)


def _line_meta(it: dict[str, Any]) -> list[str]:
    meta = []
    if it.get("company"):
        meta.append(it["company"])
    sal = format_salary(it)
    if sal:
        meta.append(sal)
    loc = it.get("city") or it.get("location")
    if loc:
        meta.append(loc)
    if it.get("work_format"):
        meta.append(FORMAT_LABELS.get(it["work_format"], it["work_format"]))
    if it.get("kind") and it["kind"] != "vacancy":
        meta.append(KIND_LABELS.get(it["kind"], it["kind"]))
    return meta


def to_markdown(items: list[dict[str, Any]], title: str = "FinRadar: новые позиции") -> str:
    if not items:
        return f"# {title}\n\nНовых подходящих позиций нет."
    out = [f"# {title}", ""]
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        by_domain.setdefault(it.get("primary_domain") or "other", []).append(it)
    for dom, group in by_domain.items():
        out.append(f"## {DOMAIN_LABELS.get(dom, dom)}")
        for it in group:
            meta = " · ".join(_line_meta(it))
            why = ", ".join(it.get("score_reasons") or [])
            out.append(f"- **[{it['title']}]({it['url']})** — {meta}  ")
            out.append(f"  скор {it.get('score') or 0:.0f}{' · ' + why if why else ''} · {it['source']}")
        out.append("")
    return "\n".join(out)


def to_telegram_html(items: list[dict[str, Any]], title: str = "FinRadar: новые позиции") -> list[str]:
    """Telegram messages (HTML parse mode), split to stay under the 4096-char limit."""
    esc = lambda s: html.escape(str(s), quote=False)  # noqa: E731
    header = f"<b>{esc(title)}</b> — {len(items)}"
    blocks = []
    for it in items:
        meta = " · ".join(esc(m) for m in _line_meta(it))
        blocks.append(
            f"<b>{it.get('score') or 0:.0f}</b> <a href=\"{html.escape(it['url'])}\">{esc(it['title'])}</a>\n{meta}"
        )
    messages, cur = [], header
    for b in blocks:
        if len(cur) + len(b) + 2 > 3900:
            messages.append(cur)
            cur = b
        else:
            cur += "\n\n" + b
    messages.append(cur)
    return messages
