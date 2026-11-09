"""Journal movements -> normalized monthly P&L rows.

Output schema (one row per account per month with activity):
    account, account_name, category, type, month, amount
`month` is 'YYYY-MM'. `amount` is agorot (int64), positive in the account's
natural direction: income = credit - debit, expense = debit - credit.
"""
from __future__ import annotations

import pandas as pd

from mabat.errors import ValidationError
from mabat.ingest.parser import BKMV
from mabat.models import ParsedExport
from mabat.normalize.classify import Classification

COLUMNS = ["account", "account_name", "category", "type", "month", "amount"]
_MAX_LISTED = 10


def build_ledger(parsed: ParsedExport, classification: Classification) -> pd.DataFrame:
    accounts = {a.key: a for a in parsed.accounts}
    active = sorted({m.account_key for m in parsed.movements})

    classified: dict[str, tuple[str, str]] = {}
    unclassified: list[str] = []
    for key in active:
        result = classification.classify(accounts[key])
        if result is None:
            unclassified.append(key)
        else:
            classified[key] = result
    if unclassified:
        listed = ", ".join(f"{k} ({accounts[k].name})" for k in unclassified[:_MAX_LISTED])
        more = f" ועוד {len(unclassified) - _MAX_LISTED}" if len(unclassified) > _MAX_LISTED else ""
        raise ValidationError(
            f"{len(unclassified)} חשבונות עם תנועות אינם מסווגים ב-classification.yaml: {listed}{more}. "
            "יש להוסיף להם כלל סיווג (income / expense / balance_sheet)."
        )

    rows = []
    for m in parsed.movements:
        kind, category = classified[m.account_key]
        if kind == "balance_sheet":
            continue
        when = m.date if classification.date_field == "date" else m.value_date
        if when is None:
            raise ValidationError("תאריך הערך חסר, והוא השדה שלפיו משויכות תנועות לחודש", file=BKMV, line=m.line)
        debit_positive = kind == "expense"
        signed = m.amount if m.is_debit == debit_positive else -m.amount
        rows.append((m.account_key, accounts[m.account_key].name, category, kind, when.strftime("%Y-%m"), signed))

    if not rows:
        return pd.DataFrame({c: pd.Series(dtype="int64" if c == "amount" else "object") for c in COLUMNS})

    frame = pd.DataFrame(rows, columns=COLUMNS)
    ledger = frame.groupby(COLUMNS[:-1], as_index=False, sort=False)["amount"].sum()
    return ledger.sort_values(["month", "account"], kind="stable").reset_index(drop=True)
