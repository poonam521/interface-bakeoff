import pytest

from bakeoff.budget import HARD_CAP_USD, BudgetExceeded, BudgetGuard


def test_cap_cannot_be_raised(tmp_path):
    with pytest.raises(ValueError):
        BudgetGuard(tmp_path / "l.json", HARD_CAP_USD + 0.01)


def test_reserve_settle_and_refuse(tmp_path):
    g = BudgetGuard(tmp_path / "l.json", 1.00)
    g.reserve(0.60)
    with pytest.raises(BudgetExceeded):
        g.reserve(0.50)                  # 0.60 reserved + 0.50 > 1.00
    g.settle(0.60, 0.10)                 # call cost less than its worst case
    g.reserve(0.50)
    g.settle(0.50, 0.50)
    assert g.spent() == pytest.approx(0.60)
    with pytest.raises(BudgetExceeded):
        g.reserve(0.41)


def test_ledger_persists_across_runs(tmp_path):
    BudgetGuard(tmp_path / "l.json", 1.0).settle(0.0, 0.9)
    g = BudgetGuard(tmp_path / "l.json", 1.0)
    assert g.spent() == pytest.approx(0.9)
    with pytest.raises(BudgetExceeded):
        g.reserve(0.2)


def test_clear_reservations_keeps_spend(tmp_path):
    g = BudgetGuard(tmp_path / "l.json", 1.0)
    g.settle(0.0, 0.3)
    g.reserve(0.5)
    g.clear_reservations()
    assert g.spent() == pytest.approx(0.3) and g.remaining() == pytest.approx(0.7)
