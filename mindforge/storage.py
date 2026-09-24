"""Хранение данных в SQLite: результаты, настройки, колоды карточек."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from .core import GameResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game TEXT NOT NULL,
    ts REAL NOT NULL,
    day TEXT NOT NULL,
    duration REAL NOT NULL DEFAULT 0,
    score REAL NOT NULL,
    rating REAL NOT NULL,
    level INTEGER NOT NULL,
    accuracy REAL,
    metrics TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_results_game ON results(game, ts);
CREATE INDEX IF NOT EXISTS idx_results_day ON results(day);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deck_id INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    front TEXT NOT NULL,
    back TEXT NOT NULL,
    ease REAL NOT NULL DEFAULT 2.5,
    interval REAL NOT NULL DEFAULT 0,
    reps INTEGER NOT NULL DEFAULT 0,
    lapses INTEGER NOT NULL DEFAULT 0,
    due REAL NOT NULL,
    created REAL NOT NULL,
    last_review REAL
);
CREATE INDEX IF NOT EXISTS idx_cards_deck ON cards(deck_id, due);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER NOT NULL,
    ts REAL NOT NULL,
    day TEXT NOT NULL,
    grade INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reviews_day ON reviews(day);
"""


def default_data_dir() -> Path:
    override = os.environ.get("MINDFORGE_DATA_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "MindForge"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "MindForge"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "MindForge"


def day_of(ts: float) -> str:
    return datetime.fromtimestamp(ts).date().isoformat()


class Storage:
    def __init__(self, path: str | Path | None = None, clock=time.time) -> None:
        if path is None:
            d = default_data_dir()
            d.mkdir(parents=True, exist_ok=True)
            path = d / "mindforge.db"
        self.path = str(path)
        self.clock = clock
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # ------------------------------------------------------------------ время
    def now(self) -> float:
        return self.clock()

    def today(self) -> date:
        return datetime.fromtimestamp(self.now()).date()

    # --------------------------------------------------------------- key/value
    def get(self, key: str, default: Any = None) -> Any:
        row = self.db.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (ValueError, TypeError):
            return default

    def set(self, key: str, value: Any) -> None:
        self.db.execute(
            "INSERT INTO kv(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )
        self.db.commit()

    def delete_prefix(self, prefix: str) -> None:
        self.db.execute("DELETE FROM kv WHERE key LIKE ?", (prefix.replace("%", r"\%") + "%",))
        self.db.commit()

    def keys(self, prefix: str) -> list[str]:
        rows = self.db.execute("SELECT key FROM kv WHERE key LIKE ?", (prefix + "%",)).fetchall()
        return [r["key"] for r in rows]

    # ---------------------------------------------------------------- уровни
    def game_level(self, game: str) -> int:
        return int(self.get(f"level.{game}", 1))

    def set_game_level(self, game: str, level: int) -> None:
        self.set(f"level.{game}", int(level))

    def game_options(self, game: str) -> dict:
        return dict(self.get(f"options.{game}", {}))

    def set_game_options(self, game: str, options: dict) -> None:
        self.set(f"options.{game}", options)

    # ------------------------------------------------------------- результаты
    def add_result(self, r: GameResult) -> int:
        cur = self.db.execute(
            "INSERT INTO results(game, ts, day, duration, score, rating, level, accuracy, metrics) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                r.game,
                r.ts,
                day_of(r.ts),
                r.duration,
                r.score,
                r.rating,
                r.level,
                r.accuracy,
                json.dumps(r.metrics, ensure_ascii=False),
            ),
        )
        self.db.commit()
        return int(cur.lastrowid)

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        try:
            d["metrics"] = json.loads(d.get("metrics") or "{}")
        except ValueError:
            d["metrics"] = {}
        return d

    def results(self, game: str | None = None, limit: int | None = None, since_day: str | None = None) -> list[dict]:
        sql = "SELECT * FROM results"
        cond, args = [], []
        if game:
            cond.append("game = ?")
            args.append(game)
        if since_day:
            cond.append("day >= ?")
            args.append(since_day)
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        sql += " ORDER BY ts DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [self._row_to_dict(r) for r in self.db.execute(sql, args).fetchall()]

    def result_count(self, game: str | None = None) -> int:
        if game:
            row = self.db.execute("SELECT COUNT(*) AS n FROM results WHERE game = ?", (game,)).fetchone()
        else:
            row = self.db.execute("SELECT COUNT(*) AS n FROM results").fetchone()
        return int(row["n"])

    def games_played(self) -> set[str]:
        return {r["game"] for r in self.db.execute("SELECT DISTINCT game FROM results").fetchall()}

    def games_on_day(self, day: str) -> set[str]:
        rows = self.db.execute("SELECT DISTINCT game FROM results WHERE day = ?", (day,)).fetchall()
        return {r["game"] for r in rows}

    def activity_by_day(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for r in self.db.execute(
            "SELECT day, COUNT(*) AS n, SUM(duration) AS dur FROM results GROUP BY day"
        ).fetchall():
            out[r["day"]] = {"sessions": int(r["n"]), "duration": float(r["dur"] or 0)}
        for r in self.db.execute("SELECT day, COUNT(*) AS n FROM reviews GROUP BY day").fetchall():
            entry = out.setdefault(r["day"], {"sessions": 0, "duration": 0.0})
            entry["reviews"] = int(r["n"])
        return out

    def total_duration(self) -> float:
        row = self.db.execute("SELECT SUM(duration) AS d FROM results").fetchone()
        return float(row["d"] or 0)

    def best_result(self, game: str, key: str = "score", lower_is_better: bool = False) -> dict | None:
        order = "ASC" if lower_is_better else "DESC"
        row = self.db.execute(
            f"SELECT * FROM results WHERE game = ? ORDER BY {key} {order}, ts ASC LIMIT 1", (game,)
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def clear_progress(self) -> None:
        self.db.execute("DELETE FROM results")
        self.db.execute("DELETE FROM reviews")
        for prefix in ("level.", "ach.", "plan", "xp"):
            self.db.execute("DELETE FROM kv WHERE key LIKE ?", (prefix + "%",))
        self.db.commit()

    # --------------------------------------------------------------- карточки
    def decks(self) -> list[dict]:
        now = self.now()
        rows = self.db.execute(
            """
            SELECT d.id, d.name, d.created,
                   COUNT(c.id) AS total,
                   SUM(CASE WHEN c.last_review IS NOT NULL AND c.due <= ? THEN 1 ELSE 0 END) AS due,
                   SUM(CASE WHEN c.last_review IS NULL THEN 1 ELSE 0 END) AS new
            FROM decks d LEFT JOIN cards c ON c.deck_id = d.id
            GROUP BY d.id ORDER BY d.created ASC
            """,
            (now,),
        ).fetchall()
        return [
            {**dict(r), "total": int(r["total"] or 0), "due": int(r["due"] or 0), "new": int(r["new"] or 0)}
            for r in rows
        ]

    def create_deck(self, name: str) -> int:
        cur = self.db.execute("INSERT INTO decks(name, created) VALUES(?, ?)", (name.strip() or "Колода", self.now()))
        self.db.commit()
        return int(cur.lastrowid)

    def rename_deck(self, deck_id: int, name: str) -> None:
        self.db.execute("UPDATE decks SET name = ? WHERE id = ?", (name.strip(), deck_id))
        self.db.commit()

    def delete_deck(self, deck_id: int) -> None:
        self.db.execute("DELETE FROM cards WHERE deck_id = ?", (deck_id,))
        self.db.execute("DELETE FROM decks WHERE id = ?", (deck_id,))
        self.db.commit()

    def add_cards(self, deck_id: int, pairs: Iterable[tuple[str, str]]) -> int:
        now = self.now()
        n = 0
        for i, (front, back) in enumerate(pairs):
            front, back = front.strip(), back.strip()
            if not front or not back:
                continue
            # небольшой сдвиг сохраняет порядок добавления при выдаче новых карточек
            self.db.execute(
                "INSERT INTO cards(deck_id, front, back, due, created) VALUES(?, ?, ?, ?, ?)",
                (deck_id, front, back, now + i * 1e-3, now),
            )
            n += 1
        self.db.commit()
        return n

    def cards(self, deck_id: int) -> list[dict]:
        rows = self.db.execute("SELECT * FROM cards WHERE deck_id = ? ORDER BY id", (deck_id,)).fetchall()
        return [dict(r) for r in rows]

    def due_cards(self, deck_id: int, limit: int = 200, new_limit: int = 20) -> list[dict]:
        now = self.now()
        review = self.db.execute(
            "SELECT * FROM cards WHERE deck_id = ? AND last_review IS NOT NULL AND due <= ? ORDER BY due LIMIT ?",
            (deck_id, now, limit),
        ).fetchall()
        new = self.db.execute(
            "SELECT * FROM cards WHERE deck_id = ? AND last_review IS NULL ORDER BY due LIMIT ?",
            (deck_id, new_limit),
        ).fetchall()
        return [dict(r) for r in review] + [dict(r) for r in new]

    def update_card_schedule(self, card: dict, grade: int) -> None:
        now = self.now()
        self.db.execute(
            "UPDATE cards SET ease = ?, interval = ?, reps = ?, lapses = ?, due = ?, last_review = ? WHERE id = ?",
            (card["ease"], card["interval"], card["reps"], card["lapses"], card["due"], now, card["id"]),
        )
        self.db.execute(
            "INSERT INTO reviews(card_id, ts, day, grade) VALUES(?, ?, ?, ?)",
            (card["id"], now, day_of(now), grade),
        )
        self.db.commit()

    def edit_card(self, card_id: int, front: str, back: str) -> None:
        self.db.execute("UPDATE cards SET front = ?, back = ? WHERE id = ?", (front.strip(), back.strip(), card_id))
        self.db.commit()

    def delete_card(self, card_id: int) -> None:
        self.db.execute("DELETE FROM cards WHERE id = ?", (card_id,))
        self.db.commit()

    def review_count(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) AS n FROM reviews").fetchone()["n"])

    def reviews_on_day(self, day: str) -> int:
        return int(self.db.execute("SELECT COUNT(*) AS n FROM reviews WHERE day = ?", (day,)).fetchone()["n"])

    def total_due(self) -> int:
        row = self.db.execute(
            "SELECT COUNT(*) AS n FROM cards WHERE last_review IS NOT NULL AND due <= ?", (self.now(),)
        ).fetchone()
        return int(row["n"])
