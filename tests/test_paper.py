from mmsim import paper


def test_inventory_strategy_reduces_risk_as_in_paper():
    setup = paper.PaperSetup(n_paths=400, seed=3)
    for gamma in (0.1, 0.5):
        inv_p, inv_q = paper.simulate(gamma, "inventory", setup)
        sym_p, sym_q = paper.simulate(gamma, "symmetric", setup)
        # главный вывод статьи: меньшая дисперсия прибыли и запаса ценой чуть меньшей средней прибыли
        assert inv_p.std() < 0.7 * sym_p.std()
        assert inv_q.std() < 0.6 * sym_q.std()
        assert inv_p.mean() < sym_p.mean() + 3


def test_average_spread_matches_paper_value():
    # в статье для γ = 0.1 средний спред 1.49
    assert round(paper.average_spread(0.1, paper.PaperSetup()), 2) == 1.49
