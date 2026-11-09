"""Read an OPENFRMT folder (INI.TXT + BKMVDATA.TXT) into a ParsedExport.

Anything that cannot be decoded with certainty raises ValidationError with the
file and line. Cross-record checks (counts, sequence) live in validate.py.
"""
from __future__ import annotations

import re
import zipfile
from datetime import date, datetime
from pathlib import Path

from mabat.errors import ValidationError
from mabat.ingest.encoding import detect_encoding
from mabat.ingest.fieldmap import FieldMap
from mabat.models import Account, Header, Movement, ParsedExport

INI = "INI.TXT"
BKMV = "BKMVDATA.TXT"

_AMOUNT = re.compile(r"[+-]?\d+")


def parse_export(folder: Path | str, fm: FieldMap) -> ParsedExport:
    folder = Path(folder)
    ini_bytes = _read_ini(folder)
    data_bytes = _read_bkmvdata(folder)
    encoding = detect_encoding(ini_bytes + data_bytes)

    header, ini_counts = _parse_ini(_lines(ini_bytes, encoding), fm)

    accounts: list[Account] = []
    movements: list[Movement] = []
    codes: list[str] = []
    numbers: list[int] = []
    primary_ids = {"A000": header.primary_id}
    closing_total = -1
    known = set(fm.data_codes())

    for n, line in enumerate(_lines(data_bytes, encoding), start=1):
        code = fm.record_code(line)
        if code not in known:
            raise ValidationError(f"קוד רשומה לא מוכר: {code!r}", file=BKMV, line=n)
        if len(line) != fm.length(code):
            raise ValidationError(
                f"אורך רשומת {code} הוא {len(line)} תווים במקום {fm.length(code)}",
                file=BKMV, line=n,
            )
        codes.append(code)
        numbers.append(_int(fm.record_number(line), "מספר רשומה", BKMV, n))

        if code == "B100":
            movements.append(_movement(fm.slice_record(code, line), n))
        elif code == "B110":
            accounts.append(_account(fm.slice_record(code, line), n))
        elif code == "A100":
            primary_ids["A100"] = fm.slice_record(code, line)["primary_id"]
        elif code == "Z900":
            v = fm.slice_record(code, line)
            primary_ids["Z900"] = v["primary_id"]
            closing_total = _int(v["total_records"], "סך רשומות", BKMV, n)

    return ParsedExport(
        header=header,
        accounts=accounts,
        movements=movements,
        record_codes=codes,
        record_numbers=numbers,
        ini_counts=ini_counts,
        primary_ids=primary_ids,
        closing_total=closing_total,
        encoding=encoding,
        source=str(folder),
    )


# ---- files ----

def _find(folder: Path, name: str) -> Path | None:
    if not folder.is_dir():
        raise ValidationError(f"התיקייה {folder} לא נמצאה")
    for child in folder.iterdir():
        if child.is_file() and child.name.upper() == name.upper():
            return child
    return None


def _read_ini(folder: Path) -> bytes:
    path = _find(folder, INI)
    if path is None:
        raise ValidationError(f"הקובץ {INI} לא נמצא בתיקייה {folder}")
    return path.read_bytes()


def _read_bkmvdata(folder: Path) -> bytes:
    path = _find(folder, BKMV)
    if path is not None:
        return path.read_bytes()
    # The spec requires the data file to be archived under the name BKMVDATA.
    for child in sorted(folder.iterdir()):
        if child.is_file() and child.stem.upper() == "BKMVDATA" and zipfile.is_zipfile(child):
            with zipfile.ZipFile(child) as zf:
                members = [m for m in zf.namelist() if not m.endswith("/")]
                named = [m for m in members if Path(m).name.upper() == BKMV]
                if not members:
                    break
                return zf.read((named or members)[0])
    raise ValidationError(f"הקובץ {BKMV} (או ארכיב BKMVDATA) לא נמצא בתיקייה {folder}")


