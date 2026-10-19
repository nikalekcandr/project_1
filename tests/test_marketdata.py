import json
from datetime import datetime

import pytest

from prism.marketdata.qc import run_qc
from prism.marketdata.snapshot import MarketSnapshot
from prism.marketdata.store import SnapshotStore


def test_snapshot_hash_and_immutability(snap):
    assert snap.content_hash == snap.compute_hash()
    with pytest.raises(AttributeError):
        snap.label = "x"
    d = snap.to_dict()
    again = MarketSnapshot.from_dict(json.loads(json.dumps(d)))
    assert again.content_hash == snap.content_hash


def test_tampered_snapshot_rejected(snap):
    d = json.loads(json.dumps(snap.to_dict()))
    d["quotes"]["RATE.RUB.KEYRATE"]["value"] = 0.2
    with pytest.raises(ValueError, match="хэш"):
        MarketSnapshot.from_dict(d)


def test_store_append_only_and_corrections(tmp_path, snap):
    st = SnapshotStore(tmp_path)
    st.save(snap)
    st.save(snap)   # идемпотентно
    q = snap.quote("FX.USDRUB.SPOT")
    new = st.correct(snap.id, {q.id: q.with_value(83.0)}, "ошибка ввода")
    assert new.id != snap.id and new.parent_id == snap.id
    assert st.load(snap.id).quote("FX.USDRUB.SPOT").value == q.value   # исходный не изменён
    assert [s.id for s in st.lineage(new.id)] == [snap.id, new.id]
    with pytest.raises(ValueError):
        snap.derive({}, "")


def test_qc_outliers_and_demo_flag(snap):
    from prism.marketdata.demo import build_demo_snapshot
    from prism.marketdata.sources import MSK
    prev = build_demo_snapshot(datetime(2026, 10, 14, 18, 45, tzinfo=MSK), day_shift=1)
    q = snap.quote("FX.USDRUB.SPOT")
    bad = snap.derive({q.id: q.with_value(q.value * 1.2)}, "тест выброса")
    f = run_qc(bad, prev)
    assert any(x.check == "outlier" and x.quote_id == "FX.USDRUB.SPOT" for x in f)
    assert any(x.quote_id == "*" for x in run_qc(snap))


def test_moex_and_cbr_parsers():
    from prism.marketdata.sources.cbr import parse_xml_daily
    from prism.marketdata.sources.moex import parse_zcyc_params
    xml = ('<?xml version="1.0" encoding="windows-1251"?><ValCurs Date="16.10.2026" name="Foreign Currency Market">'
           '<Valute ID="R01235"><NumCode>840</NumCode><CharCode>USD</CharCode><Nominal>1</Nominal><Name>USD</Name>'
           '<Value>82,4170</Value></Valute><Valute ID="R01375"><NumCode>156</NumCode><CharCode>CNY</CharCode><Nominal>10</Nominal>'
           '<Name>CNY</Name><Value>115,1000</Value></Valute></ValCurs>').encode("cp1251")
    qs = {q.id: q for q in parse_xml_daily(xml)}
    assert qs["FX.USDRUB.FIX.CBR"].value == pytest.approx(82.417)
    assert qs["FX.CNYRUB.FIX.CBR"].value == pytest.approx(11.51)
    payload = {"params": {"columns": ["tradedate", "tradetime", "B1", "B2", "B3", "T1"] + [f"G{i}" for i in range(1, 10)],
                          "data": [["2026-10-15", "18:44:00", 1350.0, 180.0, -120.0, 2.0] + [0.0] * 9]}}
    q = parse_zcyc_params(payload)
    assert q.value["B1"] == 1350.0 and q.provenance.as_of.hour == 18


def test_public_sources_only():
    from prism.marketdata.sources import fetch
    with pytest.raises(PermissionError):
        fetch("https://example.com/prices")
