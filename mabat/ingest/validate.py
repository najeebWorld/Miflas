"""Cross-record integrity checks on a parsed export.

A failed integrity check raises ValidationError: the pipeline stops rather
than report on data it cannot account for. Softer inconsistencies come back
as Hebrew warning strings and mark the report "needs review".
"""
from __future__ import annotations

from collections import Counter

from mabat.errors import ValidationError
from mabat.ingest.encoding import declared_codec
from mabat.ingest.parser import BKMV, INI
from mabat.models import ParsedExport

_MAX_LISTED = 5


def validate_export(parsed: ParsedExport) -> list[str]:
    _check_order(parsed)
    _check_sequence(parsed)
    _check_counts(parsed)
    _check_primary_id(parsed)
    _check_accounts_exist(parsed)
    return _charset_warnings(parsed) + _account_total_warnings(parsed)


def _check_order(p: ParsedExport) -> None:
    if not p.record_codes or p.record_codes[0] != "A100":
        raise ValidationError("רשומת הפתיחה A100 חייבת להיות הרשומה הראשונה", file=BKMV, line=1)
    if p.record_codes[-1] != "Z900":
        raise ValidationError(
            "רשומת הסגירה Z900 חייבת להיות הרשומה האחרונה", file=BKMV, line=len(p.record_codes)
        )
    counts = Counter(p.record_codes)
    for code in ("A100", "Z900"):
        if counts[code] != 1:
            raise ValidationError(f"נמצאו {counts[code]} רשומות {code}; מותרת אחת בלבד", file=BKMV)


def _check_sequence(p: ParsedExport) -> None:
    for i in range(1, len(p.record_numbers)):
        expected = p.record_numbers[i - 1] + 1
        if p.record_numbers[i] != expected:
            raise ValidationError(
                f"מספר הרשומה אינו רציף: נמצא {p.record_numbers[i]}, צפוי {expected}",
                file=BKMV, line=i + 1,
            )


def _check_counts(p: ParsedExport) -> None:
    actual = Counter(p.record_codes)
    total = len(p.record_codes)
    if p.header.total_records != total:
        raise ValidationError(
            f"שדה 1002 מצהיר על {p.header.total_records} רשומות, אך בקובץ הנתונים יש {total}",
            file=INI, line=1,
        )
    if p.closing_total != total:
        raise ValidationError(
            f"שדה 1155 ברשומת הסגירה מצהיר על {p.closing_total} רשומות, אך בקובץ יש {total}",
            file=BKMV, line=total,
        )
    for code, declared in sorted(p.ini_counts.items()):
        if actual.get(code, 0) != declared:
            raise ValidationError(
                f"רשומת הסיכום מצהירה על {declared} רשומות {code}, אך בקובץ הנתונים יש {actual.get(code, 0)}",
                file=INI,
            )
    for code in sorted(actual):
        if code not in ("A100", "Z900") and code not in p.ini_counts:
            raise ValidationError(
                f"בקובץ הנתונים יש {actual[code]} רשומות {code}, אך אין להן רשומת סיכום", file=INI
            )


def _check_primary_id(p: ParsedExport) -> None:
    if len(set(p.primary_ids.values())) != 1:
        detail = ", ".join(f"{k}: {v}" for k, v in sorted(p.primary_ids.items()))
        raise ValidationError(f"מזהה ראשי אינו זהה בכל הרשומות ({detail})")


def _check_accounts_exist(p: ParsedExport) -> None:
    known = {a.key for a in p.accounts}
    for m in p.movements:
        if m.account_key not in known:
            raise ValidationError(
                f"תנועה מפנה לחשבון {m.account_key!r} שאין לו רשומת B110", file=BKMV, line=m.line
            )


def _charset_warnings(p: ParsedExport) -> list[str]:
    declared = declared_codec(p.header.declared_charset)
    if declared == p.encoding or (declared is None and p.header.declared_charset == ""):
        return []
    names = {"cp1255": "ISO-8859-8", "cp862": "CP-862", "utf-8": "UTF-8", "utf-8-sig": "UTF-8"}
    return [
        f"סט התווים שזוהה ({names[p.encoding]}) שונה מהמוצהר בשדה 1029 "
        f"({p.header.declared_charset or 'ריק'}). הקובץ פוענח לפי הזיהוי."
    ]


def _account_total_warnings(p: ParsedExport) -> list[str]:
    debit: Counter[str] = Counter()
    credit: Counter[str] = Counter()
    for m in p.movements:
        (debit if m.is_debit else credit)[m.account_key] += m.amount
    off = [
        a.key for a in p.accounts
        if debit[a.key] != a.total_debit or credit[a.key] != a.total_credit
    ]
    if not off:
        return []
    listed = ", ".join(off[:_MAX_LISTED]) + (" ועוד" if len(off) > _MAX_LISTED else "")
    return [
        f"סכום התנועות אינו תואם את סה\"כ החובה/זכות ברשומת החשבון (שדות 1415, 1416) "
        f"ב-{len(off)} חשבונות: {listed}."
    ]
