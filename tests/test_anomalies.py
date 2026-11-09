import pandas as pd
import pytest

from mabat.anomalies.rules import Thresholds, detect, has_history, load_thresholds
from mabat.config import DEFAULT_CONFIG_DIR
from mabat.ingest.parser import parse_export
from mabat.normalize.classify import load_classification
from mabat.normalize.ledger import COLUMNS, build_ledger

T = Thresholds()
TARGET = "2026-04"
PREV = ["2026-01", "2026-02", "2026-03"]


def ledger_of(*rows):
    """rows: (account, category, type, month, amount in agorot)."""
    return pd.DataFrame(
        [(acc, f"כרטיס {acc}", cat, kind, month, amount) for acc, cat, kind, month, amount in rows],
        columns=COLUMNS,
    )


def history(account, category, kind, amounts, current):
    """Three previous months plus the target month for one account."""
    rows = [(account, category, kind, m, a) for m, a in zip(PREV, amounts) if a is not None]
    if current is not None:
        rows.append((account, category, kind, TARGET, current))
    return rows


def anchor():
    """A steady income account so the ledger always spans January..April."""
    return history("4000", "הכנסות", "income", [10_000_000] * 3, 10_000_000)


def run(*groups, thresholds=T):
    rows = [r for g in groups for r in g]
    return detect(ledger_of(*rows), TARGET, thresholds)


def only(findings, rule):
    return [f for f in findings if f.rule == rule]


# ---- thresholds config ----

def test_default_thresholds_file_matches_defaults():
    assert load_thresholds(DEFAULT_CONFIG_DIR / "thresholds.yaml") == Thresholds()


def test_thresholds_convert_shekels_to_agorot():
    t = Thresholds.from_dict({"category_deviation": {"min_diff_ils": 750, "orange_pct": 20}})
    assert t.deviation_min_diff == 75_000
    assert t.deviation_orange_pct == 20
    assert t.deviation_red_pct == 60


def test_unknown_threshold_key_is_rejected():
    with pytest.raises(ValueError):
        Thresholds.from_dict({"category_deviation": {"orange_percent": 20}})


# ---- category deviation ----

BASE = [1_000_000] * 3  # 10,000 ILS a month


@pytest.mark.parametrize(
    "current,expected",
    [
        (1_300_000, None),      # exactly +30%
        (1_300_001, "orange"),
        (1_600_000, "orange"),  # exactly +60%
        (1_600_001, "red"),
        (1_299_999, None),
    ],
)
def test_expense_increase_thresholds(current, expected):
    found = only(run(anchor(), history("6000", "שיווק", "expense", BASE, current)), "category_deviation")
    assert [f.severity for f in found] == ([expected] if expected else [])


def test_deviation_finding_carries_the_numbers():
    f = only(run(anchor(), history("6000", "שיווק", "expense", [900_000, 1_000_000, 1_100_000], 1_800_000)), "category_deviation")[0]
    assert (f.type, f.subject, f.account) == ("expense", "שיווק", None)
    assert (f.amount, f.baseline, f.pct_tenths) == (1_800_000, 1_000_000, 800)


def test_minimum_difference_guard():
    small = [100_000] * 3  # 1,000 ILS a month
    assert only(run(anchor(), history("6000", "שיווק", "expense", small, 150_000)), "category_deviation") == []
    assert len(only(run(anchor(), history("6000", "שיווק", "expense", small, 150_001)), "category_deviation")) == 1


def test_favourable_moves_are_info():
    drop = only(run(anchor(), history("6000", "שיווק", "expense", BASE, 300_000)), "category_deviation")
    assert [(f.severity, f.pct_tenths) for f in drop] == [("info", -700)]
    rise = only(run(history("4000", "הכנסות", "income", [10_000_000] * 3, 17_000_000)), "category_deviation")
    assert [(f.severity, f.pct_tenths) for f in rise] == [("info", 700)]


def test_income_drop_is_unfavourable():
    found = only(run(history("4000", "הכנסות", "income", [10_000_000] * 3, 3_000_000)), "category_deviation")
    assert [f.severity for f in found] == ["red"]


def test_vanished_income_is_a_deviation_not_a_missing_recurring():
    found = run(anchor(), history("4010", "ייעוץ", "income", BASE, None))
    assert [(f.rule, f.severity, f.pct_tenths) for f in found] == [("category_deviation", "red", -1000)]


def test_category_is_summed_across_its_accounts():
    found = run(
        anchor(),
        history("6100", "אחזקה", "expense", [600_000] * 3, 600_000),
        history("6110", "אחזקה", "expense", [400_000] * 3, 800_000),  # category +40%
    )
    assert [(f.rule, f.subject, f.amount) for f in found] == [("category_deviation", "אחזקה", 1_400_000)]


# ---- missing recurring ----

def test_missing_recurring_expense():
    found = run(anchor(), history("6400", "ביטוחים", "expense", [115_000] * 3, None))
    assert [(f.rule, f.severity, f.amount, f.baseline) for f in found] == [("missing_recurring", "orange", 0, 115_000)]


def test_not_recurring_if_one_previous_month_was_empty():
    found = run(anchor(), history("6400", "ביטוחים", "expense", [115_000, None, 115_000], None))
    assert only(found, "missing_recurring") == []


# ---- one-off ----

