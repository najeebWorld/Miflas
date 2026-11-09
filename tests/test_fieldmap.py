from pathlib import Path

import pytest

from mabat.ingest.fieldmap import FieldMap, load_fieldmap

FIELDMAP_PATH = Path(__file__).resolve().parents[1] / "config" / "fieldmap.yaml"

# Official record lengths, spec section 2.5 (page 8).
OFFICIAL_LENGTHS = {
    "A000": 466,
    "SUMMARY": 19,
    "A100": 95,
    "B100": 317,
    "B110": 376,
    "C100": 444,
    "D110": 339,
    "D120": 222,
    "M100": 298,
    "Z900": 110,
}


@pytest.fixture(scope="module")
def fm() -> FieldMap:
    return load_fieldmap(FIELDMAP_PATH)


def test_record_lengths_match_official_table(fm):
    assert {code: fm.length(code) for code in OFFICIAL_LENGTHS} == OFFICIAL_LENGTHS


@pytest.mark.parametrize("code", ["A000", "SUMMARY", "A100", "B100", "B110", "Z900"])
def test_fields_are_contiguous_and_cover_the_record(fm, code):
    expected_start = 1
    for field in fm.fields(code):
        assert field.start == expected_start, f"{code} field {field.id} starts at {field.start}"
        assert field.end >= field.start
        expected_start = field.end + 1
    assert expected_start - 1 == fm.length(code)


def test_field_ids_are_unique_within_a_record(fm):
    for code in ["A000", "SUMMARY", "A100", "B100", "B110", "Z900"]:
        ids = [f.id for f in fm.fields(code)]
        assert len(ids) == len(set(ids))


def test_build_then_slice_round_trips(fm):
    line = fm.build_record(
        "B100",
        {
            "record_number": 7,
            "vat_id": "514000017",
            "account_key": "6200",
            "details": "פרסום ושיווק",
            "date": "20260615",
            "debit_credit": 1,
            "amount": 720000,
        },
    )
    assert len(line) == 317
    values = fm.slice_record("B100", line)
    assert values["record_code"] == "B100"
    assert values["record_number"] == "000000007"
    assert values["account_key"] == "6200"
    assert values["details"] == "פרסום ושיווק"
    assert values["date"] == "20260615"
    assert values["debit_credit"] == "1"
    assert values["amount"] == "+00000000720000"


def test_build_record_formats_negative_amount(fm):
    line = fm.build_record("B100", {"amount": -123456})
    assert fm.slice_record("B100", line)["amount"] == "-00000000123456"


def test_build_record_pads_defaults(fm):
    line = fm.build_record("A100", {"record_number": 1})
    assert len(line) == 95
    assert line.startswith("A100000000001")


def test_build_record_rejects_value_longer_than_field(fm):
    with pytest.raises(ValueError):
        fm.build_record("B100", {"account_key": "X" * 16})


def test_slice_record_requires_fields(fm):
    with pytest.raises(KeyError):
        fm.slice_record("C100", "C100")
