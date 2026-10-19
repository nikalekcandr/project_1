import json
from pathlib import Path

import pytest
import yaml

from prism.audit.record import replay, save_record
from prism.instruments.schema import load_trade
from prism.instruments.templates import build
from prism.marketdata.store import SnapshotStore
from prism.packages.ifrs9 import assess_embedded
from prism.packages.package import compare_offers, load_package
from prism.reporting.html import render_html
from prism.valuation import ValuationOptions, run_valuation

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def store(tmp_path_factory, snap):
    st = SnapshotStore(tmp_path_factory.mktemp("snaps"))
    st.save(snap)
    return st


@pytest.fixture(scope="module")
def val(snap):
    return run_valuation(build("fx_forward_extra"), snap, ValuationOptions.fast())


def test_full_valuation_blocks(val):
    assert not val.errors, val.errors
    for blk in ("greeks", "stresses", "alternatives", "profile", "xva", "breakdown", "nrd"):
        assert getattr(val, blk) is not None, blk
    labels = {s["label"] for s in val.stresses}
    assert any("ключев" in l.lower() for l in labels) and any("курс" in l.lower() or "рубл" in l.lower() for l in labels)
    assert val.profile.zones                       # зоны «хуже, чем без хеджа» / «защита отключена»


def test_breakdown_reconciles(val):
    """Передаваемая стоимость = премия − справедливая стоимость для клиента = сумма всех компонент разложения."""
    b = val.breakdown
    assert b.transfer == pytest.approx(b.premium_pv - b.fair_value_client, rel=1e-12)
    assert sum(w["value"] for w in b.waterfall()) == pytest.approx(b.transfer, rel=1e-9, abs=1e-6)
    assert b.hedge_cost >= 0 and b.model_reserve >= 0
    assert b.fair_value_client == val.pricing.value


def test_report_html_contains_required_sections(val):
    html = render_html(val)
    for s in ("Разложение", "Ванильн", "Стресс", "CVA", "НРД", "Аудит", "ДЕМО"):
        assert s.lower() in html.lower(), s
    assert "<script" in html and "http" not in html.split("<style")[0].lower().replace("http-equiv", "")


def test_replay_bit_exact(snap, store, tmp_path):
    opts = ValuationOptions.price_only()
    opts.greeks = True
    opts.greeks_full = False
    opts.greek_mc_paths = 3000
    v = run_valuation(build("fx_tarf"), snap, opts)
    p = save_record(v.record, tmp_path / "rec.json")
    r = replay(p, store)
    assert r["ok"] and r["bit_exact"] and r["checked_outputs"] >= 2


def test_replay_detects_tampered_snapshot(snap, store, tmp_path):
    v = run_valuation(build("fx_forward"), snap, ValuationOptions.price_only())
    rec = json.loads(json.dumps(v.record))
    rec["snapshot"]["content_hash"] = "0" * 64
    assert not replay(rec, store)["ok"]


def test_package_comparison(ctx):
    pk = [load_package(yaml.safe_load(p.read_text(encoding="utf-8"))) for p in sorted((ROOT / "examples" / "packages").glob("*.yaml"))]
    res = compare_offers(pk, ctx)
    rates = {r["bank"]: r["effective_rate"] for r in res["table"]}
    assert len(rates) == 3 and all(0.05 < x < 0.4 for x in rates.values())
    assert res["best"] in {r["package"] for r in res["table"]}


def test_ifrs9_embedded_assessment():
    tr = build("structured_deposit")
    a = assess_embedded(tr, "financial_liability", fair_value=1.0, model_based_inputs=["VOL.USDRUB"], engine="analytic").to_dict()
    assert a["separate"] and "4.3.3" in a["paragraphs"] and a["fair_value_level"] == 3
    a2 = assess_embedded(tr, "financial_asset", fair_value=1.0, model_based_inputs=[], engine="analytic").to_dict()
    assert not a2["separate"] and "SPPI" in " ".join(a2["rationale"]) and a2["fair_value_level"] == 2
    cap = build("loan_floor")
    a3 = assess_embedded(cap, "financial_liability", fair_value=1.0, model_based_inputs=[]).to_dict()
    assert a3["judgement_required"]          # без рыночной ставки на дату заключения вывод не делается молча


@pytest.mark.parametrize("tid,zone,text", [
    ("fx_collar", "corridor", "коридор"),
    ("fx_forward_extra", "worse_than_unhedged", "касания барьера"),
    ("fx_leveraged_forward", "worse_than_unhedged", "плеча"),
    ("barrier_cap", "protection_off", "перестаёт защищать"),
])
def test_hedge_profile_zones_and_reasons(snap, tid, zone, text):
    o = ValuationOptions.price_only()
    o.alternatives = o.profile = True
    v = run_valuation(build(tid), snap, o)
    assert not v.errors, v.errors
    assert zone in {z["type"] for z in v.profile.zones}
    assert any(text in s for s in v.profile.summary), v.profile.summary


def test_colva_by_collateral_regime(ctx):
    from prism.xva.engine import XVAConfig, compute_xva
    base = build("irs_keyrate").model_dump(mode="json")
    out = {}
    for regime in ("none", "one_way_client", "two_way"):
        d = dict(base, collateral={"regime": regime})
        out[regime] = compute_xva([load_trade(d)], ctx, XVAConfig(paths=1000))
    assert out["none"].colva == 0.0 and out["two_way"].colva == pytest.approx(0.0, abs=1e-6)
    assert out["one_way_client"].colva < 0          # обеспечение по RUSFAR дешевле дисконтирования по КС
    assert out["one_way_client"].cva < out["none"].cva
