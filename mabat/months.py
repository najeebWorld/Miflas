"""Calendar-month arithmetic on 'YYYY-MM' strings."""
from __future__ import annotations


def _index(month: str) -> int:
    year, mm = month.split("-")
    return int(year) * 12 + int(mm) - 1


def _label(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def add_months(month: str, delta: int) -> str:
    return _label(_index(month) + delta)


def month_range(first: str, last: str) -> list[str]:
    """Every calendar month from first to last, inclusive."""
    return [_label(i) for i in range(_index(first), _index(last) + 1)]
