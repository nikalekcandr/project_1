"""SQLite storage with full-text search, change history and run bookkeeping."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Iterable, Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from finradar.models import Vacancy, dumps, utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS vacancies (
    uid TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT,
    company_key TEXT,
    description TEXT,
    location TEXT,
    city TEXT,
    country TEXT,
    work_format TEXT,
    employment TEXT,
    seniority TEXT,
    kind TEXT,
    salary_min REAL,
    salary_max REAL,
    salary_currency TEXT,
    salary_period TEXT,
    salary_gross INTEGER,
    salary_text TEXT,
    salary_month_rub REAL,
    salary_year_usd REAL,
    published_at TEXT,
    deadline TEXT,
    tags TEXT,
    skills TEXT,
    domains TEXT,
    primary_domain TEXT,
    language TEXT,
    relevance REAL,
    raw TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    closed_at TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    content_hash TEXT,
    cluster_id TEXT,
    is_canonical INTEGER NOT NULL DEFAULT 1,
    score REAL,
    score_reasons TEXT,
    llm TEXT,
    notified_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_vac_source ON vacancies(source);
CREATE INDEX IF NOT EXISTS ix_vac_active ON vacancies(is_active, is_canonical);
CREATE INDEX IF NOT EXISTS ix_vac_first_seen ON vacancies(first_seen);
CREATE INDEX IF NOT EXISTS ix_vac_cluster ON vacancies(cluster_id);
CREATE INDEX IF NOT EXISTS ix_vac_domain ON vacancies(primary_domain);
CREATE INDEX IF NOT EXISTS ix_vac_company ON vacancies(company_key);

CREATE VIRTUAL TABLE IF NOT EXISTS vacancies_fts USING fts5(
    uid UNINDEXED, title, company, description, tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT NOT NULL,
    at TEXT NOT NULL,
    field TEXT NOT NULL,
    old TEXT,
    new TEXT
);
CREATE INDEX IF NOT EXISTS ix_changes_uid ON changes(uid);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT,
    fetched INTEGER DEFAULT 0,
    kept INTEGER DEFAULT 0,
    new INTEGER DEFAULT 0,
    updated INTEGER DEFAULT 0,
    closed INTEGER DEFAULT 0,
    error TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT
);
"""

