"""Command line: mabat run | serve | sample."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from mabat.config import DEFAULT_CONFIG_DIR, load_config
from mabat.errors import ValidationError
from mabat.pipeline import discover_exports, run_folder
from mabat.report.render import STATUS_LABELS, render_report
from mabat.store.db import ReportStore

DEFAULT_OUT = Path("output")
DB_NAME = "mabat.db"


def _month(value: str) -> str:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
        raise argparse.ArgumentTypeError("month must look like 2026-06")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mabat", description="דוחות חודשיים אוטומטיים מייצוא מבנה אחיד")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="הפקת דוחות מתיקיית OPENFRMT (או מתיקיית שורש עם כמה תיקים)")
    run.add_argument("path", type=Path)
    which = run.add_mutually_exclusive_group()
    which.add_argument("--month", type=_month, help="חודש מסוים, למשל 2026-06 (ברירת מחדל: החודש האחרון)")
    which.add_argument("--all-months", action="store_true", help="דוח לכל חודש שיש בו תנועות")
    run.add_argument("--out", type=Path, default=DEFAULT_OUT, help="תיקיית פלט (ברירת מחדל: output)")
    run.add_argument("--db", type=Path, help=f"קובץ SQLite (ברירת מחדל: <out>/{DB_NAME})")
    run.add_argument("--config", type=Path, default=DEFAULT_CONFIG_DIR, help="תיקיית קובצי ההגדרות")
    run.add_argument("--no-pdf", action="store_true", help="הפקת HTML בלבד")

    serve = sub.add_parser("serve", help="דשבורד מקומי לסקירת הדוחות")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--db", type=Path, default=DEFAULT_OUT / DB_NAME)
    serve.add_argument("--config", type=Path, default=DEFAULT_CONFIG_DIR)

    sample = sub.add_parser("sample", help="יצירת ייצוא OPENFRMT סינתטי לניסוי")
    sample.add_argument("out_root", type=Path, nargs="?", default=Path("data/sample"))
    return parser


def _run(args: argparse.Namespace) -> int:
    exports = discover_exports(args.path)
    if not exports:
        print(f"לא נמצא קובץ INI.TXT בתיקייה {args.path} או מתחתיה", file=sys.stderr)
        return 2

    config = load_config(args.config)
    store = ReportStore(args.db or args.out / DB_NAME)
    args.out.mkdir(parents=True, exist_ok=True)
    failed = False

    for folder in exports:
        try:
            contexts = run_folder(folder, config, month=args.month, all_months=args.all_months)
        except ValidationError as error:
            failed = True
            print(f"✗ {folder}: {error}", file=sys.stderr)
            continue
        for context in contexts:
            store.upsert(context)
            html = render_report(context, reviewed=False)
            target = args.out / f'{context["client"]["vat_id"]}_{context["month"]}.html'
            target.write_text(html, encoding="utf-8")
            if not args.no_pdf:
                from mabat.report.pdf import html_to_pdf

                html_to_pdf(html, target.with_suffix(".pdf"))
            print(
                f'✓ {context["client"]["business_name"]} · {context["month_label"]} · '
                f'{STATUS_LABELS[context["status"]]} · {target}'
            )
    return 1 if failed else 0


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from mabat.web.app import create_app

    app = create_app(ReportStore(args.db), args.config)
    # Client data stays on this machine: the dashboard listens on loopback only.
    uvicorn.run(app, host="127.0.0.1", port=args.port)
    return 0


def _sample(args: argparse.Namespace) -> int:
    from mabat.sampledata import write_sample

    print(write_sample(args.out_root))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return {"run": _run, "serve": _serve, "sample": _sample}[args.command](args)
