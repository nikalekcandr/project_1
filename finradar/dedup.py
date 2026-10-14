"""Cross-source deduplication.

The same role is often posted on hh.ru, Habr Career, a Telegram channel and the
company's own ATS. We group such postings into clusters (union-find) and mark one
canonical posting per cluster; analytics and digests count clusters, not rows.

Blocking keys keep it near-linear:
  * same normalized company + same normalized title             -> duplicate
  * same normalized title, description shingle Jaccard >= 0.5    -> duplicate
    (covers Telegram reposts where the company is not parsed)
"""

from __future__ import annotations

import re
from collections import defaultdict

from finradar.storage import Store
from finradar.textutil import norm_key

_TITLE_STOP = {
    "вакансия", "vacancy", "job", "remote", "удаленно", "удаленка", "hybrid", "гибрид", "office", "офис",
    "м", "ж", "в", "на", "и", "the", "a", "an", "of", "for", "to", "at", "in", "with", "по", "для",
    "москва", "moscow", "london", "лондон", "спб", "full", "time", "fulltime", "полная", "занятость",
}

DEFAULT_PRIORITY = {
    "hh": 5, "ats": 5, "habr": 4, "getmatch": 4, "superjob": 3, "trudvsem": 2, "jsonld_crawler": 4,
    "html_list": 3, "remote_board": 3, "keyed_api": 3, "rss": 2, "telegram": 1, "email_alerts": 1,
}


def title_key(title: str) -> str:
    tokens = [t for t in norm_key(re.sub(r"\(.*?\)", " ", title or "")).split() if t not in _TITLE_STOP]
    return " ".join(sorted(set(tokens)))


def shingles(text: str, n: int = 3) -> set[str]:
    words = norm_key(text).split()[:400]
    if len(words) < n:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def recluster(store: Store, source_types: dict[str, str] | None = None, priority: dict[str, int] | None = None) -> dict[str, int]:
    """Recompute clusters among active postings. Returns basic stats."""
    source_types = source_types or {}
    prio = {**DEFAULT_PRIORITY, **(priority or {})}
    rows = list(
        store.conn.execute(
            "SELECT uid, source, title, company_key, description, salary_min, salary_max, first_seen, published_at "
            "FROM vacancies WHERE is_active=1"
        )
    )
    uf = _UnionFind()
    by_company_title: dict[tuple[str, str], list[str]] = defaultdict(list)
    by_title: dict[str, list[int]] = defaultdict(list)
    shingle_cache: dict[int, set[str]] = {}

    for i, r in enumerate(rows):
        uf.find(r["uid"])
        tk = title_key(r["title"])
        if not tk:
            continue
        if r["company_key"]:
            by_company_title[(r["company_key"], tk)].append(r["uid"])
        by_title[tk].append(i)

    for uids in by_company_title.values():
        for other in uids[1:]:
            uf.union(uids[0], other)

    for idxs in by_title.values():
        if len(idxs) < 2 or len(idxs) > 200:
            continue
        for a_pos, a in enumerate(idxs):
            ra = rows[a]
            for b in idxs[a_pos + 1 :]:
                rb = rows[b]
                if ra["source"] == rb["source"] and ra["company_key"] == rb["company_key"]:
                    continue  # same source + company + title: already merged or a legit re-post
                if ra["company_key"] and rb["company_key"] and ra["company_key"] != rb["company_key"]:
                    if not (ra["company_key"] in rb["company_key"] or rb["company_key"] in ra["company_key"]):
                        continue
                sa = shingle_cache.setdefault(a, shingles((ra["description"] or "")[:3000]))
                sb = shingle_cache.setdefault(b, shingles((rb["description"] or "")[:3000]))
                same_company = bool(ra["company_key"]) and ra["company_key"] == rb["company_key"]
                if jaccard(sa, sb) >= (0.3 if same_company else 0.5):
                    uf.union(ra["uid"], rb["uid"])

    clusters: dict[str, list] = defaultdict(list)
    for r in rows:
        clusters[uf.find(r["uid"])].append(r)

    def quality(r) -> tuple:
        stype = source_types.get(r["source"], r["source"])
        return (
            prio.get(stype, prio.get(r["source"], 2)),
            1 if (r["salary_min"] or r["salary_max"]) else 0,
            min(len(r["description"] or "") // 500, 6),
            r["published_at"] or r["first_seen"],
        )

    updates = []
    dup_rows = 0
    for members in clusters.values():
        best = max(members, key=quality)
        cluster_id = min(m["uid"] for m in members)
        for m in members:
            updates.append((cluster_id, 1 if m["uid"] == best["uid"] else 0, m["uid"]))
        dup_rows += len(members) - 1
    if updates:
        store.bulk_update("UPDATE vacancies SET cluster_id=?, is_canonical=? WHERE uid=?", updates)
    return {"active": len(rows), "clusters": len(clusters), "duplicates": dup_rows}
