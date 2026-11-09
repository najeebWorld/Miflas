import shutil
from datetime import datetime

import pytest

from mabat.cli import main
from mabat.config import load_config
from mabat.errors import ValidationError
from mabat.pipeline import discover_exports, run_folder
from mabat.store.db import ReportStore
from tests.conftest import read_lines, write_lines

NOW = datetime(2026, 7, 1, 10, 30)


@pytest.fixture(scope="module")
def config():
    return load_config()


# ---- run_folder ----

def test_default_is_the_latest_month(sample_dir, config):
    contexts = run_folder(sample_dir, config, now=NOW)
    assert [c["month"] for c in contexts] == ["2026-06"]
    assert contexts[0]["status"] == "needs_review"


def test_all_months(sample_dir, config):
    contexts = run_folder(sample_dir, config, all_months=True, now=NOW)
    assert [c["month"] for c in contexts] == [f"2026-0{m}" for m in range(1, 7)]
    by_month = {c["month"]: c for c in contexts}
    assert by_month["2026-05"]["status"] == "ready"
    assert by_month["2026-04"]["status"] == "ready"
    assert by_month["2026-03"]["status"] == "needs_review" and by_month["2026-03"]["warnings"]


def test_specific_month(sample_dir, config):
    contexts = run_folder(sample_dir, config, month="2026-05", now=NOW)
    assert [(c["month"], c["status"]) for c in contexts] == [("2026-05", "ready")]


def test_month_without_data_stops(sample_dir, config):
    with pytest.raises(ValidationError, match="2026-09"):
        run_folder(sample_dir, config, month="2026-09", now=NOW)


def test_validation_warning_marks_every_report(sample_dir, config):
    path = sample_dir / "INI.TXT"
    lines = read_lines(path)
    lines[0] = lines[0][:395] + "2" + lines[0][396:]  # declare CP-862 on an ISO file
    write_lines(path, lines)
    contexts = run_folder(sample_dir, config, month="2026-05", now=NOW)
    assert contexts[0]["status"] == "needs_review"
    assert "1029" in contexts[0]["warnings"][0]


# ---- discover_exports ----

def test_discover_from_root_and_from_the_folder_itself(sample_dir, tmp_path):
    root = tmp_path / "clients"
    shutil.copytree(sample_dir, root / "OPENFRMT" / "51400001.26" / "07011000")
    shutil.copytree(sample_dir, root / "OPENFRMT" / "51400002.26" / "07011000")
    (root / "OPENFRMT" / "51400002.26" / "07011000" / "INI.TXT").rename(
        root / "OPENFRMT" / "51400002.26" / "07011000" / "ini.txt"
    )
    found = discover_exports(root)
    assert [p.parent.name for p in found] == ["51400001.26", "51400002.26"]
    assert discover_exports(sample_dir) == [sample_dir]
    assert discover_exports(tmp_path / "missing") == []


# ---- store ----

def test_store_upsert_list_get_review(sample_dir, config, tmp_path):
    store = ReportStore(tmp_path / "db" / "mabat.db")
    june, = run_folder(sample_dir, config, now=NOW)
    may, = run_folder(sample_dir, config, month="2026-05", now=NOW)
    june_id, may_id = store.upsert(june), store.upsert(may)
    assert june_id != may_id

    rows = store.list()
    assert [(r["month"], r["status"], r["reviewed_at"]) for r in rows] == [
        ("2026-06", "needs_review", None),
        ("2026-05", "ready", None),
    ]
    assert rows[0]["business_name"] == 'סטודיו אלון עיצוב בע"מ'
    assert rows[0]["severity_counts"] == {"red": 1, "orange": 3, "info": 1}

    record = store.get(june_id)
    assert record["context"] == june and record["reviewed_at"] is None
    assert store.get(9999) is None

    assert store.mark_reviewed(june_id, datetime(2026, 7, 2, 9, 0)) is True
    assert store.get(june_id)["reviewed_at"] == "2026-07-02T09:00"
    assert store.mark_reviewed(9999, NOW) is False


def test_regenerating_a_report_replaces_it_and_clears_the_review(sample_dir, config, tmp_path):
    store = ReportStore(tmp_path / "mabat.db")
    june, = run_folder(sample_dir, config, now=NOW)
    first = store.upsert(june)
    store.mark_reviewed(first, NOW)
    again = store.upsert(june)
    assert again == first
    assert len(store.list()) == 1
    assert store.get(first)["reviewed_at"] is None


# ---- CLI ----

def test_cli_run_writes_html_and_records_the_report(sample_dir, tmp_path, capsys):
    out = tmp_path / "out"
    code = main(["run", str(sample_dir), "--out", str(out), "--no-pdf"])
    assert code == 0
    html = (out / "514000017_2026-06.html").read_text(encoding="utf-8")
    assert "₪113,500" in html and "טיוטה" in html
    assert not (out / "514000017_2026-06.pdf").exists()
    assert [r["month"] for r in ReportStore(out / "mabat.db").list()] == ["2026-06"]
    printed = capsys.readouterr().out
    assert "יוני 2026" in printed and "דורש בדיקה" in printed


def test_cli_run_writes_pdf_by_default(sample_dir, tmp_path):
    out = tmp_path / "out"
    assert main(["run", str(sample_dir), "--out", str(out), "--month", "2026-05"]) == 0
    assert (out / "514000017_2026-05.pdf").read_bytes().startswith(b"%PDF")


def test_cli_all_months(sample_dir, tmp_path):
    out = tmp_path / "out"
    assert main(["run", str(sample_dir), "--out", str(out), "--no-pdf", "--all-months"]) == 0
    assert len(list(out.glob("*.html"))) == 6


def test_cli_one_bad_export_does_not_stop_the_others(sample_dir, tmp_path, capsys):
    root = tmp_path / "clients"
    good, bad = root / "a_good", root / "b_bad"
    shutil.copytree(sample_dir, good)
    shutil.copytree(sample_dir, bad)
    lines = read_lines(bad / "BKMVDATA.TXT")
    lines[9] = lines[9][:-5]
    write_lines(bad / "BKMVDATA.TXT", lines)

    out = tmp_path / "out"
    code = main(["run", str(root), "--out", str(out), "--no-pdf"])
    assert code == 1
    assert (out / "514000017_2026-06.html").exists()
    err = capsys.readouterr().err
    assert "b_bad" in err and "שורה 10" in err


def test_cli_without_any_export_fails(tmp_path, capsys):
    assert main(["run", str(tmp_path), "--out", str(tmp_path / "out")]) == 2
    assert "INI.TXT" in capsys.readouterr().err


def test_cli_rejects_a_malformed_month(sample_dir, tmp_path):
    with pytest.raises(SystemExit):
        main(["run", str(sample_dir), "--out", str(tmp_path), "--month", "June"])


def test_cli_sample_command(tmp_path, capsys):
    assert main(["sample", str(tmp_path)]) == 0
    assert (tmp_path / "OPENFRMT" / "51400001.26" / "07011000" / "INI.TXT").exists()
