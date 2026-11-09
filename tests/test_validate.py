import pytest

from mabat.errors import ValidationError
from mabat.ingest.parser import parse_export
from mabat.ingest.validate import validate_export
from tests.conftest import find_line, patch_line, read_lines, write_lines


def _validate(folder, fm):
    return validate_export(parse_export(folder, fm))


def _edit(folder, name, fm, fn):
    path = folder / name
    lines = read_lines(path)
    fn(lines)
    write_lines(path, lines)


def test_clean_sample_has_no_warnings(sample_dir, fm):
    assert _validate(sample_dir, fm) == []


def test_deleted_movement_stops(sample_dir, fm):
    def drop_last_b100(lines):
        i = max(i for i, l in enumerate(lines) if fm.record_code(l) == "B100")
        del lines[i]

    _edit(sample_dir, "BKMVDATA.TXT", fm, drop_last_b100)
    with pytest.raises(ValidationError):
        _validate(sample_dir, fm)


def test_ini_count_per_record_type_must_match(sample_dir, fm):
    def change_count(lines):
        i = next(i for i, l in enumerate(lines) if l.startswith("B100"))
        lines[i] = patch_line(fm, "SUMMARY", lines[i], record_count=207)

    _edit(sample_dir, "INI.TXT", fm, change_count)
    with pytest.raises(ValidationError, match="207 רשומות B100"):
        _validate(sample_dir, fm)


def test_record_type_missing_from_ini_stops(sample_dir, fm):
    _edit(sample_dir, "INI.TXT", fm, lambda lines: lines.pop(2))  # the B110 summary line
    with pytest.raises(ValidationError, match="B110"):
        _validate(sample_dir, fm)


def test_ini_total_mismatch_stops(sample_dir, fm):
    def change_total(lines):
        lines[0] = patch_line(fm, "A000", lines[0], total_records=230)

    _edit(sample_dir, "INI.TXT", fm, change_total)
    with pytest.raises(ValidationError, match="1002"):
        _validate(sample_dir, fm)


def test_closing_total_mismatch_stops(sample_dir, fm):
    def change_total(lines):
        lines[-1] = patch_line(fm, "Z900", lines[-1], total_records=228)

    _edit(sample_dir, "BKMVDATA.TXT", fm, change_total)
    with pytest.raises(ValidationError, match="1155"):
        _validate(sample_dir, fm)


def test_closing_record_must_be_last(sample_dir, fm):
    def swap(lines):
        lines[-1], lines[-2] = lines[-2], lines[-1]

    _edit(sample_dir, "BKMVDATA.TXT", fm, swap)
    with pytest.raises(ValidationError, match="Z900"):
        _validate(sample_dir, fm)


def test_opening_record_must_be_first(sample_dir, fm):
    def swap(lines):
        lines[0], lines[1] = lines[1], lines[0]

    _edit(sample_dir, "BKMVDATA.TXT", fm, swap)
    with pytest.raises(ValidationError, match="A100"):
        _validate(sample_dir, fm)


def test_record_numbers_must_run_in_sequence(sample_dir, fm):
    def renumber(lines):
        lines[10] = patch_line(fm, "B100", lines[10], record_number=500)

    _edit(sample_dir, "BKMVDATA.TXT", fm, renumber)
    with pytest.raises(ValidationError) as err:
        _validate(sample_dir, fm)
    assert err.value.line == 11


def test_primary_id_must_match_everywhere(sample_dir, fm):
    def change_id(lines):
        lines[-1] = patch_line(fm, "Z900", lines[-1], primary_id="999999999999999")

    _edit(sample_dir, "BKMVDATA.TXT", fm, change_id)
    with pytest.raises(ValidationError, match="מזהה ראשי"):
        _validate(sample_dir, fm)


def test_movement_to_unknown_account_stops(sample_dir, fm):
    def retarget(lines):
        i = find_line(fm, lines, "B100", account_key="6200", date="20260615")
        lines[i] = patch_line(fm, "B100", lines[i], account_key="7777")

    _edit(sample_dir, "BKMVDATA.TXT", fm, retarget)
    with pytest.raises(ValidationError, match="7777"):
        _validate(sample_dir, fm)


def test_account_total_mismatch_is_a_warning(sample_dir, fm):
    def change_total(lines):
        i = find_line(fm, lines, "B110", account_key="6200")
        lines[i] = patch_line(fm, "B110", lines[i], total_debit=1)

    _edit(sample_dir, "BKMVDATA.TXT", fm, change_total)
    warnings = _validate(sample_dir, fm)
    assert len(warnings) == 1
    assert "6200" in warnings[0]


def test_declared_charset_mismatch_is_a_warning(sample_dir, fm):
    def change_flag(lines):
        lines[0] = patch_line(fm, "A000", lines[0], charset=2)

    _edit(sample_dir, "INI.TXT", fm, change_flag)
    warnings = _validate(sample_dir, fm)
    assert len(warnings) == 1
    assert "1029" in warnings[0]
