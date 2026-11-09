import pandas as pd
import pytest

from mabat.compute.pnl import Change, MonthPnL, available_months, compute_pnl
from mabat.config import DEFAULT_CONFIG_DIR
from mabat.ingest.parser import parse_export
from mabat.months import add_months, month_range
from mabat.normalize.classify import load_classification
from mabat.normalize.ledger import COLUMNS, build_ledger


def ledger_of(*rows):
    """rows: (type, month, amount_agorot) -> a minimal normalized ledger."""
    data = [
        (f"acc{i}", f"חשבון {i}", "קטגוריה", kind, month, amount)
        for i, (kind, month, amount) in enumerate(rows)
    ]
    return pd.DataFrame(data, columns=COLUMNS)


@pytest.fixture
def sample_ledger(sample_dir, fm):
    classification = load_classification(DEFAULT_CONFIG_DIR / "classification.yaml")
    return build_ledger(parse_export(sample_dir, fm), classification)


def test_month_arithmetic():
    assert add_months("2026-01", -1) == "2025-12"
    assert add_months("2025-11", 3) == "2026-02"
    assert add_months("2026-06", 0) == "2026-06"
    assert month_range("2025-11", "2026-02") == ["2025-11", "2025-12", "2026-01", "2026-02"]
    assert month_range("2026-03", "2026-02") == []


def test_sample_june(sample_ledger):
    s = compute_pnl(sample_ledger, "2026-06")
    assert s.target == MonthPnL("2026-06", 11_350_000, 7_785_000, 3_565_000, 314)
    assert s.previous == MonthPnL("2026-05", 9_600_000, 7_322_000, 2_278_000, 237)
    assert s.income_change == Change(1_750_000, 182)
    assert s.expenses_change == Change(463_000, 63)
    assert s.profit_change == Change(1_287_000, 565)
    assert [m.month for m in s.series] == [f"2026-0{m}" for m in range(1, 7)]
    assert s.series[-1] == s.target


def test_sample_available_months(sample_ledger):
    assert available_months(sample_ledger) == [f"2026-0{m}" for m in range(1, 7)]


def test_margin_is_undefined_without_income():
    s = compute_pnl(ledger_of(("expense", "2026-03", 50_000)), "2026-03")
    assert s.target == MonthPnL("2026-03", 0, 50_000, -50_000, None)


def test_first_month_has_no_previous():
    s = compute_pnl(ledger_of(("income", "2026-03", 100_000)), "2026-03")
    assert s.previous is None
    assert s.income_change is None and s.expenses_change is None and s.profit_change is None
    assert [m.month for m in s.series] == ["2026-03"]


def test_change_from_zero_has_no_percentage():
    ledger = ledger_of(("income", "2026-02", 100_000), ("income", "2026-03", 100_000), ("expense", "2026-03", 40_000))
    s = compute_pnl(ledger, "2026-03")
    assert s.expenses_change == Change(40_000, None)
    assert s.income_change == Change(0, 0)


def test_change_against_a_loss_uses_the_absolute_base():
    ledger = ledger_of(
        ("income", "2026-02", 100_000), ("expense", "2026-02", 150_000),  # loss of 50,000
        ("income", "2026-03", 100_000), ("expense", "2026-03", 75_000),   # profit of 25,000
    )
    s = compute_pnl(ledger, "2026-03")
    assert s.profit_change == Change(75_000, 1500)


def test_silent_month_inside_the_series_is_zero():
    ledger = ledger_of(("income", "2026-01", 100_000), ("income", "2026-03", 80_000))
    s = compute_pnl(ledger, "2026-03")
    assert s.previous == MonthPnL("2026-02", 0, 0, 0, None)
    assert s.income_change == Change(80_000, None)
    assert [m.income for m in s.series] == [100_000, 0, 80_000]


def test_series_is_capped_at_six_months():
    ledger = ledger_of(*[("income", f"2026-{m:02d}", m * 1000) for m in range(1, 10)])
    s = compute_pnl(ledger, "2026-09")
    assert [m.month for m in s.series] == [f"2026-0{m}" for m in range(4, 10)]


def test_series_crosses_a_year_boundary():
    ledger = ledger_of(("income", "2025-11", 1000), ("income", "2026-02", 2000))
    s = compute_pnl(ledger, "2026-02")
    assert [m.month for m in s.series] == ["2025-11", "2025-12", "2026-01", "2026-02"]


def test_target_month_without_data_is_rejected():
    with pytest.raises(ValueError):
        compute_pnl(ledger_of(("income", "2026-03", 1000)), "2026-08")
