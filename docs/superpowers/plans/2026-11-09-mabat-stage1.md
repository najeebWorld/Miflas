# Mabat Stage 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** צינור מקצה לקצה שקולט תיקיית OPENFRMT ומפיק דוח חודשי בעברית (HTML + PDF) עם מדדים, השוואה חודשית וחריגות, דרך CLI ודשבורד מקומי.

**Architecture:** פונקציות טהורות בשרשרת `ingest → validate → normalize → compute → anomalies → narrate → report`, שמחוברות ב-`pipeline.py`. ה-CLI וה-FastAPI הם מעטפות דקות. כל סכום הוא `int` באגורות; כל אחוז הוא `int` בעשיריות אחוז.

**Tech Stack:** Python 3.10+, pandas (צבירה בלבד), PyYAML, Jinja2, FastAPI, Playwright 1.64.1 (Chromium), SQLite (stdlib), pytest.

מסמך התכנון: `docs/superpowers/specs/2026-11-09-mabat-monthly-reports-design.md`.
המפרט הרשמי: `docs/spec/openfrmt-horaot-1.31.pdf`.

התוכנית מבוצעת באותו סשן שבו נכתבה, ולכן היא נועלת ממשקים, ערכי בדיקה ופקודות
ולא משכפלת את גוף כל פונקציה. כל משימה: בדיקות נכשלות → מימוש → בדיקות עוברות → commit מקומי.
**אין `git push` בשום שלב** בלי אישור מפורש של המשתמש.

פקודת הבדיקות בכל משימה: `.venv/bin/python -m pytest tests/<file> -q`.

---

## מבנה קבצים

| קובץ | אחריות |
|---|---|
| `config/fieldmap.yaml` | כל השדות של A000, SUMMARY, A100, B100, B110, Z900 + אורכי C100/D110/D120/M100 |
| `config/classification.yaml` | כללי סיווג חשבונות + `period.date_field` |
| `config/thresholds.yaml` | ספי החריגות |
| `mabat/errors.py` | `ValidationError(message, file=None, line=None)` |
| `mabat/models.py` | `Header`, `Account`, `Movement`, `ParsedExport` |
| `mabat/formatting.py` | `ils`, `pct`, `ratio_tenths`, `month_label` |
| `mabat/config.py` | `Config`, `load_config(config_dir)` |
| `mabat/ingest/fieldmap.py` | `FieldMap`: `slice_record`, `build_record`, `length` |
| `mabat/ingest/encoding.py` | `detect_encoding`, `declared_codec` |
| `mabat/ingest/parser.py` | `parse_export(folder, fieldmap) -> ParsedExport` |
| `mabat/ingest/validate.py` | `validate_export(parsed) -> list[str]` |
| `mabat/normalize/classify.py` | `Classification`, `load_classification` |
| `mabat/normalize/ledger.py` | `build_ledger(parsed, classification) -> DataFrame` |
| `mabat/compute/pnl.py` | `MonthPnL`, `Change`, `PnLSummary`, `compute_pnl`, `available_months` |
| `mabat/anomalies/rules.py` | `Finding`, `detect`, `has_history` |
| `mabat/narrate/templates.py` | `narrate(finding) -> str` |
| `mabat/narrate/guard.py` | `numbers_in`, `allowed_numbers`, `safe_narrate` |
| `mabat/report/chart.py` | `bar_chart_svg(series) -> str` |
| `mabat/report/render.py` | `render_report(context, reviewed) -> str` |
| `mabat/report/pdf.py` | `html_to_pdf(html, out_path)` |
| `mabat/store/db.py` | `ReportStore` |
| `mabat/pipeline.py` | `discover_exports`, `run_folder`, `build_context` |
| `mabat/sampledata.py` | `write_sample(out_root, encoding)` |
| `mabat/cli.py`, `mabat/__main__.py` | `mabat run`, `mabat serve`, `mabat sample` |
| `mabat/web/app.py` | `create_app(store, config_dir)` |
| `tools/generate_sample.py` | מעטפת ל-`write_sample` |

