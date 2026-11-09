import zipfile
from datetime import date

import pytest

from mabat.errors import ValidationError
from mabat.ingest.parser import parse_export
from mabat.sampledata import BUSINESS_NAME, write_sample
from tests.conftest import find_line, patch_line, read_lines, write_lines


def test_header_comes_from_a000(sample_dir, fm):
    parsed = parse_export(sample_dir, fm)
    h = parsed.header
    assert h.business_name == BUSINESS_NAME
    assert h.vat_id == "514000017"
    assert h.tax_year == 2026
    assert h.software_name == "תוכנת דמה"
    assert h.declared_charset == "1"
    assert h.total_records == 229
    assert h.range_start is None


def test_accounts_and_movements(sample_dir, fm):
    parsed = parse_export(sample_dir, fm)
    assert len(parsed.accounts) == 17
    assert len(parsed.movements) == 208
    by_key = {a.key: a for a in parsed.accounts}
    assert by_key["6110"].name == "חשמל ומים"
    assert by_key["6110"].tb_code == "310"
    assert by_key["6110"].tb_desc == "שכירות ואחזקה"
    assert by_key["6110"].code_6111 == ""
    assert by_key["2100"].name == 'מע"מ'

    june_marketing = [
        m for m in parsed.movements if m.account_key == "6200" and m.date.month == 6
    ]
    assert len(june_marketing) == 1
    m = june_marketing[0]
    assert (m.is_debit, m.amount, m.date, m.value_date) == (True, 720000, date(2026, 6, 15), date(2026, 6, 15))
    assert m.details == "פרסום ושיווק"
    assert m.counter_account == "2100"


def test_structural_metadata(sample_dir, fm):
    parsed = parse_export(sample_dir, fm)
    assert parsed.encoding == "cp1255"
    assert parsed.record_codes[0] == "A100" and parsed.record_codes[-1] == "Z900"
    assert parsed.record_numbers == list(range(1, 230))
    assert parsed.ini_counts == {"B100": 208, "B110": 17, "C100": 1, "D110": 1}
    assert parsed.closing_total == 229
    assert set(parsed.primary_ids.values()) == {"202607011000001"}
    assert set(parsed.primary_ids) == {"A000", "A100", "Z900"}


@pytest.mark.parametrize("encoding,codec", [("cp862", "cp862"), ("utf-8", "utf-8")])
def test_other_encodings_decode_the_same_text(tmp_path, fm, encoding, codec):
    folder = write_sample(tmp_path, encoding=encoding, fm=fm)
    parsed = parse_export(folder, fm)
    assert parsed.encoding == codec
    assert parsed.header.business_name == BUSINESS_NAME
    assert {a.key: a.name for a in parsed.accounts}["6000"] == "שכר עבודה"


def test_reads_zipped_bkmvdata(sample_dir, fm):
    txt = sample_dir / "BKMVDATA.TXT"
    with zipfile.ZipFile(sample_dir / "BKMVDATA.zip", "w") as zf:
        zf.write(txt, "BKMVDATA.TXT")
    txt.unlink()
    assert len(parse_export(sample_dir, fm).movements) == 208


def test_file_names_are_case_insensitive(sample_dir, fm):
    (sample_dir / "INI.TXT").rename(sample_dir / "ini.txt")
    (sample_dir / "BKMVDATA.TXT").rename(sample_dir / "bkmvdata.txt")
    assert parse_export(sample_dir, fm).header.vat_id == "514000017"


def test_negative_amount_keeps_its_sign(sample_dir, fm):
    path = sample_dir / "BKMVDATA.TXT"
    lines = read_lines(path)
    i = find_line(fm, lines, "B100", account_key="6200", date="20260615")
    lines[i] = patch_line(fm, "B100", lines[i], amount=-720000)
    write_lines(path, lines)
    parsed = parse_export(sample_dir, fm)
    assert parsed.movements[i - 3].amount == -720000  # A100, C100, D110 precede the B100s


def test_short_line_stops_with_line_number(sample_dir, fm):
    path = sample_dir / "BKMVDATA.TXT"
    lines = read_lines(path)
    lines[9] = lines[9][:-5]
    write_lines(path, lines)
    with pytest.raises(ValidationError) as err:
        parse_export(sample_dir, fm)
    assert err.value.line == 10
    assert err.value.file == "BKMVDATA.TXT"


def test_unknown_record_code_stops(sample_dir, fm):
    path = sample_dir / "BKMVDATA.TXT"
    lines = read_lines(path)
    lines[5] = "X999" + lines[5][4:]
    write_lines(path, lines)
    with pytest.raises(ValidationError, match="X999"):
        parse_export(sample_dir, fm)


def test_unparseable_amount_stops(sample_dir, fm):
    path = sample_dir / "BKMVDATA.TXT"
    lines = read_lines(path)
    i = find_line(fm, lines, "B100", account_key="6200", date="20260615")
    good = fm.slice_record("B100", lines[i])["amount"]
    lines[i] = lines[i].replace(good, "+00000ABC720000")
    write_lines(path, lines)
    with pytest.raises(ValidationError) as err:
        parse_export(sample_dir, fm)
    assert err.value.line == i + 1


def test_unparseable_date_stops(sample_dir, fm):
    path = sample_dir / "BKMVDATA.TXT"
    lines = read_lines(path)
    i = find_line(fm, lines, "B100", account_key="6200", date="20260615")
    lines[i] = patch_line(fm, "B100", lines[i], date="20261340")
    write_lines(path, lines)
    with pytest.raises(ValidationError):
        parse_export(sample_dir, fm)


def test_bad_debit_credit_flag_stops(sample_dir, fm):
    path = sample_dir / "BKMVDATA.TXT"
    lines = read_lines(path)
    i = find_line(fm, lines, "B100", account_key="6200", date="20260615")
    lines[i] = patch_line(fm, "B100", lines[i], debit_credit=3)
    write_lines(path, lines)
    with pytest.raises(ValidationError):
        parse_export(sample_dir, fm)


def test_missing_ini_stops(sample_dir, fm):
    (sample_dir / "INI.TXT").unlink()
    with pytest.raises(ValidationError, match="INI.TXT"):
        parse_export(sample_dir, fm)


def test_missing_bkmvdata_stops(sample_dir, fm):
    (sample_dir / "BKMVDATA.TXT").unlink()
    with pytest.raises(ValidationError, match="BKMVDATA"):
        parse_export(sample_dir, fm)


def test_malformed_ini_summary_stops(sample_dir, fm):
    path = sample_dir / "INI.TXT"
    lines = read_lines(path)
    lines[1] = lines[1][:-2]
    write_lines(path, lines)
    with pytest.raises(ValidationError) as err:
        parse_export(sample_dir, fm)
    assert err.value.file == "INI.TXT" and err.value.line == 2
