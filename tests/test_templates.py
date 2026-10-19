import pytest

from prism.instruments.describe import describe_trade
from prism.instruments.schema import TRADE_SCHEMA_VERSION, load_trade, migrate
from prism.instruments.templates import build, list_templates
from prism.pricing.engine import price_trade

TEMPLATES = [t["id"] for t in list_templates()]


def test_catalog_covers_all_asset_classes():
    classes = {t["asset_class"] for t in list_templates()}
    assert {"fx", "rate", "inflation", "commodity", "equity", "credit"} <= classes
    assert len(TEMPLATES) >= 50


@pytest.mark.parametrize("tid", TEMPLATES)
def test_template_builds_describes_and_prices(ctx, tid):
    tr = build(tid)
    assert tr.schema_version == TRADE_SCHEMA_VERSION
    d = describe_trade(tr)
    assert d
    r = price_trade(tr, ctx, mc_overrides={"paths": 3000})
    assert r.value == r.value and abs(r.value) < 1e12      # конечная оценка
    assert r.inputs                                         # перечень входов с источником
    if r.engine == "mc":
        assert r.mc["seed"] is not None and r.mc["stderr"] >= 0


def test_termsheet_refs_and_hash():
    tr = build("fx_forward_extra")
    d = tr.model_dump(mode="json")
    d["legs"][0]["components"][0]["strike"] = {"value": 88.1, "ref": "п. 4.1 стр. 3"}
    t2 = load_trade(d)
    assert any("п. 4.1" in v for v in t2.termsheet_refs.values())
    assert t2.content_hash() != tr.content_hash() or t2.termsheet_refs != tr.termsheet_refs


def test_schema_rejects_unknown_fields():
    d = build("fx_forward").model_dump(mode="json")
    d["legs"][0]["unknown_field"] = 1
    with pytest.raises(Exception):
        load_trade(d)


def test_migration_from_1_0():
    d = build("fx_forward").model_dump(mode="json")
    d["schema_version"] = "1.0"
    d["purpose"]["hedge"] = d["purpose"].pop("type")
    m, log = migrate(d)
    assert log == ["1.0 → 1.1"] and m["purpose"]["type"] == "buy_fx"
    assert load_trade(d).purpose.type == "buy_fx"
