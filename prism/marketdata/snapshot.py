"""Рыночные снапшоты.

Снапшот — неизменяемый именованный набор котировок и таблиц (датасетов) на
момент времени. Хэш содержимого вычисляется по каноническому JSON и
проверяется при каждой загрузке. Исправление данных создаёт новый снапшот
со ссылкой на родителя и журналом изменений — старый не перезаписывается.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from ..core.provenance import DataKind, Provenance

SNAPSHOT_FORMAT_VERSION = "1"


@dataclass(frozen=True)
class Quote:
    """Рыночная котировка.

    ``value`` — число либо структура (например, параметры КБД).
    ``meta`` — атрибуты котировки: срок, экспирация, дельта и т.п.
    """
    id: str
    value: Any
    provenance: Provenance
    unit: str = ""
    bid: float | None = None
    ask: float | None = None
    meta: Mapping[str, Any] = field(default_factory=dict)

    @property
    def spread(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        return self.ask - self.bid

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"value": self.value, "unit": self.unit, "provenance": self.provenance.to_dict()}
        if self.bid is not None:
            d["bid"] = self.bid
        if self.ask is not None:
            d["ask"] = self.ask
        if self.meta:
            d["meta"] = dict(self.meta)
        return d

    @classmethod
    def from_dict(cls, qid: str, d: Mapping[str, Any]) -> "Quote":
        return cls(qid, d["value"], Provenance.from_dict(d["provenance"]), d.get("unit", ""),
                   d.get("bid"), d.get("ask"), MappingProxyType(dict(d.get("meta", {}))))

    def with_value(self, value: Any, note: str = "", kind: DataKind | None = None) -> "Quote":
        prov = self.provenance
        if note or kind:
            prov = Provenance(prov.source, prov.as_of, kind or prov.kind, prov.url,
                              (prov.note + "; " + note).strip("; "), prov.derived_from)
        shift = None
        if isinstance(value, (int, float)) and isinstance(self.value, (int, float)):
            shift = float(value) - float(self.value)
        bid = self.bid + shift if (self.bid is not None and shift is not None) else self.bid
        ask = self.ask + shift if (self.ask is not None and shift is not None) else self.ask
        return Quote(self.id, value, prov, self.unit, bid, ask, self.meta)


@dataclass(frozen=True)
class Dataset:
    """Табличные данные (календарь заседаний ЦБ, история ИПЦ, фиксинги, ряды)."""
    name: str
    data: Any
    provenance: Provenance

    def to_dict(self) -> dict[str, Any]:
        return {"data": self.data, "provenance": self.provenance.to_dict()}

    @classmethod
    def from_dict(cls, name: str, d: Mapping[str, Any]) -> "Dataset":
        return cls(name, d["data"], Provenance.from_dict(d["provenance"]))


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


class MarketSnapshot:
    """Неизменяемый снапшот. Создаётся через :meth:`create` или загрузку."""

    __slots__ = ("_id", "_as_of", "_label", "_parent_id", "_correction", "_meta", "_quotes", "_datasets",
                 "_hash", "_qc")

    def __init__(self, *, id: str, as_of: datetime, label: str, quotes: Mapping[str, Quote],
                 datasets: Mapping[str, Dataset], meta: Mapping[str, Any] | None = None,
                 parent_id: str | None = None, correction: Mapping[str, Any] | None = None,
                 content_hash: str | None = None, qc: list | None = None):
        object.__setattr__(self, "_id", id)
        object.__setattr__(self, "_as_of", as_of)
        object.__setattr__(self, "_label", label)
        object.__setattr__(self, "_parent_id", parent_id)
        object.__setattr__(self, "_correction", MappingProxyType(dict(correction or {})))
        object.__setattr__(self, "_meta", MappingProxyType(dict(meta or {})))
        object.__setattr__(self, "_quotes", MappingProxyType(dict(sorted(quotes.items()))))
        object.__setattr__(self, "_datasets", MappingProxyType(dict(sorted(datasets.items()))))
        h = self.compute_hash()
        if content_hash is not None and content_hash != h:
            raise ValueError(f"хэш снапшота {id} не совпадает: данные повреждены или изменены "
                             f"(ожидался {content_hash[:12]}…, получен {h[:12]}…)")
        object.__setattr__(self, "_hash", h)
        object.__setattr__(self, "_qc", list(qc or []))

    def __setattr__(self, key, value):  # pragma: no cover
        raise AttributeError("снапшот неизменяем: создайте исправленную версию через SnapshotStore.correct")

    # --------------------------------------------------------------- props
    id = property(lambda s: s._id)
    as_of = property(lambda s: s._as_of)
    label = property(lambda s: s._label)
    parent_id = property(lambda s: s._parent_id)
    correction = property(lambda s: s._correction)
    meta = property(lambda s: s._meta)
    quotes = property(lambda s: s._quotes)
    datasets = property(lambda s: s._datasets)
    content_hash = property(lambda s: s._hash)
    qc = property(lambda s: list(s._qc))

    @property
    def is_demo(self) -> bool:
        return bool(self._meta.get("demo"))

    def quote(self, qid: str) -> Quote:
        try:
            return self._quotes[qid]
        except KeyError:
            raise KeyError(f"в снапшоте {self.id} нет котировки {qid}") from None

    def get(self, qid: str) -> Quote | None:
        return self._quotes.get(qid)

    def dataset(self, name: str) -> Dataset:
        try:
            return self._datasets[name]
        except KeyError:
            raise KeyError(f"в снапшоте {self.id} нет датасета {name}") from None

    def find(self, prefix: str) -> list[Quote]:
        return [q for k, q in self._quotes.items() if k.startswith(prefix)]

    # --------------------------------------------------------- serialization
    def content(self) -> dict[str, Any]:
        return {
            "as_of": self._as_of.isoformat(),
            "quotes": {k: q.to_dict() for k, q in self._quotes.items()},
            "datasets": {k: d.to_dict() for k, d in self._datasets.items()},
        }

    def compute_hash(self) -> str:
        return hashlib.sha256(_canonical(self.content()).encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_version": SNAPSHOT_FORMAT_VERSION,
            "id": self._id,
            "label": self._label,
            "parent_id": self._parent_id,
            "correction": dict(self._correction),
            "meta": dict(self._meta),
            "content_hash": self._hash,
            "qc": self._qc,
            **self.content(),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any], verify: bool = True) -> "MarketSnapshot":
        return cls(
            id=d["id"], as_of=datetime.fromisoformat(d["as_of"]), label=d.get("label", ""),
            quotes={k: Quote.from_dict(k, v) for k, v in d["quotes"].items()},
            datasets={k: Dataset.from_dict(k, v) for k, v in d.get("datasets", {}).items()},
            meta=d.get("meta"), parent_id=d.get("parent_id"), correction=d.get("correction"),
            content_hash=d.get("content_hash") if verify else None, qc=d.get("qc"),
        )

    @classmethod
    def create(cls, as_of: datetime, label: str, quotes: Iterable[Quote], datasets: Iterable[Dataset] = (),
               meta: Mapping[str, Any] | None = None, parent_id: str | None = None,
               correction: Mapping[str, Any] | None = None) -> "MarketSnapshot":
        qd = {}
        for q in quotes:
            if q.id in qd:
                raise ValueError(f"дубликат котировки {q.id}")
            qd[q.id] = q
        dd = {d.name: d for d in datasets}
        tmp = cls(id="tmp", as_of=as_of, label=label, quotes=qd, datasets=dd, meta=meta,
                  parent_id=parent_id, correction=correction)
        sid = f"{as_of.strftime('%Y%m%dT%H%M')}-{label}-{tmp.content_hash[:10]}"
        return cls(id=sid, as_of=as_of, label=label, quotes=qd, datasets=dd, meta=meta,
                   parent_id=parent_id, correction=correction)

    def with_qc(self, findings: list) -> "MarketSnapshot":
        """QC-результаты не входят в хэш содержимого — это производные данные."""
        return MarketSnapshot(id=self._id, as_of=self._as_of, label=self._label, quotes=self._quotes,
                              datasets=self._datasets, meta=self._meta, parent_id=self._parent_id,
                              correction=self._correction, content_hash=self._hash, qc=findings)

    def derive(self, changes: Mapping[str, Quote | None], reason: str,
               dataset_changes: Mapping[str, Dataset | None] | None = None, label: str | None = None) -> "MarketSnapshot":
        """Новый снапшот-исправление. ``None`` удаляет котировку."""
        if not reason:
            raise ValueError("исправление снапшота требует указания причины")
        q = dict(self._quotes)
        log = []
        for k, v in changes.items():
            old = q.get(k)
            if v is None:
                q.pop(k, None)
                log.append({"id": k, "old": old.value if old else None, "new": None})
            else:
                q[k] = v
                log.append({"id": k, "old": old.value if old else None, "new": v.value})
        dsets = dict(self._datasets)
        for k, v in (dataset_changes or {}).items():
            if v is None:
                dsets.pop(k, None)
            else:
                dsets[k] = v
            log.append({"dataset": k})
        return MarketSnapshot.create(self._as_of, label or self._label, q.values(), dsets.values(), self._meta,
                                     parent_id=self._id, correction={"reason": reason, "changes": log})

    def __repr__(self) -> str:
        return f"MarketSnapshot({self._id}, quotes={len(self._quotes)}, datasets={len(self._datasets)})"
