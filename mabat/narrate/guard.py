"""Keeps any future language model from introducing a number.

A narrator may reword a finding, but every numeric token in its text must be
one the code computed for that finding. Otherwise the deterministic template
is used instead. Stage 1 ships no model; the guard exists so one can only be
plugged in behind it.
"""
from __future__ import annotations

import re
from typing import Callable

from mabat.anomalies.rules import Finding
from mabat.formatting import ils, pct
from mabat.narrate.templates import narrate

_NUMBER = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")


def numbers_in(text: str) -> set[str]:
    """Numeric tokens in the text, thousands separators removed."""
    return {token.replace(",", "") for token in _NUMBER.findall(text)}


def allowed_numbers(finding: Finding, history_months: int) -> set[str]:
    """Every number that may legitimately appear in a sentence about the finding."""
    shown = [str(history_months), finding.subject, finding.account or "", ils(finding.amount)]
    if finding.baseline is not None:
        shown.append(ils(finding.baseline))
    if finding.pct_tenths is not None:
        shown.append(pct(finding.pct_tenths))
    return set().union(*(numbers_in(s) for s in shown))


def safe_narrate(
    finding: Finding,
    history_months: int,
    narrator: Callable[[Finding], str] | None = None,
) -> str:
    template = narrate(finding, history_months)
    if narrator is None:
        return template
    try:
        text = (narrator(finding) or "").strip()
    except Exception:
        return template
    if not text or not numbers_in(text) <= allowed_numbers(finding, history_months):
        return template
    return text
