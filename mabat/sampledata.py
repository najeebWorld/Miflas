"""Synthetic OPENFRMT export for development and tests.

Deterministic: no randomness, no clock. The numbers are documented in
docs/superpowers/plans/2026-11-09-mabat-stage1.md and the tests rely on them.
The business is fictional.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from mabat.config import DEFAULT_CONFIG_DIR
from mabat.ingest.fieldmap import FieldMap, load_fieldmap

VAT_ID = "514000017"
BUSINESS_NAME = 'סטודיו אלון עיצוב בע"מ'
PRIMARY_ID = "202607011000001"
TAX_YEAR = 2026
VAT_PERCENT = 18

# (key, name, trial-balance code, trial-balance description)
ACCOUNTS = [
    ("1000", "בנק לאומי עו\"ש", "500", "בנקים"),
    ("1100", "לקוחות", "510", "לקוחות"),
    ("2000", "ספקים", "520", "ספקים"),
    ("2100", 'מע"מ', "530", 'מע"מ'),
    ("4000", "הכנסות ממכירות", "100", "הכנסות"),
    ("4010", "הכנסות משירותי ייעוץ", "100", "הכנסות"),
    ("4900", "הכנסות אחרות", "110", "הכנסות אחרות"),
    ("5000", "קניות סחורה", "200", "עלות המכר"),
    ("6000", "שכר עבודה", "300", "שכר ונלוות"),
    ("6010", "ביטוח לאומי מעסיק", "300", "שכר ונלוות"),
    ("6100", "שכירות משרד", "310", "שכירות ואחזקה"),
    ("6110", "חשמל ומים", "310", "שכירות ואחזקה"),
    ("6200", "פרסום ושיווק", "320", "שיווק ופרסום"),
    ("6300", "הנהלת חשבונות", "330", "שירותים מקצועיים"),
    ("6400", "ביטוח עסק", "340", "ביטוחים"),
    ("6500", "ציוד משרדי", "350", "משרדיות"),
    ("6510", "כיבוד ואירוח", "360", "כיבוד ואירוח"),
]

# Whole shekels per month, January..June. None = no activity that month.
MONTHLY = {
    "4000": [82_000, 85_000, 79_000, 88_000, 84_000, 86_000],
    "4010": [12_000, 12_500, 11_000, 13_000, 12_000, 12_500],
    "4900": [None, None, None, None, None, 15_000],
    "5000": [31_000, 33_000, 30_000, 34_000, 32_000, 33_000],
    "6000": [24_000] * 6,
    "6010": [1_800] * 6,
    "6100": [6_500] * 6,
    "6110": [900, 950, 870, 820, 880, 2_900],
    "6200": [4_000, 4_200, 3_800, 4_100, 4_000, 7_200],
    "6300": [2_200] * 6,
    "6400": [1_150, 1_150, 1_150, 1_150, 1_150, None],
    "6500": [300, 350, 250, 320, 280, 100],
    "6510": [400, 380, 420, 390, 410, 400],
}
# June only: a supplier credit note larger than the month's purchases, so the
# office-supplies card ends the month with a net credit.
OFFICE_CREDIT_NOTE_JUNE = 250

BANK, CUSTOMERS, SUPPLIERS, VAT = "1000", "1100", "2000", "2100"


@dataclass(frozen=True)
class Line:
    account: str
    is_debit: bool
    amount: int  # agorot
    details: str


@dataclass(frozen=True)
class Entry:
    date: date
    value_date: date
    reference: str
    lines: tuple[Line, ...]


def _vat(net: int) -> int:
    return net * VAT_PERCENT // 100


def _sale(day: date, ref: str, account: str, net_ils: int, text: str) -> Entry:
    net = net_ils * 100
    return Entry(day, day + timedelta(days=30), ref, (
        Line(CUSTOMERS, True, net + _vat(net), text),
        Line(account, False, net, text),
        Line(VAT, False, _vat(net), text),
    ))


def _purchase(day: date, ref: str, account: str, net_ils: int, text: str) -> Entry:
    net = net_ils * 100
    return Entry(day, day, ref, (
        Line(account, True, net, text),
        Line(VAT, True, _vat(net), text),
        Line(SUPPLIERS, False, net + _vat(net), text),
    ))


def _bank_payment(day: date, ref: str, parts: list[tuple[str, int]], text: str) -> Entry:
    lines = [Line(acc, True, ils * 100, text) for acc, ils in parts]
    lines.append(Line(BANK, False, sum(ils for _, ils in parts) * 100, text))
    return Entry(day, day, ref, tuple(lines))


def sample_entries() -> list[Entry]:
    entries: list[Entry] = []
    ref = 1000

    def next_ref() -> str:
        nonlocal ref
        ref += 1
        return str(ref)

    for i in range(6):
        month = i + 1

        def d(day: int) -> date:
            return date(TAX_YEAR, month, day)

        entries.append(_bank_payment(d(1), next_ref(), [("6100", MONTHLY["6100"][i])], "שכירות משרד"))
        if MONTHLY["6400"][i] is not None:
            entries.append(_bank_payment(d(3), next_ref(), [("6400", MONTHLY["6400"][i])], "ביטוח עסק"))
        entries.append(_purchase(d(5), next_ref(), "5000", MONTHLY["5000"][i], "קניות סחורה"))
        entries.append(_purchase(d(8), next_ref(), "6500", MONTHLY["6500"][i], "ציוד משרדי"))
        first = MONTHLY["4000"][i] * 3 // 5
        entries.append(_sale(d(10), next_ref(), "4000", first, "חשבונית מכירה"))
        entries.append(_purchase(d(12), next_ref(), "6110", MONTHLY["6110"][i], "חשמל ומים"))
        entries.append(_purchase(d(15), next_ref(), "6200", MONTHLY["6200"][i], "פרסום ושיווק"))
        entries.append(_purchase(d(17), next_ref(), "6510", MONTHLY["6510"][i], "כיבוד ואירוח"))
        if MONTHLY["4900"][i] is not None:
            entries.append(_sale(d(18), next_ref(), "4900", MONTHLY["4900"][i], "מכירת ציוד משומש"))
        entries.append(_sale(d(20), next_ref(), "4010", MONTHLY["4010"][i], "שירותי ייעוץ"))
        if month == 6:
            net = OFFICE_CREDIT_NOTE_JUNE * 100
            entries.append(Entry(d(22), d(22), next_ref(), (
                Line(SUPPLIERS, True, net + _vat(net), "זיכוי ספק ציוד משרדי"),
                Line("6500", False, net, "זיכוי ספק ציוד משרדי"),
                Line(VAT, False, _vat(net), "זיכוי ספק ציוד משרדי"),
            )))
        entries.append(_sale(d(24), next_ref(), "4000", MONTHLY["4000"][i] - first, "חשבונית מכירה"))
        entries.append(_purchase(d(25), next_ref(), "6300", MONTHLY["6300"][i], "הנהלת חשבונות"))
        entries.append(_bank_payment(
            d(28), next_ref(),
            [("6000", MONTHLY["6000"][i]), ("6010", MONTHLY["6010"][i])],
            "משכורות",
        ))
    return entries


def render_export(
    fm: FieldMap,
    *,
    accounts: list[tuple[str, str, str, str]],
    entries: list[Entry],
    vat_id: str = VAT_ID,
    business_name: str = BUSINESS_NAME,
    primary_id: str = PRIMARY_ID,
    tax_year: int = TAX_YEAR,
    charset_flag: str = "1",
    count_only: tuple[str, ...] = ("C100", "D110"),
) -> tuple[list[str], list[str]]:
    """Return (INI.TXT lines, BKMVDATA.TXT lines) for the given books."""
    data: list[str] = []
    counts: dict[str, int] = {}

    def add(code: str, line: str) -> None:
        data.append(line)
        counts[code] = counts.get(code, 0) + 1

    def number() -> int:
        return len(data) + 1

    common = {"vat_id": vat_id}
    add("A100", fm.build_record("A100", {
        **common, "record_number": number(), "primary_id": primary_id,
        "system_constant": "&OF1.31&",
    }))
    for code in count_only:
        add(code, fm.build_count_only(code, number()))

    debit: dict[str, int] = {}
    credit: dict[str, int] = {}
    for tx_number, entry in enumerate(entries, start=1):
        for line_number, line in enumerate(entry.lines, start=1):
            others = [l.account for l in entry.lines if l.account != line.account]
            add("B100", fm.build_record("B100", {
                **common,
                "record_number": number(),
                "transaction_number": tx_number,
                "transaction_line": line_number,
                "batch": entry.date.month,
                "reference": entry.reference,
                "details": line.details,
                "date": entry.date.strftime("%Y%m%d"),
                "value_date": entry.value_date.strftime("%Y%m%d"),
                "account_key": line.account,
                "counter_account": others[0] if others else "",
                "debit_credit": 1 if line.is_debit else 2,
                "currency_code": "ILS",
                "amount": line.amount,
                "entry_date": entry.date.strftime("%Y%m%d"),
                "entered_by": "admin",
            }))
            bucket = debit if line.is_debit else credit
            bucket[line.account] = bucket.get(line.account, 0) + line.amount

    for key, name, tb_code, tb_desc in accounts:
        add("B110", fm.build_record("B110", {
            **common,
            "record_number": number(),
            "account_key": key,
            "account_name": name,
            "trial_balance_code": tb_code,
            "trial_balance_desc": tb_desc,
            "total_debit": debit.get(key, 0),
            "total_credit": credit.get(key, 0),
        }))

    total = len(data) + 1
    add("Z900", fm.build_record("Z900", {
        **common, "record_number": number(), "primary_id": primary_id,
        "system_constant": "&OF1.31&", "total_records": total,
    }))

    ini = [fm.build_record("A000", {
        "total_records": total,
        "vat_id": vat_id,
        "primary_id": primary_id,
        "system_constant": "&OF1.31&",
        "software_registration": "00123456",
        "software_name": "תוכנת דמה",
        "software_version": "1.0",
        "software_maker_name": "מבט",
        "software_type": 1,
        "bookkeeping_type": 2,
        "balance_required": 1,
        "business_name": business_name,
        "address_street": "הרצל",
        "address_house_number": "10",
        "address_city": "חיפה",
        "tax_year": tax_year,
        "process_date": f"{tax_year}0701",
        "process_time": "1000",
        "language_code": 0,
        "charset": charset_flag,
        "leading_currency": "ILS",
        "has_branches": 0,
    })]
    for code in sorted(c for c in counts if c not in ("A100", "Z900")):
        ini.append(fm.build_record("SUMMARY", {"record_code": code, "record_count": counts[code]}))
    return ini, data


def write_export(folder: Path, ini: list[str], data: list[str], encoding: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name, lines in (("INI.TXT", ini), ("BKMVDATA.TXT", data)):
        text = "".join(line + "\r\n" for line in lines)
        (folder / name).write_bytes(text.encode(encoding))


def write_sample(out_root: Path | str, encoding: str = "iso8859_8", fm: FieldMap | None = None) -> Path:
    """Write the sample client under out_root using the spec's folder layout."""
    fm = fm or load_fieldmap(DEFAULT_CONFIG_DIR / "fieldmap.yaml")
    charset_flag = "2" if encoding == "cp862" else "1"
    ini, data = render_export(fm, accounts=ACCOUNTS, entries=sample_entries(), charset_flag=charset_flag)
    folder = Path(out_root) / "OPENFRMT" / f"{VAT_ID[:8]}.{TAX_YEAR % 100:02d}" / "07011000"
    write_export(folder, ini, data, encoding)
    return folder
