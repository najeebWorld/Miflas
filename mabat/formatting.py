"""Deterministic number formatting. Integer arithmetic only."""
from __future__ import annotations

HEBREW_MONTHS = [
    "ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
    "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר",
]


def _div_half_away(numer: int, denom: int) -> int:
    """numer / denom rounded to the nearest int, halves away from zero."""
    negative = (numer < 0) != (denom < 0)
    n, d = abs(numer), abs(denom)
    q = (2 * n + d) // (2 * d)
    return -q if negative else q


def ils(agorot: int) -> str:
    """12345.67 ILS -> '₪12,346'. Negative values render as '-₪150'."""
    shekels = _div_half_away(abs(agorot), 100)
    text = f"₪{shekels:,}"
    return f"-{text}" if agorot < 0 and shekels else text


def ratio_tenths(numer: int, denom: int) -> int | None:
    """numer/denom as tenths of a percent (314 == 31.4%). None if denom is 0."""
    if denom == 0:
        return None
    return _div_half_away(numer * 1000, denom)


def pct(tenths: int) -> str:
    sign = "-" if tenths < 0 else ""
    whole, frac = divmod(abs(tenths), 10)
    return f"{sign}{whole:,}.{frac}%"


def month_label(month: str) -> str:
    """'2026-06' -> 'יוני 2026'."""
    year, mm = month.split("-")
    return f"{HEBREW_MONTHS[int(mm) - 1]} {year}"


def month_short(month: str) -> str:
    """'2026-06' -> '06/26'."""
    year, mm = month.split("-")
    return f"{mm}/{year[2:]}"
