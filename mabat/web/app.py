"""Local review dashboard: upload an export, see reports, mark them reviewed.

Nothing here sends a report anywhere. The accountant downloads the HTML/PDF
by hand once the report is reviewed.
"""
from __future__ import annotations

import re
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.middleware.trustedhost import TrustedHostMiddleware

from mabat.config import DEFAULT_CONFIG_DIR, load_config
from mabat.errors import ValidationError
from mabat.pipeline import run_folder
from mabat.report.render import STATUS_LABELS, display_datetime, render_report
from mabat.store.db import ReportStore

# The dashboard is for the accountant's own machine. Requests naming any other
# host are refused (protects against DNS rebinding); "testserver" is the test client.
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]

_MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.filters["datetime"] = display_datetime


def _same_origin(request: Request) -> None:
    """Refuse state-changing requests sent by another website (CSRF)."""
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "cross-site request refused")


def _group_uploads(files: list[UploadFile]) -> dict[str, dict[str, UploadFile]]:
    """{folder: {"ini": file, "data": file}} keyed by the uploaded relative folder.

    A folder upload carries relative paths, so several clients can arrive at
    once; a plain two-file upload lands in a single group named "".
    """
    groups: dict[str, dict[str, UploadFile]] = {}
    for upload in files:
        if not upload.filename:
            continue
        path = PurePosixPath(upload.filename.replace("\\", "/"))
        name = path.name.upper()
        if name == "INI.TXT":
            kind = "ini"
        elif path.stem.upper() == "BKMVDATA":
            kind = "data"
        else:
            continue
        groups.setdefault(str(path.parent) if str(path.parent) != "." else "", {})[kind] = upload
    return groups


def _save(upload: UploadFile, folder: Path, kind: str) -> None:
    """Write under a fixed name; the uploaded name never reaches the filesystem."""
    data = upload.file.read()
    if kind == "ini":
        name = "INI.TXT"
    else:
        name = "BKMVDATA.zip" if data[:2] == b"PK" else "BKMVDATA.TXT"
    (folder / name).write_bytes(data)


def create_app(store: ReportStore, config_dir: Path | str = DEFAULT_CONFIG_DIR) -> FastAPI:
    app = FastAPI(title="מבט", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

    def index(errors: list[str] | None = None, notice: str | None = None, status: int = 200) -> HTMLResponse:
        page = _env.get_template("index.html.j2").render(
            reports=store.list(), status_labels=STATUS_LABELS, errors=errors or [], notice=notice,
        )
        return HTMLResponse(page, status_code=status)

    def record_or_404(report_id: int) -> dict:
        record = store.get(report_id)
        if record is None:
            raise HTTPException(404, "הדוח לא נמצא")
        return record

    def filename(record: dict, extension: str) -> str:
        return f'{record["vat_id"]}_{record["month"]}.{extension}'

    def report_html(record: dict) -> str:
        return render_report(
            record["context"], reviewed=record["reviewed_at"] is not None, reviewed_at=record["reviewed_at"]
        )

    @app.get("/", response_class=HTMLResponse)
    def home():
        return index()

    @app.post("/upload")
    def upload(
        request: Request,
        files: list[UploadFile] = File(default=[]),
        month: str = Form(default=""),
        all_months: str = Form(default=""),
    ):
        _same_origin(request)
        month = month.strip()
        if month and not _MONTH.fullmatch(month):
            return index(["החודש צריך להיות בפורמט YYYY-MM, למשל 2026-06."], status=400)

        groups = _group_uploads(files)
        if not any("ini" in g for g in groups.values()):
            return index(["לא נמצא קובץ INI.TXT בין הקבצים שהועלו."], status=400)

        config = load_config(config_dir)
        errors: list[str] = []
        created = 0
        for folder_name, group in sorted(groups.items()):
            label = f"{folder_name}: " if folder_name else ""
            if "ini" not in group or "data" not in group:
                missing = "INI.TXT" if "ini" not in group else "BKMVDATA.TXT (או BKMVDATA.zip)"
                errors.append(f"{label}חסר הקובץ {missing}.")
                continue
            # Source files live only for the duration of the request.
            with tempfile.TemporaryDirectory(prefix="mabat-upload-") as tmp:
                _save(group["ini"], Path(tmp), "ini")
                _save(group["data"], Path(tmp), "data")
                try:
                    contexts = run_folder(tmp, config, month=month or None, all_months=bool(all_months))
                except ValidationError as error:
                    errors.append(f"{label}{error}")
                    continue
            for context in contexts:
                store.upsert(context)
                created += 1

        if errors:
            notice = f"הופקו {created} דוחות. חלק מהתיקים נכשלו:" if created else None
            return index(errors, notice=notice, status=200 if created else 400)
        return RedirectResponse("/", status_code=303)

    @app.get("/reports/{report_id}", response_class=HTMLResponse)
    def review_page(report_id: int):
        record = record_or_404(report_id)
        return _env.get_template("review.html.j2").render(r=record, status_labels=STATUS_LABELS)

    @app.get("/reports/{report_id}/html")
    def report_as_html(report_id: int, download: int = 0):
        record = record_or_404(report_id)
        headers = {}
        if download:
            headers["Content-Disposition"] = f'attachment; filename="{filename(record, "html")}"'
        return HTMLResponse(report_html(record), headers=headers)

    @app.get("/reports/{report_id}/pdf")
    def report_as_pdf(report_id: int):
        from mabat.report.pdf import html_to_pdf_bytes

        record = record_or_404(report_id)
        return Response(
            html_to_pdf_bytes(report_html(record)),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename(record, "pdf")}"'},
        )

    @app.post("/reports/{report_id}/review")
    def mark_reviewed(report_id: int, request: Request):
        _same_origin(request)
        record_or_404(report_id)
        store.mark_reviewed(report_id, datetime.now())
        return RedirectResponse(f"/reports/{report_id}", status_code=303)

    return app
