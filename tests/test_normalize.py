from dataclasses import replace
from datetime import date

import pytest

from mabat.config import DEFAULT_CONFIG_DIR
from mabat.errors import ValidationError
from mabat.ingest.parser import parse_export
from mabat.models import Account, Header, Movement, ParsedExport
from mabat.normalize.classify import Classification, load_classification
from mabat.normalize.ledger import build_ledger


@pytest.fixture(scope="module")
def classification() -> Classification:
    return load_classification(DEFAULT_CONFIG_DIR / "classification.yaml")


def account(key, tb_code="", tb_desc="", name=None, code_6111=""):
    return Account(key, name or f"חשבון {key}", tb_code, tb_desc, code_6111, 0, 0, 0)


def move(key, day, amount, debit=True, value_date=None):
    return Movement(1, key, "", day, value_date or day, debit, amount, "", "")


def export_of(accounts, movements):
    header = Header("514000017", "לקוח בדיקה", "", 2026, None, None, "1", "1", 0)
    return ParsedExport(header, accounts, movements, [], [], {}, {}, 0, "cp1255")


def total(ledger, type_, month):
    rows = ledger[(ledger["type"] == type_) & (ledger["month"] == month)]
    return int(rows["amount"].sum())


# ---- on the sample ----

def test_sample_june_totals(sample_dir, fm, classification):
    ledger = build_ledger(parse_export(sample_dir, fm), classification)
    assert total(ledger, "income", "2026-06") == 11_350_000
    assert total(ledger, "expense", "2026-06") == 7_785_000
    assert total(ledger, "income", "2026-05") == 9_600_000
    assert total(ledger, "expense", "2026-05") == 7_322_000


def test_sample_ledger_shape(sample_dir, fm, classification):
    ledger = build_ledger(parse_export(sample_dir, fm), classification)
    assert list(ledger.columns) == ["account", "account_name", "category", "type", "month", "amount"]
    assert set(ledger["type"]) == {"income", "expense"}
    assert not set(ledger["account"]) & {"1000", "1100", "2000", "2100"}
    assert sorted(ledger["month"].unique()) == [f"2026-0{m}" for m in range(1, 7)]

    row = ledger[(ledger["account"] == "6500") & (ledger["month"] == "2026-06")].iloc[0]
    assert int(row["amount"]) == -15_000
    row = ledger[(ledger["account"] == "6110") & (ledger["month"] == "2026-06")].iloc[0]
    assert row["category"] == "שכירות ואחזקה"
    assert row["account_name"] == "חשמל ומים"


def test_value_date_setting_moves_sales_to_the_next_month(sample_dir, fm, classification):
    by_value_date = replace(classification, date_field="value_date")
    ledger = build_ledger(parse_export(sample_dir, fm), by_value_date)
    assert total(ledger, "income", "2026-07") == 11_350_000
    assert total(ledger, "income", "2026-01") == 0


# ---- sign conventions ----

def test_income_is_credit_minus_debit_and_expense_is_debit_minus_credit(classification):
    exp = export_of(
        [account("4000", "100", "הכנסות"), account("6000", "300", "שכר")],
        [
            move("4000", date(2026, 3, 1), 50_000, debit=False),
            move("4000", date(2026, 3, 2), 20_000, debit=True),
            move("6000", date(2026, 3, 3), 70_000, debit=True),
            move("6000", date(2026, 3, 4), 10_000, debit=False),
        ],
    )
    ledger = build_ledger(exp, classification)
    assert total(ledger, "income", "2026-03") == 30_000
    assert total(ledger, "expense", "2026-03") == 60_000


def test_negative_amount_reduces_its_own_side(classification):
    exp = export_of(
        [account("6000", "300", "שכר")],
        [move("6000", date(2026, 3, 3), 70_000), move("6000", date(2026, 3, 9), -5_000)],
    )
    assert total(build_ledger(exp, classification), "expense", "2026-03") == 65_000


# ---- classification rules ----

def rules(*items, date_field="date"):
    return Classification.from_dict({"period": {"date_field": date_field}, "rules": list(items)})


def test_first_matching_rule_wins():
    c = rules(
        {"match": {"account_key": ["6000"]}, "type": "balance_sheet"},
        {"match": {"tb_code_range": {"from": 300, "to": 399}}, "type": "expense"},
    )
    assert c.classify(account("6000", "300", "שכר")) == ("balance_sheet", "שכר")
    assert c.classify(account("6010", "300", "שכר")) == ("expense", "שכר")


def test_category_falls_back_from_rule_to_tb_desc_to_account_name():
    c = rules(
        {"match": {"tb_code": ["A1"]}, "type": "expense", "category": "הנהלה וכלליות"},
        {"match": {"tb_code": ["A2"]}, "type": "expense"},
    )
    assert c.classify(account("1", "A1", "משהו")) == ("expense", "הנהלה וכלליות")
    assert c.classify(account("2", "A2", "תיאור קוד")) == ("expense", "תיאור קוד")
    assert c.classify(account("3", "A2", "", name="שם החשבון")) == ("expense", "שם החשבון")


def test_code_6111_range_rule():
    c = rules({"match": {"code_6111_range": {"from": 1000, "to": 1999}}, "type": "income"})
    assert c.classify(account("1", code_6111="1010"))[0] == "income"
    assert c.classify(account("2", code_6111="3015")) is None
    assert c.classify(account("3", code_6111="")) is None


def test_all_conditions_in_a_rule_must_hold():
    c = rules({"match": {"tb_code": ["300"], "account_key": ["6000"]}, "type": "expense"})
    assert c.classify(account("6000", "300")) is not None
    assert c.classify(account("6010", "300")) is None


def test_non_numeric_tb_code_never_matches_a_range():
    c = rules({"match": {"tb_code_range": {"from": 100, "to": 199}}, "type": "income"})
    assert c.classify(account("1", "1A0")) is None


def test_bad_config_is_rejected():
    with pytest.raises(ValueError):
        rules({"match": {"tb_code": ["1"]}, "type": "revenue"})
    with pytest.raises(ValueError):
        rules({"match": {"colour": ["red"]}, "type": "income"})
    with pytest.raises(ValueError):
        rules({"match": {}, "type": "income"})
    with pytest.raises(ValueError):
        rules(date_field="entry_date")


# ---- stops ----

def test_unclassified_account_with_movements_stops(classification):
    exp = export_of(
        [account("9999", "900", "לא ידוע", name="חשבון מסתורי")],
        [move("9999", date(2026, 3, 1), 100)],
    )
    with pytest.raises(ValidationError) as err:
        build_ledger(exp, classification)
    assert "9999" in err.value.message and "חשבון מסתורי" in err.value.message


def test_unclassified_account_without_movements_is_ignored(classification):
    exp = export_of(
        [account("9999", "900"), account("6000", "300", "שכר")],
        [move("6000", date(2026, 3, 1), 100)],
    )
    assert len(build_ledger(exp, classification)) == 1


def test_missing_value_date_stops_when_it_is_the_period_field(classification):
    by_value_date = replace(classification, date_field="value_date")
    m = Movement(42, "6000", "", date(2026, 3, 1), None, True, 100, "", "")
    with pytest.raises(ValidationError) as err:
        build_ledger(export_of([account("6000", "300")], [m]), by_value_date)
    assert err.value.line == 42
