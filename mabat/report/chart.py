"""Income vs. expenses column chart as static inline SVG.

Built in code so the HTML report and the PDF show the same picture and the
report needs no JavaScript or network. Pixel geometry uses floats; every
*value* shown as text is formatted from integers.
"""
from __future__ import annotations

from html import escape

from mabat.formatting import div_round

WIDTH, HEIGHT = 640, 250
LEFT, RIGHT, TOP, BOTTOM = 46, 10, 22, 40
BAR_MAX = 24  # px; columns stay thin, the rest of the band is air
PAIR_GAP = 2  # px of surface between the two columns of a month
RADIUS = 4  # px, on the data end only
MAX_TICKS = 5


def _nice_step(span: int) -> int:
    """Smallest round step (1, 2, 2.5 or 5 x 10^k, whole shekels) that covers
    `span` in at most MAX_TICKS steps."""
    magnitude = 1
    while True:
        candidates = [magnitude, 2 * magnitude, 5 * magnitude]
        if magnitude >= 10:
            candidates.insert(2, 25 * magnitude // 10)
        for step in candidates:
            if step * MAX_TICKS >= span:
                return step
        magnitude *= 10


def _axis(values: list[int]) -> tuple[int, int, int]:
    """(bottom, top, step) in shekels, with 0 always on the axis."""
    low, high = min(values + [0]), max(values + [0])
    step = _nice_step(max(high - low, 1))
    top = -(-high // step) * step
    bottom = (low // step) * step
    if top == bottom:
        top = step
    return bottom, top, step


def _column(x: float, width: float, y_value: float, y_zero: float, css: str, tip: str) -> str:
    """A column from the zero line to the value, rounded at the data end only."""
    height = abs(y_zero - y_value)
    r = min(RADIUS, height, width / 2)
    # For a negative value the data end is below the baseline; flip the corner offset.
    s = r if y_value <= y_zero else -r
    d = (
        f"M{x:.1f},{y_zero:.1f} L{x:.1f},{y_value + s:.1f} "
        f"Q{x:.1f},{y_value:.1f} {x + r:.1f},{y_value:.1f} "
        f"L{x + width - r:.1f},{y_value:.1f} "
        f"Q{x + width:.1f},{y_value:.1f} {x + width:.1f},{y_value + s:.1f} "
        f"L{x + width:.1f},{y_zero:.1f} Z"
    )
    return f'<path class="bar {css}" d="{d}"><title>{escape(tip)}</title></path>'


def bar_chart_svg(series: list[dict]) -> str:
    """series: oldest first; each item has label, year, month_label, income,
    expenses (agorot) and income_text / expenses_text."""
    income = [div_round(m["income"], 100) for m in series]
    expenses = [div_round(m["expenses"], 100) for m in series]
    bottom, top, step = _axis(income + expenses)
    thousands = top >= 10_000 or bottom <= -10_000

    plot_w = WIDTH - LEFT - RIGHT
    plot_h = HEIGHT - TOP - BOTTOM

    def y(value: int) -> float:
        return TOP + (top - value) * plot_h / (top - bottom)

    parts = [
        f'<svg class="chart" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" direction="ltr" '
        f'aria-label="גרף עמודות: הכנסות מול הוצאות לפי חודש">'
    ]

    # Gridlines and y ticks: recessive hairlines, the zero line one step stronger.
    for tick in range(bottom, top + 1, step):
        css = "axis-zero" if tick == 0 else "grid"
        label = f"{tick // 1000:,}" if thousands else f"{tick:,}"
        parts.append(f'<line class="{css}" x1="{LEFT}" x2="{WIDTH - RIGHT}" y1="{y(tick):.1f}" y2="{y(tick):.1f}"/>')
        parts.append(f'<text class="tick" x="{LEFT - 8}" y="{y(tick) + 3.5:.1f}" text-anchor="end">{label}</text>')
    unit = "אלפי ₪" if thousands else "₪"
    parts.append(f'<text class="unit" x="{LEFT - 8}" y="{TOP - 10}" text-anchor="end">{unit}</text>')

    band = plot_w / len(series)
    bar_w = min(BAR_MAX, max((band - PAIR_GAP) / 2 - 6, 2))
    y_zero = y(0)
    for i, month in enumerate(series):
        centre = LEFT + band * (i + 0.5)
        x_income = centre - PAIR_GAP / 2 - bar_w
        x_expenses = centre + PAIR_GAP / 2
        parts.append(_column(
            x_income, bar_w, y(income[i]), y_zero, "bar-income",
            f'{month["month_label"]} · הכנסות: {month["income_text"]}',
        ))
        parts.append(_column(
            x_expenses, bar_w, y(expenses[i]), y_zero, "bar-expenses",
            f'{month["month_label"]} · הוצאות: {month["expenses_text"]}',
        ))
        last = " month-current" if i == len(series) - 1 else ""
        parts.append(
            f'<text class="month{last}" x="{centre:.1f}" y="{HEIGHT - BOTTOM + 17}" text-anchor="middle">'
            f'{escape(month["label"])}</text>'
        )
        if i == 0 or month["label"] == "ינואר":
            parts.append(
                f'<text class="year" x="{centre:.1f}" y="{HEIGHT - BOTTOM + 31}" text-anchor="middle">'
                f'{escape(month["year"])}</text>'
            )
    parts.append("</svg>")
    return "".join(parts)
