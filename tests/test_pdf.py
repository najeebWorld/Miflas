import shutil
import subprocess
from datetime import datetime

import pytest

from mabat.config import load_config
from mabat.ingest.parser import parse_export
from mabat.ingest.validate import validate_export
from mabat.normalize.ledger import build_ledger
from mabat.pipeline import build_context
from mabat.report.pdf import html_to_pdf, html_to_pdf_bytes
from mabat.report.render import render_report


@pytest.fixture
def june_html(sample_dir):
    config = load_config()
    parsed = parse_export(sample_dir, config.fieldmap)
    warnings = validate_export(parsed)
    ledger = build_ledger(parsed, config.classification)
    ctx = build_context(parsed, ledger, warnings, "2026-06", config.thresholds, datetime(2026, 7, 1, 10, 30))
    return render_report(ctx, reviewed=False)


def test_pdf_file_is_written(june_html, tmp_path):
    out = tmp_path / "nested" / "report.pdf"
    html_to_pdf(june_html, out)
    data = out.read_bytes()
    assert data.startswith(b"%PDF")
    assert len(data) > 5_000


def test_pdf_bytes_match_file_output(june_html):
    assert html_to_pdf_bytes(june_html).startswith(b"%PDF")


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="pdftotext not installed")
def test_pdf_contains_the_report_figures(june_html, tmp_path):
    out = tmp_path / "report.pdf"
    html_to_pdf(june_html, out)
    text = subprocess.run(["pdftotext", str(out), "-"], capture_output=True, text=True, check=True).stdout
    assert "113,500" in text and "77,850" in text and "35,650" in text
