from pathlib import Path

import pytest
import yaml

from prism.cli import main

ROOT = Path(__file__).resolve().parents[1]


def test_cli_end_to_end(tmp_path, capsys):
    st = str(tmp_path / "store")
    main(["--store", st, "snapshot", "demo"])
    main(["--store", st, "snapshot", "list"])
    trade = tmp_path / "t.yaml"
    main(["new", "fx_forward_extra", "--set", "strike=88.5", "-o", str(trade)])
    assert yaml.safe_load(trade.read_text(encoding="utf-8"))["product"]
    rep, rec = tmp_path / "r.html", tmp_path / "rec.json"
    main(["--store", st, "price", str(trade), "--price-only", "--report", str(rep), "--record", str(rec)])
    assert rep.exists() and rec.exists()
    with pytest.raises(SystemExit) as ex:
        main(["--store", st, "replay", str(rec)])
    assert ex.value.code == 0
    assert '"bit_exact": true' in capsys.readouterr().out
    main(["--store", st, "compare"] + [str(p) for p in sorted((ROOT / "examples" / "packages").glob("*.yaml"))])


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from prism.web.app import create_app
    return TestClient(create_app(str(tmp_path_factory.mktemp("webstore"))))


def test_web_flow(client):
    assert client.get("/").status_code == 200
    tpls = client.get("/api/templates").json()
    assert any(t["id"] == "fx_forward_extra" for t in tpls)
    y = client.post("/api/render", json={"template": "fx_forward_extra", "params": {}}).json()["yaml"]
    r = client.post("/api/price", json={"trade_yaml": y, "mode": "price"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["demo"] is True and j["value"] == j["value"]
    assert client.get(f"/api/report/{j['report_id']}").status_code == 200
    assert client.get(f"/api/record/{j['report_id']}").json()["snapshot"]["id"] == j["snapshot"]
    m = client.get("/api/market").json()
    assert m["meetings"] and m["keyrate_svg"].startswith("<svg") or "<svg" in m["keyrate_svg"]


def test_web_rejects_bad_termsheet(client):
    r = client.post("/api/price", json={"trade_yaml": "product: x\nlegs: 1", "mode": "price"})
    assert r.status_code == 400


def test_web_compare(client):
    pk = client.get("/api/examples/packages").json()
    r = client.post("/api/compare", json={"packages": [p["yaml"] for p in pk]})
    assert r.status_code == 200 and r.json()["best"]
