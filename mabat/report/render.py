"""Report context -> self-contained HTML (RTL Hebrew, no network, no scripts)."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from mabat.report.chart import bar_chart_svg

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

# Amounts and percentages inside Hebrew sentences. Without isolation the
# bidi algorithm may place the currency or percent sign on the wrong side.
# A hyphen counts as a minus sign only at the start of a word: in "ב-₪7,200"
# it belongs to the Hebrew prefix, not to the number.
_SIGN = r"(?:(?<![^\s(])-)?"
_DIGITS = r"\d+(?:,\d{3})*"
_FIGURE = re.compile(_SIGN + "₪" + _DIGITS + "|" + _SIGN + _DIGITS + r"(?:\.\d+)?%")


def isolate_figures(text: str) -> Markup:
    """Escape the text and wrap each figure in a left-to-right isolate."""
    escaped = str(escape(text))
    return Markup(_FIGURE.sub(lambda m: f'<span class="num">{m.group(0)}</span>', escaped))


_env.filters["figures"] = isolate_figures

STATUS_LABELS = {"ready": "מוכן", "needs_review": "דורש בדיקה"}


def display_datetime(iso: str | None) -> str:
    """'2026-07-01T10:30' -> '01/07/2026 10:30'."""
    if not iso:
        return ""
    return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M")


def render_report(context: dict, reviewed: bool, reviewed_at: str | None = None) -> str:
    template = _env.get_template("report.html.j2")
    return template.render(
        c=context,
        reviewed=reviewed,
        reviewed_at_text=display_datetime(reviewed_at),
        generated_at_text=display_datetime(context["generated_at"]),
        status_label=STATUS_LABELS[context["status"]],
        chart=Markup(bar_chart_svg(context["series"])),
    )
