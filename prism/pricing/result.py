"""Результат оценки: цена, использованные входы с происхождением, диагностика."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PricingResult:
    trade_id: str
    product: str
    value: float                       # справедливая стоимость (mid) для КЛИЕНТА, валюта отчёта
    currency: str
    engine: str                        # analytic | mc | tree | pde | actuarial
    model: str
    measure: str = "risk_neutral"      # или 'historical' (нет торгуемого хеджа)
    items: list[dict[str, Any]] = field(default_factory=list)
    cashflows: list[dict[str, Any]] = field(default_factory=list)
    mc: dict[str, Any] | None = None
    checks: list[dict[str, Any]] = field(default_factory=list)
    inputs: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    fallback_reason: str | None = None
    exercise: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0

    @property
    def model_based_inputs(self) -> list[dict[str, Any]]:
        from ..core.provenance import DataKind
        out = []
        for u in self.inputs:
            k = DataKind(u["provenance"]["kind"])
            if k.is_model_based or "extrapolated" in u.get("flags", []) or "strike_extrapolated" in u.get("flags", []):
                out.append(u)
        return out

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["model_based_inputs"] = [u["id"] for u in self.model_based_inputs]
        return d