## ממשקים נעולים

```python
# models.py
@dataclass(frozen=True)
class Header:            # A000
    vat_id: str; business_name: str; software_name: str
    tax_year: int | None; range_start: date | None; range_end: date | None
    primary_id: str; declared_charset: str; total_records: int

@dataclass(frozen=True)
class Account:           # B110
    key: str; name: str; tb_code: str; tb_desc: str; code_6111: str
    opening_balance: int; total_debit: int; total_credit: int

@dataclass(frozen=True)
class Movement:          # B100
    line: int; account_key: str; counter_account: str
    date: date; value_date: date | None; is_debit: bool; amount: int
    details: str; reference: str

@dataclass
class ParsedExport:
    header: Header; accounts: list[Account]; movements: list[Movement]
    record_codes: list[str]        # קוד כל רשומה ב-BKMVDATA, לפי הסדר
    record_numbers: list[int]      # השדה השני של כל רשומה, לפי הסדר
    ini_counts: dict[str, int]     # רשומות הסיכום ב-INI.TXT
    primary_ids: dict[str, str]    # {"A000":…, "A100":…, "Z900":…}
    closing_total: int             # שדה 1155
    encoding: str                  # codec שזוהה: utf-8 / cp1255 / cp862

# compute/pnl.py
@dataclass(frozen=True)
class MonthPnL: month: str; income: int; expenses: int; profit: int; margin_tenths: int | None
@dataclass(frozen=True)
class Change: diff: int; pct_tenths: int | None
@dataclass(frozen=True)
class PnLSummary:
    target: MonthPnL; previous: MonthPnL | None
    income_change: Change | None; expenses_change: Change | None; profit_change: Change | None
    series: list[MonthPnL]         # עד 6 חודשים קלנדריים רצופים, מהישן לחדש

# anomalies/rules.py
@dataclass(frozen=True)
class Finding:
    rule: str        # category_deviation | missing_recurring | one_off | sign_flip | account_spike
    severity: str    # red | orange | info
    type: str        # income | expense
    subject: str     # שם הקטגוריה או שם הכרטיס
    account: str | None
    amount: int
    baseline: int | None       # ממוצע 3 החודשים הקודמים, מעוגל לאגורה
    pct_tenths: int | None     # סטייה מהממוצע, או נתח מהסך החודשי
```

הלדג'ר המנורמל הוא `DataFrame` עם העמודות
`account, account_name, category, type, month, amount` (`month` בפורמט `YYYY-MM`).

`ratio_tenths(numer, denom)`: `numer/denom` באלפיות, מעוגל חצי הרחק מאפס; `None` כש-`denom == 0`.

## נתוני הדמה (ערכים שהבדיקות נשענות עליהם)

לקוח: "סטודיו אלון עיצוב בע"מ", ע.מ. 514000017, שנת מס 2026, ינואר–יוני.
נתיב: `data/sample/OPENFRMT/51400001.26/07011000/`. סכומים בש"ח, לפי חודש:

