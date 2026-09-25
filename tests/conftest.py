import pytest

from mmsim.data.synthetic import SyntheticConfig, generate


@pytest.fixture(scope="session")
def synth():
    """Небольшой синтетический набор: 4 дня, ~20 тыс. сделок в день."""
    return generate(SyntheticConfig(days=4, trades_per_second=0.7, seed=11))