@pytest.mark.parametrize(
    "current,expected",
    [
        (1_000_000, None),      # exactly 10% of 10,000,000 total expenses
        (1_000_100, "orange"),
        (2_500_000, "orange"),  # exactly 25%
        (2_500_100, "red"),
    ],
)
def test_one_off_expense_share_thresholds(current, expected):
    steady = history("6000", "שכר", "expense", [9_000_000] * 3, 10_000_000 - current)
    found = only(run(anchor(), steady, history("6900", "שיפוצים", "expense", [None] * 3, current)), "one_off")
    assert [f.severity for f in found] == ([expected] if expected else [])


def test_one_off_finding_carries_share():
    steady = history("6000", "שכר", "expense", [8_000_000] * 3, 8_000_000)
    f = only(run(anchor(), steady, history("6900", "שיפוצים", "expense", [None] * 3, 2_000_000)), "one_off")[0]
    assert (f.subject, f.amount, f.baseline, f.pct_tenths) == ("שיפוצים", 2_000_000, None, 200)


def test_one_off_is_not_also_a_deviation():
    steady = history("6000", "שכר", "expense", [8_000_000] * 3, 8_000_000)
    found = run(anchor(), steady, history("6900", "שיפוצים", "expense", [None] * 3, 2_000_000))
    assert [f.rule for f in found] == ["one_off"]


# ---- sign flip ----

@pytest.mark.parametrize("current,flagged", [(-9_999, False), (-10_000, True), (-50_000, True), (5_000, False)])
def test_sign_flip_threshold(current, flagged):
    found = only(run(anchor(), history("6500", "משרדיות", "expense", [None] * 3, current)), "sign_flip")
    assert bool(found) == flagged
    if flagged:
        assert (found[0].severity, found[0].account, found[0].subject, found[0].amount) == (
            "orange", "6500", "כרטיס 6500", current,
        )


# ---- account spike ----

def spike_case(current_6110):
    return (
        anchor(),
        history("6100", "אחזקה", "expense", [2_000_000] * 3, 2_000_000),
        history("6110", "אחזקה", "expense", [100_000] * 3, current_6110),
    )


@pytest.mark.parametrize("current,flagged", [(300_000, False), (300_001, True)])
def test_account_spike_ratio_threshold(current, flagged):
    found = run(*spike_case(current))
    assert [f.rule for f in found] == (["account_spike"] if flagged else [])


def test_account_spike_finding():
    f = run(*spike_case(400_000))[0]
    assert (f.severity, f.account, f.subject, f.amount, f.baseline) == ("info", "6110", "כרטיס 6110", 400_000, 100_000)


def test_account_spike_needs_minimum_difference():
    found = run(
        anchor(),
        history("6100", "אחזקה", "expense", [2_000_000] * 3, 2_000_000),
        history("6110", "אחזקה", "expense", [10_000] * 3, 60_000),  # 6x, but only +500 ILS
    )
    assert found == []


def test_account_spike_suppressed_when_its_category_is_already_flagged():
    found = run(anchor(), history("6110", "אחזקה", "expense", [100_000] * 3, 400_000))
    assert [f.rule for f in found] == ["category_deviation"]


# ---- history ----

def test_without_three_months_of_history_only_sign_flip_runs():
    rows = [
        ("4000", "הכנסות", "income", "2026-03", 10_000_000),
        ("4000", "הכנסות", "income", TARGET, 1_000_000),      # would be a red deviation
        ("6500", "משרדיות", "expense", TARGET, -50_000),
    ]
    ledger = ledger_of(*rows)
    assert not has_history(ledger, TARGET, T)
    assert [f.rule for f in detect(ledger, TARGET, T)] == ["sign_flip"]


def test_has_history_when_data_starts_three_months_before():
    assert has_history(ledger_of(*anchor()), TARGET, T)


# ---- ordering ----

def test_findings_are_sorted_by_severity_then_size():
    found = run(
        anchor(),
        history("6000", "שכר", "expense", [8_000_000] * 3, 8_000_000),
        history("6200", "שיווק", "expense", BASE, 2_000_000),               # red, +100%
        history("6300", "ייעוץ", "expense", BASE, 1_400_000),               # orange, +40%
        history("6400", "ביטוחים", "expense", [115_000] * 3, None),         # orange, missing
        history("6500", "משרדיות", "expense", [20_000] * 3, -15_000),       # orange, sign flip
        history("6700", "נסיעות", "expense", BASE, 300_000),                # info, -70%
    )
    assert [(f.severity, f.subject) for f in found] == [
        ("red", "שיווק"),
        ("orange", "ייעוץ"),
        ("orange", "ביטוחים"),
        ("orange", "כרטיס 6500"),
        ("info", "נסיעות"),
    ]


# ---- the sample ----

@pytest.fixture
def sample_ledger(sample_dir, fm):
    classification = load_classification(DEFAULT_CONFIG_DIR / "classification.yaml")
    return build_ledger(parse_export(sample_dir, fm), classification)


def test_sample_june_has_exactly_the_five_planted_anomalies(sample_ledger):
    found = detect(sample_ledger, "2026-06", T)
    assert [(f.rule, f.severity, f.subject, f.amount, f.baseline, f.pct_tenths) for f in found] == [
        ("category_deviation", "red", "שיווק ופרסום", 720_000, 396_667, 815),
        ("one_off", "orange", "הכנסות אחרות", 1_500_000, None, 132),
        ("missing_recurring", "orange", "ביטוחים", 0, 115_000, None),
        ("sign_flip", "orange", "ציוד משרדי", -15_000, None, None),
        ("account_spike", "info", "חשמל ומים", 290_000, 85_667, None),
    ]
    assert found[3].account == "6500" and found[4].account == "6110"


def test_sample_may_is_clean(sample_ledger):
    assert detect(sample_ledger, "2026-05", T) == []