_LIST_FIELDS = ("tags", "skills", "domains")
_TRACKED = ("title", "salary_min", "salary_max", "salary_currency", "company", "work_format")


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self.lock = threading.RLock()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------ meta
    def get_meta(self, key: str, max_age_hours: float | None = None) -> Any:
        row = self.conn.execute("SELECT value, updated_at FROM meta WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        if max_age_hours is not None:
            age = utcnow() - datetime.fromisoformat(row["updated_at"])
            if age > timedelta(hours=max_age_hours):
                return None
        return json.loads(row["value"])

    def set_meta(self, key: str, value: Any) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT INTO meta(key, value, updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, dumps(value), utcnow().isoformat()),
            )

    # ------------------------------------------------------------------ runs
    def start_run(self, source: str) -> int:
        with self.lock:
            cur = self.conn.execute(
                "INSERT INTO runs(source, started_at, status) VALUES(?,?,?)", (source, utcnow().isoformat(), "running")
            )
            return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str, error: str | None = None, **counts: int) -> None:
        cols = ", ".join(f"{k}=?" for k in counts)
        sql = f"UPDATE runs SET finished_at=?, status=?, error=?{', ' + cols if cols else ''} WHERE id=?"
        with self.lock:
            self.conn.execute(sql, (utcnow().isoformat(), status, error, *counts.values(), run_id))

    def last_runs(self) -> dict[str, sqlite3.Row]:
        rows = self.conn.execute(
            "SELECT r.* FROM runs r JOIN (SELECT source, MAX(id) mid FROM runs GROUP BY source) x ON r.id = x.mid"
        ).fetchall()
        return {r["source"]: r for r in rows}

    # ------------------------------------------------------------------ vacancies
    def upsert(self, items: Iterable[Vacancy], *, now: datetime | None = None) -> tuple[int, int, list[str]]:
        """Insert or refresh vacancies. Returns (new, updated, uids_seen)."""
        from finradar.textutil import norm_company

        now = now or utcnow()
        now_s = now.isoformat()
        new = updated = 0
        seen: list[str] = []
        with self.lock:
            self.conn.execute("BEGIN")
            try:
                for v in items:
                    uid = v.uid
                    seen.append(uid)
                    row = self.conn.execute(
                        "SELECT uid, content_hash, title, salary_min, salary_max, salary_currency, company, work_format, is_active "
                        "FROM vacancies WHERE uid=?",
                        (uid,),
                    ).fetchone()
                    data = self._row_values(v)
                    data["company_key"] = norm_company(v.company)
                    content_hash = hashlib.sha1(
                        dumps([v.title, v.company, v.description, v.salary_min, v.salary_max, v.salary_currency]).encode()
                    ).hexdigest()[:16]
                    data["content_hash"] = content_hash
                    if row is None:
                        data.update(first_seen=now_s, last_seen=now_s, is_active=1, cluster_id=uid, is_canonical=1)
                        cols = ", ".join(data)
                        self.conn.execute(
                            f"INSERT INTO vacancies({cols}) VALUES({', '.join('?' * len(data))})", tuple(data.values())
                        )
                        self._fts_replace(uid, v)
                        new += 1
                        continue
                    if row["content_hash"] != content_hash:
                        for f in _TRACKED:
                            old, cur = row[f], data[f]
                            if old != cur and not (old is None and cur is None):
                                self.conn.execute(
                                    "INSERT INTO changes(uid, at, field, old, new) VALUES(?,?,?,?,?)",
                                    (uid, now_s, f, None if old is None else str(old), None if cur is None else str(cur)),
                                )
                        updated += 1
                        self._fts_replace(uid, v)
                    data.update(last_seen=now_s, is_active=1, closed_at=None)
                    assignments = ", ".join(f"{k}=?" for k in data)
                    self.conn.execute(f"UPDATE vacancies SET {assignments} WHERE uid=?", (*data.values(), uid))
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
        return new, updated, seen

    @staticmethod
    def _row_values(v: Vacancy) -> dict[str, Any]:
        d: dict[str, Any] = {}
        for name in Vacancy.field_names():
            val = getattr(v, name)
            if name in _LIST_FIELDS:
                val = dumps(val)
            elif name == "raw":
                val = dumps(val)[:20000]
            elif isinstance(val, datetime):
                val = _iso(val)
            elif isinstance(val, bool):
                val = int(val)
            elif name in ("salary_min", "salary_max") and val is not None:
                val = float(val)
            d[name] = val
        d["uid"] = v.uid
        return d

    def _fts_replace(self, uid: str, v: Vacancy) -> None:
        self.conn.execute("DELETE FROM vacancies_fts WHERE uid=?", (uid,))
        self.conn.execute(
            "INSERT INTO vacancies_fts(uid, title, company, description) VALUES(?,?,?,?)",
            (uid, v.title, v.company or "", v.description[:8000]),
        )

    def close_missing(self, source: str, seen: Iterable[str], *, now: datetime | None = None) -> int:
        """Mark vacancies of a full-listing source that were not seen in this run as closed."""
        now_s = (now or utcnow()).isoformat()
        seen_set = set(seen)
        with self.lock:
            rows = self.conn.execute("SELECT uid FROM vacancies WHERE source=? AND is_active=1", (source,)).fetchall()
            gone = [r["uid"] for r in rows if r["uid"] not in seen_set]
            self.conn.executemany(
                "UPDATE vacancies SET is_active=0, closed_at=? WHERE uid=?", [(now_s, uid) for uid in gone]
            )
        return len(gone)

    def expire(self, source: str, ttl_days: int, *, now: datetime | None = None) -> int:
        """For stream-like sources (Telegram, RSS) close postings older than ``ttl_days``."""
        now = now or utcnow()
        cutoff = (now - timedelta(days=ttl_days)).isoformat()
        with self.lock:
            cur = self.conn.execute(
                "UPDATE vacancies SET is_active=0, closed_at=? WHERE source=? AND is_active=1 "
                "AND COALESCE(published_at, first_seen) < ?",
                (now.isoformat(), source, cutoff),
            )
            return cur.rowcount

    def iter_rows(self, where: str = "1=1", params: tuple = (), order: str = "first_seen DESC", limit: int | None = None) -> Iterator[sqlite3.Row]:
        sql = f"SELECT * FROM vacancies WHERE {where} ORDER BY {order}"
        if limit:
            sql += f" LIMIT {int(limit)}"
        yield from self.conn.execute(sql, params)

    def get(self, uid: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM vacancies WHERE uid=?", (uid,)).fetchone()

    def search(self, query: str, *, active_only: bool = True, limit: int = 50) -> list[sqlite3.Row]:
        fts_query = " ".join(f'"{tok}"*' for tok in query.replace('"', " ").split() if tok)
        if not fts_query:
            return []
        sql = (
            "SELECT v.* FROM vacancies_fts f JOIN vacancies v ON v.uid = f.uid "
            "WHERE vacancies_fts MATCH ? "
            + ("AND v.is_active=1 AND v.is_canonical=1 " if active_only else "")
            + "ORDER BY bm25(vacancies_fts, 0, 10.0, 3.0, 1.0) LIMIT ?"
        )
        return self.conn.execute(sql, (fts_query, limit)).fetchall()

    def update_fields(self, uid: str, **fields: Any) -> None:
        if not fields:
            return
        assignments = ", ".join(f"{k}=?" for k in fields)
        with self.lock:
            self.conn.execute(f"UPDATE vacancies SET {assignments} WHERE uid=?", (*fields.values(), uid))

    def bulk_update(self, sql: str, rows: list[tuple]) -> None:
        with self.lock:
            self.conn.execute("BEGIN")
            self.conn.executemany(sql, rows)
            self.conn.execute("COMMIT")

    def count(self, where: str = "1=1", params: tuple = ()) -> int:
        return int(self.conn.execute(f"SELECT COUNT(*) FROM vacancies WHERE {where}", params).fetchone()[0])


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for f in (*_LIST_FIELDS, "score_reasons"):
        if d.get(f):
            try:
                d[f] = json.loads(d[f])
            except (TypeError, ValueError):
                d[f] = []
        else:
            d[f] = []
    if d.get("llm"):
        try:
            d["llm"] = json.loads(d["llm"])
        except ValueError:
            d["llm"] = None
    d.pop("raw", None)
    return d


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
