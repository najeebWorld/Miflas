import pytest

from mabat.anomalies.rules import Finding
from mabat.narrate.guard import allowed_numbers, numbers_in, safe_narrate
from mabat.narrate.templates import narrate, title

DEVIATION_UP = Finding("category_deviation", "red", "expense", "שיווק ופרסום", None, 720_000, 396_667, 815)
DEVIATION_DOWN = Finding("category_deviation", "red", "income", "הכנסות", None, 300_000, 1_000_000, -700)
MISSING = Finding("missing_recurring", "orange", "expense", "ביטוחים", None, 0, 115_000, None)
ONE_OFF = Finding("one_off", "orange", "income", "הכנסות אחרות", None, 1_500_000, None, 132)
SIGN_FLIP = Finding("sign_flip", "orange", "expense", "ציוד משרדי", "6500", -15_000, None, None)
SPIKE = Finding("account_spike", "info", "expense", "חשמל ומים", "6110", 290_000, 85_667, None)
ALL = [DEVIATION_UP, DEVIATION_DOWN, MISSING, ONE_OFF, SIGN_FLIP, SPIKE]


def test_deviation_up_sentence():
    assert narrate(DEVIATION_UP, 3) == (
        'ההוצאות בקטגוריה "שיווק ופרסום" הסתכמו ב-₪7,200, '
        "גבוה ב-81.5% מהממוצע של 3 החודשים הקודמים (₪3,967)."
    )


def test_deviation_down_sentence():
    assert narrate(DEVIATION_DOWN, 3) == (
        'ההכנסות בקטגוריה "הכנסות" הסתכמו ב-₪3,000, '
        "נמוך ב-70.0% מהממוצע של 3 החודשים הקודמים (₪10,000)."
    )


def test_missing_recurring_sentence():
    assert narrate(MISSING, 3) == (
        'לא נרשמה החודש הוצאה בקטגוריה "ביטוחים", '
        "שהופיעה בכל אחד מ-3 החודשים הקודמים (ממוצע ₪1,150)."
    )


def test_one_off_sentence():
    assert narrate(ONE_OFF, 3) == (
        'הכנסה חד-פעמית בקטגוריה "הכנסות אחרות" בסך ₪15,000, שהם 13.2% מסך ההכנסות החודש. '
        "בקטגוריה לא נרשמה פעילות ב-3 החודשים הקודמים."
    )


def test_sign_flip_sentence():
    assert narrate(SIGN_FLIP, 3) == (
        'כרטיס ההוצאה "ציוד משרדי" (6500) סיים את החודש ביתרת זכות של ₪150. '
        "כדאי לבדוק אם מדובר בזיכוי או בטעות סיווג."
    )


def test_account_spike_sentence():
    assert narrate(SPIKE, 3) == (
        'בכרטיס "חשמל ומים" (6110) נרשמו ₪2,900, לעומת ממוצע של ₪857 ב-3 החודשים הקודמים. '
        "הקטגוריה כולה לא חרגה."
    )


def test_history_length_is_not_hardcoded():
    assert "4 החודשים הקודמים" in narrate(DEVIATION_UP, 4)


def test_titles():
    assert title(DEVIATION_UP) == "חריגה בקטגוריה · שיווק ופרסום"
    assert title(MISSING) == "הוצאה קבועה שלא נרשמה · ביטוחים"
    assert title(ONE_OFF) == "הכנסה חד-פעמית · הכנסות אחרות"
    assert title(SIGN_FLIP) == "יתרה הפוכה בכרטיס · ציוד משרדי"
    assert title(SPIKE) == "סכום לא שגרתי בכרטיס · חשמל ומים"


def test_unknown_rule_is_an_error():
    with pytest.raises(KeyError):
        narrate(Finding("mystery", "info", "expense", "x", None, 1, None, None), 3)


# ---- the number guard ----

def test_numbers_in_normalizes_thousands_separators():
    assert numbers_in("₪12,345 ו-31.5%") == {"12345", "31.5"}
    assert numbers_in("ב-3 החודשים, 6500.") == {"3", "6500"}
    assert numbers_in("אין מספרים") == set()


@pytest.mark.parametrize("finding", ALL)
def test_every_template_passes_its_own_guard(finding):
    text = narrate(finding, 3)
    assert numbers_in(text) <= allowed_numbers(finding, 3)
    assert safe_narrate(finding, 3) == text


def test_digits_in_names_are_allowed():
    f = Finding("sign_flip", "orange", "expense", "רכב 2 ליסינג", "6520", -15_000, None, None)
    assert numbers_in(narrate(f, 3)) <= allowed_numbers(f, 3)


def test_narrator_with_a_foreign_number_falls_back_to_the_template():
    text = safe_narrate(DEVIATION_UP, 3, narrator=lambda f: "ההוצאה על שיווק זינקה ל-₪9,999 החודש.")
    assert text == narrate(DEVIATION_UP, 3)


def test_narrator_using_only_computed_numbers_is_accepted():
    rewrite = "הוצאות השיווק קפצו ל-₪7,200, שהם 81.5% מעל הממוצע (₪3,967)."
    assert safe_narrate(DEVIATION_UP, 3, narrator=lambda f: rewrite) == rewrite


def test_narrator_that_fails_or_returns_nothing_falls_back():
    def boom(f):
        raise RuntimeError("model unavailable")

    assert safe_narrate(SPIKE, 3, narrator=boom) == narrate(SPIKE, 3)
    assert safe_narrate(SPIKE, 3, narrator=lambda f: "  ") == narrate(SPIKE, 3)
