import warnings

import pytest

warnings.filterwarnings("ignore", category=RuntimeWarning)


@pytest.fixture(scope="session")
def snap():
    from prism.marketdata.demo import build_demo_snapshot
    return build_demo_snapshot()


@pytest.fixture(scope="session")
def ctx(snap):
    from prism.marketdata.context import MarketContext
    return MarketContext(snap)


@pytest.fixture(scope="session")
def flat_ctx(ctx):
    from prism.validation.suite import flat_smile_context
    return flat_smile_context(ctx)


def price(trade, ctx, **kw):
    from prism.pricing.engine import price_trade
    return price_trade(trade, ctx, **kw)
