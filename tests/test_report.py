import html as html_lib
import json
import re
from datetime import datetime

import pytest

from mabat.config import load_config
from mabat.ingest.parser import parse_export
from mabat.ingest.validate import validate_export
from mabat.normalize.ledger import build_ledger
from mabat.pipeline import build_context
from mabat.report.chart import bar_chart_svg
from mabat.report.render import render_report

NOW = datetime(2026, 7, 1, 10, 30)
FOOTER = 'נוצר אוטומטית · לבדיקת רו"ח לפני שליחה ללקוח'


@pytest.fixture(scope="module")
def config():
    return load_config()


@pytest.fixture
def loaded(sample_dir, config):
    parsed = parse_export(sample_dir, config.fieldmap)
    warnings = validate_export(parsed)
    return parsed, build_ledger(parsed, config.classification), warnings


def context_for(loaded, config, month):
    parsed, ledger, warnings = loaded
    return build_context(parsed, ledger, warnings, month, config.thresholds, NOW)


def text_of(page: str) -> str:
    return html_lib.unescape(page)


# ---- context ----

def test_june_context_values(loaded, config):
    ctx = context_for(loaded, config, "2026-06")
    assert ctx["month"] == "2026-06" and ctx["month_label"] == "יוני 2026"
    assert ctx["client"] == {
        "vat_id": "514000017",
        "business_name": 'סטודיו אלון עיצוב בע"מ',
        "software_name": "תוכנת דמה",
        "tax_year": 2026,
    }
    kpis = {k["key"]: k for k in ctx["kpis"]}
    assert kpis["income"]["value"] == 11_350_000 and kpis["income"]["value_text"] == "₪113,500"
    assert kpis["expenses"]["value_text"] == "₪77,850"
    assert kpis["profit"]["value_text"] == "₪35,650"
    assert kpis["income"]["change"] == {
        "diff": 1_750_000, "diff_text": "+₪17,500", "pct_text": "18.2%", "direction": "up", "tone": "good",
    }
    assert kpis["expenses"]["change"]["tone"] == "bad"
    assert kpis["expenses"]["change"]["pct_text"] == "6.3%"
    assert kpis["profit"]["change"]["diff_text"] == "+₪12,870"
    assert ctx["margin_text"] == "31.4%"
    assert ctx["previous_label"] == "מאי 2026"
    assert len(ctx["series"]) == 6
    assert ctx["generated_at"] == "2026-07-01T10:30"


def test_june_context_findings_and_status(loaded, config):
    ctx = context_for(loaded, config, "2026-06")
    assert [f["severity"] for f in ctx["findings"]] == ["red", "orange", "orange", "orange", "info"]
    assert ctx["severity_counts"] == {"red": 1, "orange": 3, "info": 1}
    assert ctx["findings"][0]["title"] == "חריגה בקטגוריה · שיווק ופרסום"
    assert "₪7,200" in ctx["findings"][0]["text"]
    assert ctx["warnings"] == []
    assert ctx["status"] == "needs_review"


def test_may_is_ready(loaded, config):
    ctx = context_for(loaded, config, "2026-05")
    assert ctx["findings"] == [] and ctx["warnings"] == []
    assert ctx["status"] == "ready"


def test_month_without_history_gets_a_warning(loaded, config):
    ctx = context_for(loaded, config, "2026-03")
    assert len(ctx["warnings"]) == 1 and "3 חודשי" in ctx["warnings"][0]
    assert ctx["status"] == "needs_review"


def test_first_month_has_no_change(loaded, config):
    ctx = context_for(loaded, config, "2026-01")
    assert all(k["change"] is None for k in ctx["kpis"])
    assert ctx["previous_label"] is None


def test_validation_warnings_reach_the_context(loaded, config):
    parsed, ledger, _ = loaded
    ctx = build_context(parsed, ledger, ["אזהרה לדוגמה"], "2026-05", config.thresholds, NOW)
    assert ctx["warnings"] == ["אזהרה לדוגמה"]
    assert ctx["status"] == "needs_review"


def test_context_is_json_serializable(loaded, config):
    ctx = context_for(loaded, config, "2026-06")
    assert json.loads(json.dumps(ctx, ensure_ascii=False)) == ctx


# ---- HTML ----

