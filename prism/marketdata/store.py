"""Хранилище снапшотов: только добавление, без перезаписи.

Каждый снапшот — отдельный JSON-файл ``<id>.json``; файл создаётся в режиме
эксклюзивного создания и помечается только для чтения. Идентификатор
содержит префикс хэша содержимого, загрузка проверяет хэш целиком.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Iterator

from .snapshot import MarketSnapshot

DEFAULT_STORE = Path(os.environ.get("PRISM_SNAPSHOT_DIR", Path(__file__).resolve().parents[2] / "snapshots"))


class SnapshotStore:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root else DEFAULT_STORE
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, sid: str) -> Path:
        return self.root / f"{sid}.json"

    def save(self, snap: MarketSnapshot) -> Path:
        p = self.path(snap.id)
        payload = json.dumps(snap.to_dict(), ensure_ascii=False, indent=1, sort_keys=False)
        if p.exists():
            existing = json.loads(p.read_text(encoding="utf-8"))
            if existing.get("content_hash") == snap.content_hash:
                return p  # идемпотентно: тот же снапшот уже сохранён
            raise FileExistsError(f"снапшот {snap.id} уже существует с другим содержимым — перезапись запрещена")
        with open(p, "x", encoding="utf-8") as f:
            f.write(payload)
        try:
            os.chmod(p, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        except OSError:  # pragma: no cover
            pass
        return p

    def load(self, sid_or_path: str | Path) -> MarketSnapshot:
        p = Path(sid_or_path)
        if not p.suffix == ".json" or not p.exists():
            p = self.path(str(sid_or_path))
        if not p.exists():
            matches = [x for x in self.root.glob(f"{sid_or_path}*.json")]
            if len(matches) == 1:
                p = matches[0]
            else:
                raise FileNotFoundError(f"снапшот {sid_or_path} не найден в {self.root}")
        return MarketSnapshot.from_dict(json.loads(p.read_text(encoding="utf-8")), verify=True)

    def ids(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.json"))

    def __iter__(self) -> Iterator[MarketSnapshot]:
        for sid in self.ids():
            yield self.load(sid)

    def latest(self, label: str | None = None) -> MarketSnapshot:
        cands = [s for s in self.ids() if label is None or f"-{label}-" in s]
        if not cands:
            raise FileNotFoundError("в хранилище нет снапшотов")
        snaps = [self.load(s) for s in cands]
        snaps.sort(key=lambda s: (s.as_of, s.id))
        return snaps[-1]

    def lineage(self, sid: str) -> list[MarketSnapshot]:
        """Цепочка исправлений от исходного снапшота до указанного."""
        out = []
        cur: str | None = sid
        while cur:
            s = self.load(cur)
            out.append(s)
            cur = s.parent_id
        return list(reversed(out))

    def correct(self, sid: str, changes, reason: str, dataset_changes=None) -> MarketSnapshot:
        base = self.load(sid)
        new = base.derive(changes, reason, dataset_changes)
        self.save(new)
        return new
