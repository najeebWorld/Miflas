"""Wires the stages together: export folder -> report contexts.

A report *context* is a plain JSON-serializable dict holding every computed
figure and every sentence of one monthly report. The HTML template only
prints it, and the dashboard stores it, so a report can be re-rendered later
without the client's source files.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from mabat.anomalies.rules import SEVERITIES, Thresholds, detect, has_history
from mabat.compute.pnl import Change, available_months, compute_pnl
from mabat.config import Config
from mabat.errors import ValidationError
from mabat.formatting import HEBREW_MONTHS, ils, month_label, pct
from mabat.ingest.parser import INI, parse_export
from mabat.ingest.validate import validate_export
from mabat.models import ParsedExport
from mabat.narrate.guard import safe_narrate
from mabat.narrate.templates import title
from mabat.normalize.ledger import build_ledger

STATUS_READY = "ready"
STATUS_NEEDS_REVIEW = "needs_review"

_SEVERITY_LABELS = {"red": "חריגה מהותית", "orange": "לבדיקה", "info": "מידע"}
# Whether a rise in the measure is good news for the client.
_RISE_IS_GOOD = {"income": True, "expenses": False, "profit": True}
_KPI_LABELS = {"income": "הכנסות", "expenses": "הוצאות", "profit": "רווח תפעולי"}


def _signed_ils(agorot: int) -> str:
    return ("+" if agorot > 0 else "") + ils(agorot)


def _change(key: str, change: Change | None) -> dict | None:
    if change is None:
        return None
    direction = "up" if change.diff > 0 else "down" if change.diff < 0 else "flat"
    if direction == "flat":
        tone = "neutral"
    else:
        tone = "good" if (direction == "up") == _RISE_IS_GOOD[key] else "bad"
    return {
        "diff": change.diff,
        "diff_text": _signed_ils(change.diff),
        "pct_text": None if change.pct_tenths is None else pct(abs(change.pct_tenths)),
        "direction": direction,
        "tone": tone,
    }


def build_context(
    parsed: ParsedExport,
    ledger: pd.DataFrame,
    warnings: list[str],
    month: str,
    thresholds: Thresholds,
    now: datetime,
) -> dict:
    summary = compute_pnl(ledger, month)
    findings = detect(ledger, month, thresholds)
    warnings = list(warnings)
    if not has_history(ledger, month, thresholds):
        warnings.append(
            f"אין {thresholds.history_months} חודשי נתונים לפני {month_label(month)}, "
            "ולכן בדיקות ההשוואה לממוצע לא בוצעו בדוח זה."
        )

    target = summary.target
    values = {"income": target.income, "expenses": target.expenses, "profit": target.profit}
    changes = {
        "income": summary.income_change,
        "expenses": summary.expenses_change,
        "profit": summary.profit_change,
    }
    kpis = [
        {
            "key": key,
            "label": _KPI_LABELS[key],
            "value": values[key],
            "value_text": ils(values[key]),
            "change": _change(key, changes[key]),
        }
        for key in ("income", "expenses", "profit")
    ]

    series = []
    for m in summary.series:
        year, mm = m.month.split("-")
        series.append({
            "month": m.month,
            "label": HEBREW_MONTHS[int(mm) - 1],
            "year": year,
            "month_label": month_label(m.month),
            "income": m.income,
            "expenses": m.expenses,
            "profit": m.profit,
            "income_text": ils(m.income),
            "expenses_text": ils(m.expenses),
            "profit_text": ils(m.profit),
            "margin_text": "—" if m.margin_tenths is None else pct(m.margin_tenths),
        })

    finding_items = [
        {
            "rule": f.rule,
            "severity": f.severity,
            "severity_label": _SEVERITY_LABELS[f.severity],
            "title": title(f),
            "text": safe_narrate(f, thresholds.history_months),
            "type": f.type,
            "subject": f.subject,
            "account": f.account,
            "amount": f.amount,
            "baseline": f.baseline,
            "pct_tenths": f.pct_tenths,
        }
        for f in findings
    ]
    counts = {s: sum(1 for f in findings if f.severity == s) for s in SEVERITIES}
    needs_review = bool(warnings) or counts["red"] > 0 or counts["orange"] > 0

    return {
        "schema": 1,
        "client": {
            "vat_id": parsed.header.vat_id,
            "business_name": parsed.header.business_name,
            "software_name": parsed.header.software_name,
            "tax_year": parsed.header.tax_year,
        },
        "month": month,
        "month_label": month_label(month),
        "previous_label": month_label(summary.previous.month) if summary.previous else None,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M"),
        "status": STATUS_NEEDS_REVIEW if needs_review else STATUS_READY,
        "history_months": thresholds.history_months,
        "kpis": kpis,
        "margin_text": "—" if target.margin_tenths is None else pct(target.margin_tenths),
        "series": series,
        "findings": finding_items,
        "severity_counts": counts,
        "warnings": warnings,
    }


def discover_exports(root: Path | str) -> list[Path]:
    """Folders under `root` (or `root` itself) that hold an INI.TXT."""
    root = Path(root)
    if not root.is_dir():
        return []
    found = {p.parent for p in root.rglob("*") if p.is_file() and p.name.upper() == INI}
    return sorted(found)


def run_folder(
    folder: Path | str,
    config: Config,
    month: str | None = None,
    all_months: bool = False,
    now: datetime | None = None,
) -> list[dict]:
    """Parse, validate and report on one export folder.

    Returns one report context per requested month: the latest month with
    activity by default, one named month, or every month in the export.
    Raises ValidationError when the export cannot be trusted.
    """
    parsed = parse_export(folder, config.fieldmap)
    warnings = validate_export(parsed)
    ledger = build_ledger(parsed, config.classification)
    months = available_months(ledger)
    if not months:
        raise ValidationError("בייצוא אין תנועות בחשבונות הכנסה או הוצאה")
    if all_months:
        targets = months
    elif month is not None:
        if month not in months:
            raise ValidationError(f"אין נתונים לחודש {month}. חודשים זמינים: {', '.join(months)}")
        targets = [month]
    else:
        targets = [months[-1]]
    now = now or datetime.now()
    return [build_context(parsed, ledger, warnings, m, config.thresholds, now) for m in targets]
