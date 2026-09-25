"""Пример использования mmsim из Python.

    python examples/quickstart.py            # синтетика (работает офлайн)
    python examples/quickstart.py --moex     # реальные минутные свечи SBER с MOEX ISS
"""

import sys

from mmsim import (
    AvellanedaStoikov,
    CalibrationConfig,
    ExecutionConfig,
    GLFT,
    MoexISS,
    generate,
    run_backtest,
)
from mmsim.metrics import format_metrics, metrics_frame
from mmsim.report import write_compare_report

if "--moex" in sys.argv:
    iss = MoexISS(cache_dir="data/cache")
    # неделя истории до start нужна для walk-forward калибровки
    data = iss.load("SBER", "2025-09-01", "2025-09-30", interval=1)
    trade_start = "2025-09-08"
else:
    data = generate(days=10)
    trade_start = None

print(data.summary(), "\n")

execution = ExecutionConfig(
    fill_model="candle",  # исполнение по свечам: проторговали насквозь / касание с вероятностью
    touch_fill_prob=0.3,
    maker_fee_bps=1.0,
    taker_fee_bps=3.0,
    max_inventory=10,
)
calibration = CalibrationConfig(mode="walk_forward", window_days=3)

results = []
for strategy in (
    AvellanedaStoikov(gamma=0.01),
    AvellanedaStoikov(gamma=0.01, inventory_skew=False),
    GLFT(gamma=0.05),
):
    res = run_backtest(data, strategy, execution, calibration, trade_start=trade_start)
    results.append(res)
    print(res.strategy)
    print(format_metrics(res.metrics), "\n")

print(metrics_frame(results).round(2).to_string())
print("\nОтчёт:", write_compare_report(results, "reports/quickstart"))
