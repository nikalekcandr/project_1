"""Происхождение данных (data lineage).

Каждый рыночный вход на любом слое несёт объект :class:`Provenance`:
источник, ссылку, время снятия котировки и *вид* данных. Вид отделяет
наблюдаемые рыночные числа от интерполированных, экстраполированных,
исторических и модельных — это различие обязано доходить до отчёта.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Iterable


class DataKind(str, Enum):
    MARKET = "market"              # прямое рыночное наблюдение (котировка, фиксинг)
    DERIVED = "derived"            # детерминированно выведено из рыночных (бутстрэп-узел)
    INTERPOLATED = "interpolated"  # интерполяция между рыночными точками
    EXTRAPOLATED = "extrapolated"  # экстраполяция за последний рыночный узел
    HISTORICAL = "historical"      # историческая оценка (фоллбэк при отсутствии рынка)
    MODEL = "model"                # модельное допущение / параметр
    TERMSHEET = "termsheet"        # параметр сделки из термшита
    DEMO = "demo"                  # иллюстративные данные — не для реальной оценки

    @property
    def is_model_based(self) -> bool:
        """Вход опирается не на рынок: читатель отчёта обязан это видеть."""
        return self in (DataKind.EXTRAPOLATED, DataKind.HISTORICAL, DataKind.MODEL, DataKind.DEMO)

    @property
    def label_ru(self) -> str:
        return _KIND_RU[self]


_KIND_RU = {
    DataKind.MARKET: "рыночная котировка",
    DataKind.DERIVED: "выведено из рынка",
    DataKind.INTERPOLATED: "интерполяция",
    DataKind.EXTRAPOLATED: "экстраполяция",
    DataKind.HISTORICAL: "историческая оценка",
    DataKind.MODEL: "модельное допущение",
    DataKind.TERMSHEET: "термшит",
    DataKind.DEMO: "ДЕМО-данные",
}

# Приоритет «худшего» вида при агрегации: если хоть один вход модельный,
# производный объект наследует этот признак.
_SEVERITY = {
    DataKind.MARKET: 0,
    DataKind.TERMSHEET: 0,
    DataKind.DERIVED: 1,
    DataKind.INTERPOLATED: 2,
    DataKind.EXTRAPOLATED: 3,
    DataKind.HISTORICAL: 4,
    DataKind.MODEL: 5,
    DataKind.DEMO: 6,
}


def worst_kind(kinds: Iterable[DataKind]) -> DataKind:
    kinds = list(kinds)
    if not kinds:
        return DataKind.MARKET
    return max(kinds, key=lambda k: _SEVERITY[k])


@dataclass(frozen=True)
class Provenance:
    source: str
    as_of: datetime | None
    kind: DataKind = DataKind.MARKET
    url: str | None = None
    note: str = ""
    derived_from: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind.value
        d["as_of"] = self.as_of.isoformat() if self.as_of else None
        d["derived_from"] = list(self.derived_from)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Provenance":
        return cls(
            source=d["source"],
            as_of=datetime.fromisoformat(d["as_of"]) if d.get("as_of") else None,
            kind=DataKind(d.get("kind", "market")),
            url=d.get("url"),
            note=d.get("note", ""),
            derived_from=tuple(d.get("derived_from", ())),
        )

    def with_kind(self, kind: DataKind, note: str = "") -> "Provenance":
        return Provenance(self.source, self.as_of, kind, self.url, note or self.note, self.derived_from)


@dataclass
class UsedInput:
    """Запись об использованном входе в конкретном расчёте."""
    id: str
    value: Any
    provenance: Provenance
    role: str = ""          # для чего использован (например, «дисконтирование RUB»)
    flags: tuple[str, ...] = ()

    @property
    def kind(self) -> DataKind:
        return self.provenance.kind

    def to_dict(self) -> dict[str, Any]:
        v = self.value
        if hasattr(v, "tolist"):
            v = v.tolist()
        return {
            "id": self.id,
            "value": v,
            "role": self.role,
            "flags": list(self.flags),
            "provenance": self.provenance.to_dict(),
        }


@dataclass
class InputTracker:
    """Собирает перечень фактически использованных входов при оценке.

    Движки не ходят за данными сами: они получают контекст рынка, а контекст
    регистрирует каждое обращение здесь. Итоговый перечень попадает в отчёт.
    """
    used: dict[str, UsedInput] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def record(self, inp: UsedInput) -> None:
        prev = self.used.get(inp.id)
        if prev is None:
            self.used[inp.id] = inp
        else:
            flags = tuple(sorted(set(prev.flags) | set(inp.flags)))
            role = prev.role if inp.role in prev.role else (prev.role + "; " + inp.role).strip("; ")
            self.used[inp.id] = UsedInput(prev.id, prev.value, prev.provenance, role, flags)

    def warn(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)

    def merge(self, other: "InputTracker") -> None:
        for v in other.used.values():
            self.record(v)
        for w in other.warnings:
            self.warn(w)

    @property
    def model_based(self) -> list[UsedInput]:
        return [u for u in self.used.values() if u.kind.is_model_based or "extrapolated" in u.flags]

    def to_list(self) -> list[dict[str, Any]]:
        return [self.used[k].to_dict() for k in sorted(self.used)]