| כרטיס | שם | קוד מאזן בוחן / קטגוריה | ינו | פבר | מרץ | אפר | מאי | יוני |
|---|---|---|---|---|---|---|---|---|
| 4000 | הכנסות ממכירות | 100 הכנסות | 82,000 | 85,000 | 79,000 | 88,000 | 84,000 | 86,000 |
| 4010 | הכנסות משירותי ייעוץ | 100 הכנסות | 12,000 | 12,500 | 11,000 | 13,000 | 12,000 | 12,500 |
| 4900 | הכנסות אחרות | 110 הכנסות אחרות | – | – | – | – | – | 15,000 |
| 5000 | קניות סחורה | 200 עלות המכר | 31,000 | 33,000 | 30,000 | 34,000 | 32,000 | 33,000 |
| 6000 | שכר עבודה | 300 שכר ונלוות | 24,000 | 24,000 | 24,000 | 24,000 | 24,000 | 24,000 |
| 6010 | ביטוח לאומי מעסיק | 300 שכר ונלוות | 1,800 | 1,800 | 1,800 | 1,800 | 1,800 | 1,800 |
| 6100 | שכירות משרד | 310 שכירות ואחזקה | 6,500 | 6,500 | 6,500 | 6,500 | 6,500 | 6,500 |
| 6110 | חשמל ומים | 310 שכירות ואחזקה | 900 | 950 | 870 | 820 | 880 | 2,900 |
| 6200 | פרסום ושיווק | 320 שיווק ופרסום | 4,000 | 4,200 | 3,800 | 4,100 | 4,000 | 7,200 |
| 6300 | הנהלת חשבונות | 330 שירותים מקצועיים | 2,200 | 2,200 | 2,200 | 2,200 | 2,200 | 2,200 |
| 6400 | ביטוח עסק | 340 ביטוחים | 1,150 | 1,150 | 1,150 | 1,150 | 1,150 | – |
| 6500 | ציוד משרדי | 350 משרדיות | 300 | 350 | 250 | 320 | 280 | חובה 100, זכות 250 |
| 6510 | כיבוד ואירוח | 360 כיבוד ואירוח | 400 | 380 | 420 | 390 | 410 | 400 |

חשבונות מאזניים: 1000 בנק (500), 1100 לקוחות (510), 2000 ספקים (520), 2100 מע"מ (530).
הקובץ כולל גם רשומת `C100` אחת ורשומת `D110` אחת, כדי לבדוק רשומות שנספרות ולא מפוענחות.
תאריך הערך של חשבוניות המכירה הוא 30 יום אחרי התאריך.

תוצאות צפויות ליוני 2026: הכנסות 113,500; הוצאות 77,850; רווח 35,650; שיעור רווח 31.4%.
מאי: הכנסות 96,000; הוצאות 73,220; רווח 22,780.
שינוי: הכנסות +17,500 (18.2%); הוצאות +4,630 (6.3%); רווח +12,870 (56.5%).

חריגות צפויות ביוני (חמש בדיוק):
1. `category_deviation` אדום — שיווק ופרסום, 7,200 מול ממוצע 3,966.67, ‎+81.5%.
2. `missing_recurring` כתום — ביטוחים, ממוצע 1,150.
3. `one_off` כתום — הכנסות אחרות, 15,000, 13.2% מההכנסות.
4. `sign_flip` כתום — כרטיס 6500, ‎-150.
5. `account_spike` מידע — כרטיס 6110, 2,900 מול ממוצע 856.67.

מאי: אין חריגות ואין אזהרות → `ready`. מרץ: אין 3 חודשי היסטוריה → אזהרה → `needs_review`.

---

### Task 1: שלד, fieldmap והמרות בסיס

**Files:** `config/fieldmap.yaml`, `mabat/errors.py`, `mabat/models.py`, `mabat/formatting.py`, `mabat/ingest/fieldmap.py`, `tests/test_fieldmap.py`, `tests/test_formatting.py`

- [x] `test_fieldmap.py`: לכל רשומה עם שדות — השדות רציפים מ-1, לא חופפים, ומסתכמים ל-`length`; אורכים: A000 466, SUMMARY 19, A100 95, B100 317, B110 376, Z900 110, C100 444, D110 339, D120 222, M100 298; `build_record` → `slice_record` מחזיר את אותם ערכים; `build_record` של סכום `-123456` נותן `-00000000123456`.
- [x] `test_formatting.py`: `ils(1234567) == "₪12,346"`, `ils(-15000) == "-₪150"`, `pct(315) == "31.5%"`, `pct(-63) == "-6.3%"`, `ratio_tenths(1, 3) == 333`, `ratio_tenths(-1, 2000) == -1` (חצי הרחק מאפס), `ratio_tenths(5, 0) is None`, `month_label("2026-06") == "יוני 2026"`.
- [x] הרצה → כשל; מימוש; הרצה → עובר; commit.