def _lines(data: bytes, encoding: str) -> list[str]:
    text = data.decode(encoding, errors="replace")
    lines = [line.rstrip("\r") for line in text.split("\n")]
    while lines and lines[-1].strip("\x1a ") == "":
        lines.pop()
    return lines


# ---- INI.TXT ----

def _parse_ini(lines: list[str], fm: FieldMap) -> tuple[Header, dict[str, int]]:
    if not lines:
        raise ValidationError("הקובץ ריק", file=INI)
    first = lines[0]
    if not first.startswith("A000") or len(first) != fm.length("A000"):
        raise ValidationError(
            f"רשומת A000 חסרה או באורך {len(first)} תווים במקום {fm.length('A000')}",
            file=INI, line=1,
        )
    v = fm.slice_record("A000", first)
    year = _int(v["tax_year"], "שנת המס", INI, 1)
    header = Header(
        vat_id=v["vat_id"],
        business_name=v["business_name"],
        software_name=v["software_name"],
        tax_year=year or None,
        range_start=_date(v["range_start"], "תאריך התחלה", INI, 1),
        range_end=_date(v["range_end"], "תאריך סיום", INI, 1),
        primary_id=v["primary_id"],
        declared_charset=v["charset"],
        total_records=_int(v["total_records"], "סך רשומות", INI, 1),
    )
    counts: dict[str, int] = {}
    for n, line in enumerate(lines[1:], start=2):
        if len(line) != fm.length("SUMMARY"):
            raise ValidationError(
                f"אורך רשומת סיכום הוא {len(line)} תווים במקום {fm.length('SUMMARY')}",
                file=INI, line=n,
            )
        s = fm.slice_record("SUMMARY", line)
        counts[s["record_code"]] = _int(s["record_count"], "סך רשומות", INI, n)
    return header, counts


# ---- BKMVDATA.TXT records ----

def _movement(v: dict[str, str], n: int) -> Movement:
    flag = v["debit_credit"]
    if flag not in ("1", "2"):
        raise ValidationError(f"סימן פעולה לא חוקי: {flag!r} (מותר 1 או 2)", file=BKMV, line=n)
    when = _date(v["date"], "תאריך", BKMV, n)
    if when is None:
        raise ValidationError("תאריך התנועה חסר", file=BKMV, line=n)
    return Movement(
        line=n,
        account_key=v["account_key"],
        counter_account=v["counter_account"],
        date=when,
        value_date=_date(v["value_date"], "תאריך ערך", BKMV, n),
        is_debit=flag == "1",
        amount=_amount(v["amount"], "סכום הפעולה", n),
        details=v["details"],
        reference=v["reference"],
    )


def _account(v: dict[str, str], n: int) -> Account:
    code_6111 = v["code_6111"]
    return Account(
        key=v["account_key"],
        name=v["account_name"],
        tb_code=v["trial_balance_code"],
        tb_desc=v["trial_balance_desc"],
        code_6111="" if code_6111.strip("0") == "" else code_6111,
        opening_balance=_amount(v["opening_balance"], "יתרת פתיחה", n),
        total_debit=_amount(v["total_debit"], 'סה"כ חובה', n),
        total_credit=_amount(v["total_credit"], 'סה"כ זכות', n),
    )


# ---- field converters ----

def _amount(text: str, label: str, n: int) -> int:
    """X9(n)v99: optional sign then digits, last two are agorot. Blank = 0."""
    if text == "":
        return 0
    if not _AMOUNT.fullmatch(text):
        raise ValidationError(f"{label}: ערך לא מספרי {text!r}", file=BKMV, line=n)
    return int(text)


def _int(text: str, label: str, file: str, n: int) -> int:
    text = text.strip()
    if text == "":
        return 0
    if not text.isdigit():
        raise ValidationError(f"{label}: ערך לא מספרי {text!r}", file=file, line=n)
    return int(text)


def _date(text: str, label: str, file: str, n: int) -> date | None:
    """YYYYMMDD. Blank or all zeros means 'not provided'."""
    if text.strip("0") == "":
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError:
        raise ValidationError(f"{label}: תאריך לא חוקי {text!r}", file=file, line=n) from None
