"""Data structures passed between pipeline stages.

All money is an int number of agorot. No floats anywhere in the pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Header:
    """INI.TXT record A000."""

    vat_id: str
    business_name: str
    software_name: str
    tax_year: int | None
    range_start: date | None
    range_end: date | None
    primary_id: str
    declared_charset: str
    total_records: int


@dataclass(frozen=True)
class Account:
    """BKMVDATA record B110."""

    key: str
    name: str
    tb_code: str
    tb_desc: str
    code_6111: str
    opening_balance: int
    total_debit: int
    total_credit: int


@dataclass(frozen=True)
class Movement:
    """BKMVDATA record B100. `line` is the 1-based line in BKMVDATA.TXT."""

    line: int
    account_key: str
    counter_account: str
    date: date
    value_date: date | None
    is_debit: bool
    amount: int
    details: str
    reference: str


@dataclass
class ParsedExport:
    header: Header
    accounts: list[Account]
    movements: list[Movement]
    record_codes: list[str]
    record_numbers: list[int]
    ini_counts: dict[str, int]
    primary_ids: dict[str, str]
    closing_total: int
    encoding: str
    source: str = ""
    notes: list[str] = field(default_factory=list)
