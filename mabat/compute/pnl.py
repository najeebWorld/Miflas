"""Monthly P&L and month-over-month comparison.

Deterministic integer arithmetic: money in agorot, ratios in tenths of a
percent. Nothing here reads a clock, a file or a model.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from mabat.formatting import ratio_tenths
from mabat.months import add_months, month_range

SERIES_MONTHS = 6


@dataclass(frozen=True)
class MonthPnL:
    month: str
    income: int
    expenses: int
    profit: int
    margin_tenths: int | None  # profit / income; None when there is no income


@dataclass(frozen=True)
class Change:
    diff: int
    pct_tenths: int | None  # relative to |previous|; None when previous is 0


@dataclass(frozen=True)
class PnLSummary:
    target: MonthPnL
    previous: MonthPnL | None
    income_change: Change | None
    expenses_change: Change | None
    profit_change: Change | None
    series: list[MonthPnL]  # oldest first, ends with target


def available_months(ledger: pd.DataFrame) -> list[str]:
    return sorted(ledger["month"].unique())


def month_pnl(ledger: pd.DataFrame, month: str) -> MonthPnL:
    rows = ledger[ledger["month"] == month]
    income = int(rows.loc[rows["type"] == "income", "amount"].sum())
    expenses = int(rows.loc[rows["type"] == "expense", "amount"].sum())
    profit = income - expenses
    return MonthPnL(month, income, expenses, profit, ratio_tenths(profit, income))


def _change(current: int, previous: int) -> Change:
    return Change(current - previous, ratio_tenths(current - previous, abs(previous)))


def compute_pnl(ledger: pd.DataFrame, target_month: str) -> PnLSummary:
    months = available_months(ledger)
    if target_month not in months:
        raise ValueError(f"no data for month {target_month}")
    first = months[0]
    start = max(first, add_months(target_month, -(SERIES_MONTHS - 1)))
    series = [month_pnl(ledger, m) for m in month_range(start, target_month)]
    target = series[-1]

    if len(series) < 2:
        return PnLSummary(target, None, None, None, None, series)
    previous = series[-2]
    return PnLSummary(
        target=target,
        previous=previous,
        income_change=_change(target.income, previous.income),
        expenses_change=_change(target.expenses, previous.expenses),
        profit_change=_change(target.profit, previous.profit),
        series=series,
    )
