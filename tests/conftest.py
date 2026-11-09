from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from mabat.config import DEFAULT_CONFIG_DIR
from mabat.ingest.fieldmap import FieldMap, load_fieldmap
from mabat.sampledata import write_sample


@pytest.fixture(scope="session")
def fm() -> FieldMap:
    return load_fieldmap(DEFAULT_CONFIG_DIR / "fieldmap.yaml")


@pytest.fixture(scope="session")
def _sample_master(tmp_path_factory, fm) -> Path:
    return write_sample(tmp_path_factory.mktemp("sample"), fm=fm)


@pytest.fixture
def sample_dir(_sample_master, tmp_path) -> Path:
    """A private, writable copy of the sample export folder."""
    target = tmp_path / "export"
    shutil.copytree(_sample_master, target)
    return target


def read_lines(path: Path, encoding: str = "iso8859_8") -> list[str]:
    return path.read_bytes().decode(encoding).split("\r\n")[:-1]


def write_lines(path: Path, lines: list[str], encoding: str = "iso8859_8") -> None:
    path.write_bytes("".join(line + "\r\n" for line in lines).encode(encoding))


def patch_line(fm: FieldMap, code: str, line: str, **overrides) -> str:
    """Rebuild a fixed-width line with some fields replaced."""
    values: dict[str, object] = dict(fm.slice_record(code, line))
    values.pop("record_code", None) if code != "SUMMARY" else None
    for f in fm.fields(code):
        if f.type == "amount" and f.name in values:
            values[f.name] = int(values[f.name])
    values.update(overrides)
    return fm.build_record(code, values)


def find_line(fm: FieldMap, lines: list[str], code: str, **match) -> int:
    """Index of the first line of `code` whose sliced fields equal `match`."""
    for i, line in enumerate(lines):
        if fm.record_code(line) != code:
            continue
        values = fm.slice_record(code, line)
        if all(values[k] == v for k, v in match.items()):
            return i
    raise AssertionError(f"no {code} line matching {match}")
