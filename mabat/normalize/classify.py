"""Account -> (type, category), driven by config/classification.yaml."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from mabat.models import Account

TYPES = ("income", "expense", "balance_sheet")
DATE_FIELDS = ("date", "value_date")
_MATCHERS = ("account_key", "tb_code", "tb_code_range", "code_6111_range")


@dataclass(frozen=True)
class Rule:
    type: str
    category: str | None
    account_keys: frozenset[str] | None = None
    tb_codes: frozenset[str] | None = None
    tb_code_range: tuple[int, int] | None = None
    code_6111_range: tuple[int, int] | None = None

    def matches(self, a: Account) -> bool:
        if self.account_keys is not None and a.key not in self.account_keys:
            return False
        if self.tb_codes is not None and a.tb_code not in self.tb_codes:
            return False
        if self.tb_code_range is not None and not _in_range(a.tb_code, self.tb_code_range):
            return False
        if self.code_6111_range is not None and not _in_range(a.code_6111, self.code_6111_range):
            return False
        return True


def _in_range(code: str, bounds: tuple[int, int]) -> bool:
    return code.isdigit() and bounds[0] <= int(code) <= bounds[1]


@dataclass(frozen=True)
class Classification:
    date_field: str
    rules: tuple[Rule, ...]

    def classify(self, a: Account) -> tuple[str, str] | None:
        """(type, category) from the first matching rule, or None."""
        for rule in self.rules:
            if rule.matches(a):
                return rule.type, rule.category or a.tb_desc or a.name
        return None

    @classmethod
    def from_dict(cls, data: dict) -> "Classification":
        date_field = (data.get("period") or {}).get("date_field", "date")
        if date_field not in DATE_FIELDS:
            raise ValueError(f"period.date_field must be one of {DATE_FIELDS}, got {date_field!r}")
        return cls(date_field, tuple(_rule(i, r) for i, r in enumerate(data.get("rules") or [], 1)))


def _rule(index: int, raw: dict) -> Rule:
    where = f"classification rule #{index}"
    if raw.get("type") not in TYPES:
        raise ValueError(f"{where}: type must be one of {TYPES}, got {raw.get('type')!r}")
    match = raw.get("match") or {}
    if not match:
        raise ValueError(f"{where}: match is empty")
    unknown = set(match) - set(_MATCHERS)
    if unknown:
        raise ValueError(f"{where}: unknown match keys {sorted(unknown)}")

    def keys(name: str) -> frozenset[str] | None:
        return frozenset(str(v) for v in match[name]) if name in match else None

    def bounds(name: str) -> tuple[int, int] | None:
        return (int(match[name]["from"]), int(match[name]["to"])) if name in match else None

    return Rule(
        type=raw["type"],
        category=raw.get("category"),
        account_keys=keys("account_key"),
        tb_codes=keys("tb_code"),
        tb_code_range=bounds("tb_code_range"),
        code_6111_range=bounds("code_6111_range"),
    )


def load_classification(path: Path | str) -> Classification:
    with open(path, encoding="utf-8") as fh:
        return Classification.from_dict(yaml.safe_load(fh))