### Task 2: זיהוי קידוד

**Files:** `mabat/ingest/encoding.py`, `tests/test_encoding.py`

- [x] בדיקות: טקסט עברי מקודד ב-`iso8859_8` → `cp1255`; ב-`cp862` → `cp862`; ב-`utf-8` → `utf-8`; ASCII בלבד → `cp1255`; `declared_codec("1") == "cp1255"`, `("2") == "cp862"`, `("0") is None`.
- [x] כשל → מימוש → עובר → commit.

### Task 3: מחולל נתוני הדמה

**Files:** `mabat/sampledata.py`, `tools/generate_sample.py`, `data/sample/…`, `tests/conftest.py`

- [x] `write_sample(out_root, encoding="iso8859_8") -> Path` מחזיר את תיקיית הייצוא. דטרמיניסטי.
- [x] `conftest.py`: fixtures `fieldmap`, `sample_dir` (נוצר ב-`tmp_path_factory`), `config`.
- [x] בדיקה ב-`tests/test_sampledata.py`: שתי הרצות נותנות קבצים זהים בייט-בבייט; כל שורה ב-`BKMVDATA.TXT` באורך הרשמי של הסוג שלה; סוף שורה CRLF.
- [x] commit (כולל `data/sample/`).

### Task 4: פרסר

**Files:** `mabat/ingest/parser.py`, `tests/test_parser.py`

- [x] בדיקות על הדמה: `header.business_name == 'סטודיו אלון עיצוב בע"מ'`, `vat_id == "514000017"`, `tax_year == 2026`; 17 חשבונות; תנועה ידועה מפוענחת (חשבון 6200, יוני, חובה, 720000 אגורות); `encoding == "cp1255"`; דמה ב-CP-862 ודמה ב-UTF-8 נותנות אותו שם עסק; `BKMVDATA.zip` במקום `.TXT` נקרא; שורה מקוצרת → `ValidationError` עם מספר השורה; קוד רשומה `X999` → `ValidationError`; סכום `+00000ABC…` → `ValidationError`; תיקייה בלי `INI.TXT` → `ValidationError`.
- [x] כשל → מימוש → עובר → commit.

### Task 5: ולידציה

**Files:** `mabat/ingest/validate.py`, `tests/test_validate.py`

- [x] בדיקות (כל אחת משחיתה עותק של הדמה): דמה תקינה → `[]`; מחיקת שורת `B100` → עצירה (ספירה מול INI); שינוי 1002 → עצירה; שינוי 1155 → עצירה; החלפת סדר כך ש-`Z900` לא אחרונה → עצירה; מספר רשומה לא רציף → עצירה; מזהה ראשי שונה ב-`Z900` → עצירה; תנועה לחשבון בלי `B110` → עצירה; שינוי 1415 בחשבון אחד → אזהרה (לא עצירה) שמציינת את מפתח החשבון; שדה 1029 = 2 בקובץ ISO → אזהרה.
- [x] כשל → מימוש → עובר → commit.

### Task 6: סיווג ולדג'ר

**Files:** `config/classification.yaml`, `mabat/normalize/classify.py`, `mabat/normalize/ledger.py`, `mabat/config.py`, `tests/test_normalize.py`

- [x] בדיקות: בדמה — סכום `income` ליוני 11,350,000 אגורות, `expense` 7,785,000; אין שורות `balance_sheet`; כרטיס 6500 ביוני = ‎-15,000; קטגוריה של 6110 = "שכירות ואחזקה"; כלל `account_key` גובר כשהוא ראשון; כלל `code_6111_range` מתאים לחשבון עם קוד 6111; חשבון עם תנועות בלי סיווג → `ValidationError` שמכיל את המפתח; חשבון בלי תנועות ובלי סיווג לא עוצר; `date_field: value_date` מעביר את מכירות יוני ליולי.
- [x] כשל → מימוש → עובר → commit.

