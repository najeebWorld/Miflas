"""Deterministic Hebrew wording for findings.

This is the only narration in stage 1. Every figure in a sentence is taken
from the Finding and formatted here; nothing is estimated or rephrased.
"""
from __future__ import annotations

from mabat.anomalies.rules import Finding
from mabat.formatting import ils, pct

_PLURAL = {"income": "ההכנסות", "expense": "ההוצאות"}
_SINGULAR = {"income": "הכנסה", "expense": "הוצאה"}
_CARD = {"income": "כרטיס ההכנסה", "expense": "כרטיס ההוצאה"}
# The side an account lands on when its monthly net is opposite to its type.
_FLIPPED_SIDE = {"income": "חובה", "expense": "זכות"}


def _category_deviation(f: Finding, months: int) -> str:
    direction = "גבוה" if f.pct_tenths > 0 else "נמוך"
    return (
        f'{_PLURAL[f.type]} בקטגוריה "{f.subject}" הסתכמו ב-{ils(f.amount)}, '
        f"{direction} ב-{pct(abs(f.pct_tenths))} מהממוצע של {months} החודשים הקודמים ({ils(f.baseline)})."
    )


def _missing_recurring(f: Finding, months: int) -> str:
    return (
        f'לא נרשמה החודש הוצאה בקטגוריה "{f.subject}", '
        f"שהופיעה בכל אחד מ-{months} החודשים הקודמים (ממוצע {ils(f.baseline)})."
    )


def _one_off(f: Finding, months: int) -> str:
    return (
        f'{_SINGULAR[f.type]} חד-פעמית בקטגוריה "{f.subject}" בסך {ils(f.amount)}, '
        f"שהם {pct(f.pct_tenths)} מסך {_PLURAL[f.type]} החודש. "
        f"בקטגוריה לא נרשמה פעילות ב-{months} החודשים הקודמים."
    )


def _sign_flip(f: Finding, months: int) -> str:
    return (
        f'{_CARD[f.type]} "{f.subject}" ({f.account}) סיים את החודש ביתרת '
        f"{_FLIPPED_SIDE[f.type]} של {ils(abs(f.amount))}. "
        "כדאי לבדוק אם מדובר בזיכוי או בטעות סיווג."
    )


def _account_spike(f: Finding, months: int) -> str:
    return (
        f'בכרטיס "{f.subject}" ({f.account}) נרשמו {ils(f.amount)}, '
        f"לעומת ממוצע של {ils(f.baseline)} ב-{months} החודשים הקודמים. "
        "הקטגוריה כולה לא חרגה."
    )


_SENTENCES = {
    "category_deviation": _category_deviation,
    "missing_recurring": _missing_recurring,
    "one_off": _one_off,
    "sign_flip": _sign_flip,
    "account_spike": _account_spike,
}

_TITLES = {
    "category_deviation": lambda f: "חריגה בקטגוריה",
    "missing_recurring": lambda f: "הוצאה קבועה שלא נרשמה",
    "one_off": lambda f: f"{_SINGULAR[f.type]} חד-פעמית",
    "sign_flip": lambda f: "יתרה הפוכה בכרטיס",
    "account_spike": lambda f: "סכום לא שגרתי בכרטיס",
}


def narrate(finding: Finding, history_months: int) -> str:
    return _SENTENCES[finding.rule](finding, history_months)


def title(finding: Finding) -> str:
    return f"{_TITLES[finding.rule](finding)} · {finding.subject}"