def test_june_report_html(loaded, config):
    page = render_report(context_for(loaded, config, "2026-06"), reviewed=False)
    text = text_of(page)
    assert '<html lang="he" dir="rtl">' in page
    assert 'סטודיו אלון עיצוב בע"מ' in text
    assert "יוני 2026" in text
    for figure in ("₪113,500", "₪77,850", "₪35,650", "18.2%", "6.3%", "56.5%", "31.4%"):
        assert figure in text, figure
    assert FOOTER in text
    assert "<svg" in page
    assert len(re.findall(r'class="finding finding-red"', page)) == 1
    assert len(re.findall(r'class="finding finding-orange"', page)) == 3
    assert len(re.findall(r'class="finding finding-info"', page)) == 1
    assert "דורש בדיקה" in text


def test_report_loads_nothing_from_the_network(loaded, config):
    page = render_report(context_for(loaded, config, "2026-06"), reviewed=False)
    assert "http://" not in page and "https://" not in page
    assert "<script" not in page and "@import" not in page and "url(" not in page


def test_draft_stamp_until_reviewed(loaded, config):
    ctx = context_for(loaded, config, "2026-06")
    assert "טיוטה" in render_report(ctx, reviewed=False)
    reviewed = render_report(ctx, reviewed=True, reviewed_at="2026-07-02T09:00")
    assert "טיוטה" not in reviewed
    assert "נסקר" in reviewed and "02/07/2026" in reviewed
    assert FOOTER in text_of(reviewed)


def test_clean_month_says_so(loaded, config):
    text = text_of(render_report(context_for(loaded, config, "2026-05"), reviewed=False))
    assert "לא זוהו חריגות" in text
    assert "מוכן" in text


def test_warnings_are_shown(loaded, config):
    text = text_of(render_report(context_for(loaded, config, "2026-03"), reviewed=False))
    assert "3 חודשי" in text


def test_text_from_the_export_is_escaped(loaded, config):
    ctx = context_for(loaded, config, "2026-06")
    ctx["client"]["business_name"] = "<script>alert(1)</script>"
    page = render_report(ctx, reviewed=False)
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


# ---- chart ----

def series(*pairs):
    return [
        {"month": f"2026-{i:02d}", "label": f"חודש {i}", "year": "2026", "month_label": f"חודש {i} 2026",
         "income": inc, "expenses": exp, "income_text": f"₪{inc // 100:,}", "expenses_text": f"₪{exp // 100:,}"}
        for i, (inc, exp) in enumerate(pairs, start=1)
    ]


def test_chart_has_two_bars_per_month():
    svg = bar_chart_svg(series((10_000_00, 8_000_00), (12_000_00, 9_000_00), (11_000_00, 9_500_00)))
    assert svg.startswith("<svg")
    assert svg.count('class="bar bar-income"') == 3
    assert svg.count('class="bar bar-expenses"') == 3
    assert svg.count("<title>") == 6
    assert "http" not in svg


def test_chart_axis_uses_thousands_for_large_values():
    svg = bar_chart_svg(series((113_500_00, 77_850_00)))
    assert "אלפי ₪" in svg
    assert ">125<" in svg and ">0<" in svg


def test_chart_axis_uses_shekels_for_small_values():
    svg = bar_chart_svg(series((4_200_00, 3_100_00)))
    assert "אלפי" not in svg
    assert ">5,000<" in svg


def test_chart_handles_all_zero_and_negative_values():
    assert "<svg" in bar_chart_svg(series((0, 0)))
    svg = bar_chart_svg(series((5_000_00, -2_000_00)))
    assert svg.count('class="bar bar-expenses"') == 1
    assert ">-2,000<" in svg


def test_figures_in_sentences_are_direction_isolated(loaded, config):
    page = render_report(context_for(loaded, config, "2026-06"), reviewed=False)
    assert 'הסתכמו ב-<span class="num">₪7,200</span>' in page
    assert 'גבוה ב-<span class="num">81.5%</span>' in page
    assert 'של <span class="num">₪150</span>' in page


def test_isolate_figures_keeps_real_minus_signs():
    from mabat.report.render import isolate_figures

    assert isolate_figures("הפרש של -₪150 החודש") == 'הפרש של <span class="num">-₪150</span> החודש'
    assert isolate_figures("(-12.5%)") == '(<span class="num">-12.5%</span>)'
    assert isolate_figures("ב-3 החודשים") == "ב-3 החודשים"
    assert isolate_figures("<b>") == "&lt;b&gt;"
