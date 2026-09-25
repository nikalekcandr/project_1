import json
from pathlib import Path

import pandas as pd
import pytest

from mmsim.data.moex import MoexISS, fix_volume_units, parse_trades

FIX = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeSession:
    """Отдаёт страницы ISS по параметру start и запоминает запросы."""

    def __init__(self, pages: dict):
        self.pages = pages
        self.calls = []
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        key = (url.rsplit("/", 1)[-1], (params or {}).get("start", 0))
        return FakeResponse(self.pages.get(key) or self.pages[("default", 0)])


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_candles_pagination_and_parsing(tmp_path):
    pages = {
        ("candles.json", 0): load("iss_candles_page1.json"),
        ("candles.json", 2): load("iss_candles_page2.json"),
        ("candles.json", 3): load("iss_empty.json"),
        ("default", 0): load("iss_empty.json"),
    }
    sess = FakeSession(pages)
    iss = MoexISS(cache_dir=tmp_path, session=sess)
    df = iss.candles("SBER", "2025-09-01", "2025-09-01")
    assert list(df.columns) == ["open", "high", "low", "close", "volume", "value"]
    assert len(df) == 3
    assert df.index[0] == pd.Timestamp("2025-09-01 10:00:00")
    assert df["high"].iloc[1] == 300.25
    starts = [c[1]["start"] for c in sess.calls]
    assert starts == [0, 2, 3]
    assert all(c[1]["iss.meta"] == "off" and c[1]["interval"] == 1 for c in sess.calls)
    # второй запрос берётся из кэша
    n_calls = len(sess.calls)
    df2 = iss.candles("SBER", "2025-09-01", "2025-09-01")
    assert len(sess.calls) == n_calls
    pd.testing.assert_frame_equal(df, df2, check_freq=False)


def test_instrument_specs():
    iss = MoexISS(cache_dir=None, session=FakeSession({("SBER.json", 0): load("iss_security_sber.json"), ("default", 0): {}}))
    inst = iss.instrument("SBER")
    assert (inst.lot_size, inst.tick_size, inst.currency) == (10, 0.01, "RUB")
    assert inst.multiplier == 10

    iss = MoexISS(cache_dir=None, session=FakeSession({("SiZ5.json", 0): load("iss_security_si.json"), ("default", 0): {}}))
    si = iss.instrument("SiZ5", engine="futures", market="forts", board="RFUD")
    assert si.tick_size == 1 and si.step_price == 1 and si.multiplier == 1


def test_parse_trades_sides_order_and_lots():
    raw = MoexISS.block(load("iss_trades.json"), "trades")
    tr = parse_trades(raw, lot_size=10)
    assert list(tr["side"]) == [-1, 1, -1]
    assert list(tr["qty"]) == [5, 2, 1]
    assert tr.index[0] == pd.Timestamp("2025-09-25 10:00:00")


def test_volume_units_fix():
    idx = pd.date_range("2025-09-01 10:00", periods=2, freq="60s")
    lots = pd.DataFrame({"open": [300, 300], "high": [300, 300], "low": [300, 300], "close": [300.0, 300.0],
                         "volume": [100.0, 200.0], "value": [300_000.0, 600_000.0]}, index=idx)
    assert fix_volume_units(lots, 10)["volume"].tolist() == [1000.0, 2000.0]
    shares = lots.assign(value=[30_000.0, 60_000.0])
    assert fix_volume_units(shares, 10)["volume"].tolist() == [100.0, 200.0]


def test_unavailable_raises(tmp_path):
    import requests

    from mmsim.data.moex import MoexUnavailable

    class Broken(FakeSession):
        def get(self, *a, **kw):
            raise requests.ConnectionError("blocked")

    iss = MoexISS(cache_dir=tmp_path, session=Broken({}), retries=1)
    with pytest.raises(MoexUnavailable):
        iss.instrument("SBER")
