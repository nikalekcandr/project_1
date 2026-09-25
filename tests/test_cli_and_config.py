from pathlib import Path

import pandas as pd
import pytest

from mmsim.cli import main
from mmsim.config import SimConfig
from mmsim.data.csv_loader import load_candles_csv, load_trades_csv

ROOT = Path(__file__).resolve().parents[1]


def test_example_configs_parse():
    for path in sorted((ROOT / "configs").glob("*.toml")):
        cfg = SimConfig.load(path)
        assert cfg.strategy.gamma > 0


def test_unknown_key_rejected():
    with pytest.raises(ValueError):
        SimConfig.from_dict({"strategy": {"gama": 0.1}})
    cfg = SimConfig()
    cfg.set("execution.max_inventory", "7")
    cfg.set("calibration.k", "12.5")
    cfg.set("execution.post_only", "false")
    assert cfg.execution.max_inventory == 7 and cfg.calibration.k == 12.5 and cfg.execution.post_only is False


def test_cli_run_compare_sweep(tmp_path):
    common = ["--source", "synthetic", "-s", "data.synthetic_days=3", "-s", "calibration.window_days=1"]
    assert main(["run", *common, "--out", str(tmp_path / "run")]) == 0
    assert (tmp_path / "run" / "report.html").exists()
    assert (tmp_path / "run" / "fills.csv").exists()
    assert main(["compare", *common, "--out", str(tmp_path / "cmp"), "as", "glft:gamma=0.05", "fixed:half_spread_ticks=8"]) == 0
    assert (tmp_path / "cmp" / "compare.html").exists()
    assert main(["sweep", *common, "--out", str(tmp_path / "sw"), "--values", "0.005,0.05"]) == 0
    assert len(pd.read_csv(tmp_path / "sw" / "sweep.csv")) == 2
    assert main(["calibrate", *common, "--out", str(tmp_path / "cal")]) == 0
    assert (tmp_path / "cal" / "intensity.png").exists()
    assert main(["paper", "--paths", "50", "--out", str(tmp_path / "paper")]) == 0


def test_finam_csv(tmp_path):
    candles = tmp_path / "SBER_1min.csv"
    candles.write_text(
        "<TICKER>,<PER>,<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>\n"
        "SBER,1,20250901,100000,300.00,300.10,299.90,300.05,12000\n"
        "SBER,1,20250901,100100,300.05,300.20,300.00,300.15,8000\n",
        encoding="utf-8",
    )
    df = load_candles_csv(candles)
    assert df.index[1] == pd.Timestamp("2025-09-01 10:01:00")
    assert df["volume"].tolist() == [12000, 8000]
    ticks = tmp_path / "SBER_ticks.csv"
    ticks.write_text(
        "<TICKER>;<PER>;<DATE>;<TIME>;<LAST>;<VOL>;<ID>;<OPER>\n"
        "SBER;0;01/09/25;10:00:00;300.00;10;1;S\n"
        "SBER;0;01/09/25;10:00:01;300.01;5;2;B\n",
        encoding="utf-8",
    )
    tr = load_trades_csv(ticks, qty_in_shares=True, lot_size=10)
    assert tr["side"].tolist() == [-1, 1]
    assert tr["qty"].tolist() == [1.0, 0.5]
