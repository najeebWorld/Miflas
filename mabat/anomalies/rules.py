"""Rule-based anomaly detection on the normalized ledger.

Every comparison is exact integer arithmetic against the *sum* of the history
months, so no threshold decision depends on a rounded average. `baseline` on a
Finding is the rounded average and is for display only.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path

import pandas as pd
import yaml

from mabat.formatting import div_round, ratio_tenths
from mabat.months import add_months

SEVERITIES = ("red", "orange", "info")
_AGOROT = 100


@dataclass(frozen=True)
class Thresholds:
    history_months: int = 3
    deviation_orange_pct: int = 30
    deviation_red_pct: int = 60
    deviation_min_diff: int = 500 * _AGOROT
    one_off_orange_share_pct: int = 10
    one_off_red_share_pct: int = 25
    sign_flip_min_amount: int = 100 * _AGOROT
    spike_ratio: int = 3
    spike_min_diff: int = 500 * _AGOROT

    @classmethod
    def from_dict(cls, data: dict) -> "Thresholds":
        """Read the nested YAML layout; `*_ils` values are whole shekels."""
        layout = {
            ("history_months",): ("history_months", 1),
            ("category_deviation", "orange_pct"): ("deviation_orange_pct", 1),
            ("category_deviation", "red_pct"): ("deviation_red_pct", 1),
            ("category_deviation", "min_diff_ils"): ("deviation_min_diff", _AGOROT),
            ("one_off", "orange_share_pct"): ("one_off_orange_share_pct", 1),
            ("one_off", "red_share_pct"): ("one_off_red_share_pct", 1),
            ("sign_flip", "min_amount_ils"): ("sign_flip_min_amount", _AGOROT),
            ("account_spike", "ratio"): ("spike_ratio", 1),
            ("account_spike", "min_diff_ils"): ("spike_min_diff", _AGOROT),
        }
        values: dict[str, int] = {}
        for section, content in (data or {}).items():
            items = content.items() if isinstance(content, dict) else [(None, content)]
            for key, value in items:
                path = (section,) if key is None else (section, key)
                if path not in layout:
                    raise ValueError(f"unknown threshold setting: {'.'.join(path)}")
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise ValueError(f"threshold {'.'.join(path)} must be a non-negative integer")
                name, scale = layout[path]
                values[name] = value * scale
        assert set(values) <= {f.name for f in fields(cls)}
        return cls(**values)


def load_thresholds(path: Path | str) -> Thresholds:
    with open(path, encoding="utf-8") as fh:
        return Thresholds.from_dict(yaml.safe_load(fh))


@dataclass(frozen=True)
class Finding:
    rule: str  # category_deviation | missing_recurring | one_off | sign_flip | account_spike
    severity: str  # red | orange | info
    type: str  # income | expense
    subject: str  # category name, or account name for account-level rules
    account: str | None  # account key for account-level rules
    amount: int  # target-month amount, agorot
    baseline: int | None  # rounded average of the history months
    pct_tenths: int | None  # deviation from the average, or share of the month's total


def has_history(ledger: pd.DataFrame, target_month: str, t: Thresholds) -> bool:
    """True when the data starts at least `history_months` before the target."""
    if ledger.empty:
        return False
    return ledger["month"].min() <= add_months(target_month, -t.history_months)


def detect(ledger: pd.DataFrame, target_month: str, t: Thresholds) -> list[Finding]:
    findings = _sign_flips(ledger, target_month, t)
    if has_history(ledger, target_month, t):
        n = t.history_months
        prev = [add_months(target_month, -k) for k in range(n, 0, -1)]
        window = ledger[ledger["month"].isin(prev + [target_month])]
        category_findings = _category_rules(window, target_month, prev, t)
        flagged = {(f.type, f.subject) for f in category_findings}
        findings += category_findings
        findings += _account_spikes(window, target_month, prev, flagged, t)
    return sorted(findings, key=_sort_key)


def _sort_key(f: Finding):
    size = abs(f.amount) if f.amount else abs(f.baseline or 0)
    return (SEVERITIES.index(f.severity), -size, f.subject)


def _monthly(frame: pd.DataFrame, keys: list[str]) -> dict[tuple, dict[str, int]]:
    """{key tuple: {month: amount}} summed over `keys`."""
    out: dict[tuple, dict[str, int]] = {}
    grouped = frame.groupby(keys + ["month"], sort=True)["amount"].sum()
    for index, amount in grouped.items():
        out.setdefault(tuple(index[:-1]), {})[index[-1]] = int(amount)
    return out


def _category_rules(window, target, prev, t: Thresholds) -> list[Finding]:
    n = len(prev)
    month_total = {
        kind: int(window.loc[(window["month"] == target) & (window["type"] == kind), "amount"].sum())
        for kind in ("income", "expense")
    }
    findings = []
    for (kind, category), by_month in _monthly(window, ["type", "category"]).items():
        current = by_month.get(target, 0)
        history = [by_month.get(m, 0) for m in prev]
        total = sum(history)

        if all(h == 0 for h in history):
            share_base = month_total[kind]
            if current > 0 and share_base > 0 and current * 100 > t.one_off_orange_share_pct * share_base:
                red = current * 100 > t.one_off_red_share_pct * share_base
                findings.append(Finding(
                    "one_off", "red" if red else "orange", kind, category, None,
                    current, None, ratio_tenths(current, share_base),
                ))
            continue

        if kind == "expense" and current == 0 and all(h > 0 for h in history):
            findings.append(Finding(
                "missing_recurring", "orange", kind, category, None, 0, div_round(total, n), None,
            ))
            continue

        if total <= 0:
            continue
        gap = n * current - total  # n x (current - average)
        if abs(gap) * 100 > t.deviation_orange_pct * total and abs(gap) > n * t.deviation_min_diff:
            favourable = (gap > 0) == (kind == "income")
            if favourable:
                severity = "info"
            elif abs(gap) * 100 > t.deviation_red_pct * total:
                severity = "red"
            else:
                severity = "orange"
            findings.append(Finding(
                "category_deviation", severity, kind, category, None,
                current, div_round(total, n), ratio_tenths(gap, total),
            ))
    return findings


def _sign_flips(ledger, target, t: Thresholds) -> list[Finding]:
    rows = ledger[(ledger["month"] == target) & (ledger["amount"] <= -t.sign_flip_min_amount)]
    return [
        Finding("sign_flip", "orange", r.type, r.account_name, r.account, int(r.amount), None, None)
        for r in rows.itertuples()
    ]


def _account_spikes(window, target, prev, flagged, t: Thresholds) -> list[Finding]:
    n = len(prev)
    findings = []
    keys = ["type", "category", "account", "account_name"]
    for (kind, category, account, name), by_month in _monthly(window, keys).items():
        if (kind, category) in flagged:
            continue
        current = by_month.get(target, 0)
        total = sum(by_month.get(m, 0) for m in prev)
        if total > 0 and n * current > t.spike_ratio * total and n * current - total > n * t.spike_min_diff:
            findings.append(Finding(
                "account_spike", "info", kind, name, account, current, div_round(total, n), None,
            ))
    return findings
