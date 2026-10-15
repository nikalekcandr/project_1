"""Аудиторская запись оценки и воспроизведение «бит в бит».

Любая выданная оценка должна точно воспроизводиться спустя год из
сохранённого состояния: версия кода, версии моделей, снапшот рынка с
таймстемпом и хэшем, все параметры сделки, параметры движков, seed.
Числа хранятся и в десятичном виде, и в шестнадцатеричном представлении
IEEE-754 — сравнение при воспроизведении точное.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..version import MODEL_VERSIONS, code_version

RECORD_VERSION = "1"


def _h(x: float | None) -> str | None:
    return None if x is None else float(x).hex()


def _cfg_hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def key_outputs(v) -> dict[str, Any]:
    out = {"value": v.pricing.value}
    if v.xva is not None:
        out["cva"] = v.xva.cva
        out["dva"] = v.xva.dva
    if v.breakdown is not None:
        out["residual"] = v.breakdown.residual
        out["hedge_cost"] = v.breakdown.hedge_cost
    if v.greeks is not None:
        for k, g in v.greeks.get("values", {}).items():
            if isinstance(g, dict) and "delta" in g:
                out[f"delta:{k}"] = g["delta"]
                out[f"vega:{k}"] = g.get("vega_1pt")
    return out


def make_record(v, options, ctx) -> dict[str, Any]:
    outs = key_outputs(v)
    tr = v.trade
    return {
        "record_version": RECORD_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "code": code_version(),
        "models": dict(MODEL_VERSIONS),
        "snapshot": {"id": v.snapshot_id, "content_hash": v.snapshot_hash, "as_of": ctx.snapshot.as_of.isoformat(),
                     "demo": v.snapshot_demo},
        "market_config_hash": _cfg_hash(ctx.config),
        "trade": {"schema_version": tr.schema_version, "hash": tr.content_hash(), "data": tr.model_dump(mode="json")},
        "options": asdict(options),
        "rng": {"mc_seed": tr.model.seed, "mc_paths": tr.model.paths, "antithetic": tr.model.antithetic,
                "xva_seed": 777, "xva_paths": options.xva_paths},
        "engine": {"selected": v.pricing.engine, "model": v.pricing.model, "fallback_reason": v.pricing.fallback_reason},
        "outputs": {k: {"value": val, "hex": _h(val)} for k, val in outs.items()},
    }


def save_record(record: dict, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def replay(record: dict | str | Path, store=None) -> dict[str, Any]:
    """Повторить оценку по записи и сравнить ключевые результаты точно (по битам)."""
    from ..instruments.schema import load_trade
    from ..marketdata.store import SnapshotStore
    from ..valuation import ValuationOptions, run_valuation
    if not isinstance(record, dict):
        record = json.loads(Path(record).read_text(encoding="utf-8"))
    store = store or SnapshotStore()
    snap = store.load(record["snapshot"]["id"])
    if snap.content_hash != record["snapshot"]["content_hash"]:
        return {"ok": False, "reason": "хэш снапшота не совпадает"}
    trade = load_trade(record["trade"]["data"])
    if trade.content_hash() != record["trade"]["hash"]:
        return {"ok": False, "reason": "хэш сделки не совпадает (миграция схемы изменила данные)"}
    opts = ValuationOptions(**record["options"])
    v = run_valuation(trade, snap, opts)
    new = key_outputs(v)
    diffs = []
    for k, ref in record["outputs"].items():
        got = new.get(k)
        same = got is not None and float(got).hex() == ref["hex"]
        if not same:
            diffs.append({"output": k, "recorded": ref["value"], "replayed": got,
                          "abs_diff": None if got is None else abs(got - ref["value"])})
    code_now = code_version()
    code_changed = code_now["source_hash"] != record["code"]["source_hash"]
    models_changed = {k: (record["models"].get(k), vv) for k, vv in MODEL_VERSIONS.items() if record["models"].get(k) != vv}
    return {"ok": not diffs, "bit_exact": not diffs, "differences": diffs, "code_changed": code_changed,
            "models_changed": models_changed, "snapshot_id": snap.id, "checked_outputs": len(record["outputs"])}