### Task 7: חישוב רווח והפסד

**Files:** `mabat/compute/pnl.py`, `tests/test_compute.py`

- [x] בדיקות על לדג'ר בנוי ידנית: הכנסות אפס → `margin_tenths is None`; אין חודש קודם → `previous is None` וכל ה-`Change` הם `None`; חודש קודם עם רווח שלילי → אחוז לפי ערך מוחלט של המכנה; חודש חסר באמצע הסדרה → אפסים; הסדרה לא מתחילה לפני חודש הנתונים הראשון ולא ארוכה מ-6.
- [x] בדיקות על הדמה: ערכי יוני ומאי והשינויים מהטבלה למעלה; `available_months` = ינואר–יוני.
- [x] כשל → מימוש → עובר → commit.

### Task 8: חריגות

**Files:** `config/thresholds.yaml`, `mabat/anomalies/rules.py`, `tests/test_anomalies.py`

כללים (השוואות בשלמים מול סכום שלושת החודשים, בלי עיגול):
- `category_deviation`: ממוצע חיובי, `|סטייה| > 30%` וגם `|הפרש| > ₪500`. מעל 60% אדום, אחרת כתום. סטייה לטובה (הכנסה עולה, הוצאה יורדת) → מידע.
- `missing_recurring`: הוצאה, חיובית בכל 3 הקודמים, ובדיוק אפס בחודש היעד → כתום.
- `one_off`: אפס בכל 3 הקודמים, חיובי בחודש היעד, נתח מעל 10% מסך הסוג → כתום; מעל 25% אדום.
- `sign_flip`: נטו שלילי בכרטיס, בערך מוחלט ₪100 לפחות → כתום. לא דורש היסטוריה.
- `account_spike`: ממוצע הכרטיס חיובי, הסכום מעל פי 3 מהממוצע, הפרש מעל ₪500, ואין לקטגוריה ממצא ברמת קטגוריה → מידע.
- בלי 3 חודשי היסטוריה (`has_history` שקר): רק `sign_flip` רץ.
- מיון: אדום, כתום, מידע; בתוך חומרה לפי ערך מוחלט של הסכום, יורד.

- [x] בדיקות סף לכל כלל: בדיוק על הסף (לא מופעל), אגורה מעל (מופעל), מתחת; מעבר כתום→אדום; סטייה לטובה → מידע; `missing_recurring` לא מופעל על הכנסה ולא כשאחד החודשים הקודמים אפס; `account_spike` מדוכא כשיש ממצא קטגוריה; בלי היסטוריה רק `sign_flip`.
- [x] בדיקה על הדמה: חמשת הממצאים של יוני בדיוק, לפי הסדר (אדום, שלושה כתומים לפי סכום, מידע); מאי → `[]`.
- [x] כשל → מימוש → עובר → commit.

### Task 9: ניסוח ושומר המספרים

**Files:** `mabat/narrate/templates.py`, `mabat/narrate/guard.py`, `tests/test_narrate.py`

- [x] בדיקות: לכל אחד מחמשת ממצאי הדמה, המשפט מכיל את שם הנושא ואת הסכום המעוצב; כל תבנית עוברת את השומר; `safe_narrate(finding, narrator=lambda f: "ההוצאה עלתה ל-₪9,999")` מחזיר את התבנית (מספר זר); narrator שמחזיר משפט עם אותם מספרים מתקבל כלשונו; `numbers_in("₪12,345 ו-31.5%") == {"12345", "31.5"}`.
- [x] כשל → מימוש → עובר → commit.

### Task 10: דוח HTML וגרף

**Files:** `mabat/report/chart.py`, `mabat/report/render.py`, `mabat/report/templates/report.html.j2`, `mabat/pipeline.py` (`build_context`), `tests/test_report.py`

