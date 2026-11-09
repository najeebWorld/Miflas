from mabat.formatting import ils, month_label, pct, ratio_tenths


def test_ils_rounds_to_whole_shekels_half_up():
    assert ils(1234567) == "₪12,346"
    assert ils(1234549) == "₪12,345"
    assert ils(1234550) == "₪12,346"
    assert ils(0) == "₪0"


def test_ils_negative():
    assert ils(-15000) == "-₪150"
    assert ils(-1234550) == "-₪12,346"


def test_pct():
    assert pct(315) == "31.5%"
    assert pct(-63) == "-6.3%"
    assert pct(0) == "0.0%"
    assert pct(1000) == "100.0%"


def test_ratio_tenths_rounds_half_away_from_zero():
    assert ratio_tenths(1, 3) == 333
    assert ratio_tenths(2, 3) == 667
    assert ratio_tenths(1, 2000) == 1  # 0.05% -> 0.1%
    assert ratio_tenths(-1, 2000) == -1
    assert ratio_tenths(1, -2000) == -1
    assert ratio_tenths(35650, 113500) == 314


def test_ratio_tenths_zero_denominator():
    assert ratio_tenths(5, 0) is None


def test_month_label():
    assert month_label("2026-06") == "יוני 2026"
    assert month_label("2025-12") == "דצמבר 2025"
