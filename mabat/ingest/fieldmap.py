"""Config-driven fixed-width record layout for OPENFRMT files.

Positions come from config/fieldmap.yaml, transcribed from the official spec.
Nothing in the code knows a column number.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Field:
    id: int
    name: str
    start: int  # 1-based, inclusive
    end: int  # 1-based, inclusive
    type: str  # alnum | num | amount

    @property
    def width(self) -> int:
        return self.end - self.start + 1


class FieldMap:
    def __init__(self, records: dict[str, dict], common: dict[str, dict]):
        self._code_span = (common["record_code"]["start"] - 1, common["record_code"]["end"])
        self._number_span = (common["record_number"]["start"] - 1, common["record_number"]["end"])
        self._lengths: dict[str, int] = {}
        self._fields: dict[str, list[Field]] = {}
        for code, spec in records.items():
            self._lengths[code] = int(spec["length"])
            if spec.get("fields"):
                self._fields[code] = [Field(**f) for f in spec["fields"]]

    def codes(self) -> list[str]:
        return list(self._lengths)

    def data_codes(self) -> list[str]:
        """Record codes that may appear in BKMVDATA.TXT."""
        return [c for c in self._lengths if c not in ("A000", "SUMMARY")]

    def length(self, code: str) -> int:
        return self._lengths[code]

    def fields(self, code: str) -> list[Field]:
        return self._fields[code]

    def record_code(self, line: str) -> str:
        """Record type code of a BKMVDATA line."""
        return line[self._code_span[0] : self._code_span[1]]

    def record_number(self, line: str) -> str:
        """Running record number of a BKMVDATA line (raw text)."""
        return line[self._number_span[0] : self._number_span[1]]

    def build_count_only(self, code: str, record_number: int) -> str:
        """A blank record of a type we count but do not decode (C100, D110...)."""
        width = self._number_span[1] - self._number_span[0]
        head = code + str(record_number).zfill(width)
        return head.ljust(self._lengths[code])

    def slice_record(self, code: str, line: str) -> dict[str, str]:
        """Cut a decoded line into {field name: stripped raw text}."""
        return {f.name: line[f.start - 1 : f.end].strip() for f in self._fields[code]}

    def build_record(self, code: str, values: dict[str, object]) -> str:
        """Inverse of slice_record: format values into one fixed-width line.

        Used by the sample generator and by tests. Missing fields get the
        spec's filler: spaces for alnum, zeros for num, +0 for amounts.
        """
        unknown = set(values) - {f.name for f in self._fields[code]} - {"record_code"}
        if unknown:
            raise KeyError(f"{code}: unknown fields {sorted(unknown)}")
        parts = []
        for f in self._fields[code]:
            if f.name == "record_code" and code != "SUMMARY":
                value = code  # a SUMMARY record carries the code of the type it counts
            else:
                value = values.get(f.name)
            parts.append(_format(f, value))
        line = "".join(parts)
        assert len(line) == self._lengths[code]
        return line


def _format(f: Field, value: object) -> str:
    if f.type == "amount":
        number = int(value or 0)
        text = ("-" if number < 0 else "+") + str(abs(number)).zfill(f.width - 1)
    elif f.type == "num":
        text = str(value if value is not None else "").zfill(f.width)
    else:
        text = str(value if value is not None else "").ljust(f.width)
    if len(text) != f.width:
        raise ValueError(f"field {f.id} ({f.name}): {value!r} does not fit in {f.width} chars")
    return text


def load_fieldmap(path: Path | str) -> FieldMap:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return FieldMap(data["records"], data["bkmvdata_common"])
