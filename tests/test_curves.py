import numpy as np
import pytest

from prism.curves.cbr import load_meetings
from prism.curves.kbd import kbd_g


@pytest.mark.parametrize("cid", ["RUB.KEYRATE", "RUB.RUSFAR", "RUB.RUONIA", "USD.SOFR", "EUR.ESTR", "CNY.REPO", "CNH.HIBOR"])
def test_curve_repricing_within_tolerance(ctx, cid):
    rep = ctx.curve_fit_report(cid)
    assert rep["max_error_bp"] <= 0.5
    c = ctx.curve(cid)
    df = c.df(np.linspace(0.01, 20, 300))
    assert np.all(df > 0) and np.all(np.diff(df) < 0)


def test_step_short_end_constant_between_meetings(ctx):
    c = ctx.curve("RUB.KEYRATE")
    ms = [m for m in load_meetings(ctx.snapshot.dataset("cbr_meetings").data) if m.effective > ctx.ref_date]
    t1, t2 = c.time(ms[0].effective), c.time(ms[1].effective)
    pts = np.linspace(t1 + 0.002, t2 - 0.002, 7)
    f = c.inst_fwd(pts)
    assert np.ptp(f) < 1e-10                       # плоский форвард между заседаниями
    jump = c.inst_fwd(t1 + 1e-4) - c.inst_fwd(t1 - 1e-4)
    assert abs(jump) > 1e-3                        # скачок — на дату вступления в силу


def test_meeting_path_recovers_cut(ctx):
    mp = ctx.meeting_path()
    assert mp[0]["expected_change_bp"] == pytest.approx(-50, abs=2)
    assert sum(o["probability"] for o in mp[0]["outcomes"]) == pytest.approx(1.0)


def test_kbd_formula():
    p = {"B1": 1000.0, "B2": 0.0, "B3": 0.0, "T1": 1.0}
    assert kbd_g(5.0, p) == pytest.approx(1000.0)


def test_fx_forward_and_cip(ctx):
    fx = ctx.fx("USDRUB")
    q = ctx.snapshot.quote("FX.USDRUB.FWD.1Y")
    d = fx.pillar_dates[[i for i, _ in enumerate(fx.pillar_dates)][7]]
    assert fx.forward(d) == pytest.approx(fx.spot + q.value, rel=1e-12)
    cip = ctx.cip_table("USDRUB")
    assert all(r["basis_bp"] < 0 for r in cip)     # имплицированная ставка ниже onshore (заложено в демо)


def test_credit_proxy_hierarchy(ctx):
    assert ctx.credit_curve("CLIENT_METAL").method_rank == 1     # собственные облигации
    assert ctx.credit_curve("CLIENT_IMPORT").method_rank == 2    # сопоставимые эмитенты
    agro = ctx.credit_curve("CLIENT_AGRO")
    assert agro.method_rank == 3 and agro.measure == "physical"  # рейтинг → статистика


def test_cpi_seasonality_and_publication(ctx):
    cpi = ctx.cpi()
    assert abs(cpi.seasonality.sum()) < 1e-12
    assert cpi.index(cpi.base_month)[1].startswith("опубликовано")
    from prism.curves.inflation import add_m
    v12, kind = cpi.index(add_m(cpi.base_month, 12))
    assert kind == "прогноз"
    assert v12 / cpi.base_index - 1 == pytest.approx(cpi.pillar_rates[0], abs=1e-6)   # годовая точка точно