- [x] לפני כתיבת הגרף: לטעון את ה-skill `dataviz`.
- [x] `build_context(parsed, ledger, warnings, month, thresholds, now) -> dict` — מילון שניתן לסריאליזציה ל-JSON, עם ערכים גולמיים ומחרוזות מעוצבות, כולל `status`.
- [x] בדיקות: ה-HTML של יוני מכיל `dir="rtl"`, את שם העסק, "₪113,500", "₪77,850", "₪35,650", "18.2%", חמישה פריטי חריגה עם מחלקות חומרה, את שורת התחתית המדויקת, `<svg`, ואין בו `http://` או `https://`; `reviewed=False` מכיל "טיוטה", `reviewed=True` לא; `json.dumps(context)` עובד; סטטוס יוני `needs_review`, מאי `ready`.
- [x] כשל → מימוש → עובר; לפתוח את הדוח בדפדפן ולצלם לבדיקה חזותית → commit.

### Task 11: PDF

**Files:** `mabat/report/pdf.py`, `tests/test_pdf.py`

- [x] בדיקה: `html_to_pdf` יוצר קובץ שמתחיל ב-`%PDF` וגדול מ-5KB; `pdftotext` על התוצאה מכיל "113,500".
- [x] כשל → מימוש → עובר → commit.

### Task 12: אחסון, צינור ו-CLI

**Files:** `mabat/store/db.py`, `mabat/pipeline.py`, `mabat/cli.py`, `mabat/__main__.py`, `tests/test_store.py`, `tests/test_pipeline.py`, `tests/test_cli.py`

- [x] `ReportStore(path)`: `upsert(context) -> int`, `list() -> list[dict]`, `get(id) -> dict | None`, `mark_reviewed(id, when)`. מפתח ייחודי `(vat_id, month)`; `upsert` חוזר מאפס `reviewed_at`.
- [x] `discover_exports(root) -> list[Path]`; `run_folder(folder, config, month=None, all_months=False, now=None) -> list[dict]`.
- [x] בדיקות: `run_folder` ברירת מחדל → דוח אחד ליוני; `all_months=True` → 6 דוחות, מרץ עם אזהרת היסטוריה; `month="2026-05"` → `ready`; חודש שלא קיים → `ValidationError`; `discover_exports` מוצא את הדמה מתיקיית השורש; CLI: `mabat run data/sample --out <tmp> --no-pdf` יוצר `514000017_2026-06.html` ומחזיר 0; תיקייה עם ייצוא פגום ועוד ייצוא תקין → התקין מופק, קוד יציאה 1.
- [x] כשל → מימוש → עובר → commit.

### Task 13: דשבורד

**Files:** `mabat/web/app.py`, `mabat/web/templates/index.html.j2`, `mabat/web/templates/review.html.j2`, `tests/test_web.py`

- [x] נתיבים: `GET /`, `POST /upload`, `GET /reports/{id}`, `GET /reports/{id}/html`, `GET /reports/{id}/pdf`, `POST /reports/{id}/review`.
- [x] בדיקות (`TestClient`): `GET /` → 200; העלאת קובצי הדמה → הדוח מופיע ברשימה עם "דורש בדיקה"; העלאת `INI.TXT` פגום → הודעת שגיאה בעברית ואין דוח חדש; `/reports/1/html` מכיל "טיוטה"; אחרי `POST /reports/1/review` אין "טיוטה"; `/reports/999` → 404.
- [x] כשל → מימוש → עובר; הרצת השרת ובדיקה בדפדפן → commit.

### Task 14: סגירה

**Files:** `README.md`

- [x] README בעברית: התקנה, הרצה על הדמה, מבנה ה-config, מה לבדוק כשמגיע קובץ אמיתי.
- [x] הרצת כל הבדיקות; הרצת `mabat run data/sample --all-months` ובדיקת הפלט; commit.
