import html as html_lib
import zipfile
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from mabat.store.db import ReportStore
from mabat.web.app import create_app


@pytest.fixture
def store(tmp_path):
    return ReportStore(tmp_path / "mabat.db")


@pytest.fixture
def client(store):
    return TestClient(create_app(store), follow_redirects=False)


def sample_files(sample_dir, prefix=""):
    return [
        ("files", (f"{prefix}INI.TXT", (sample_dir / "INI.TXT").read_bytes())),
        ("files", (f"{prefix}BKMVDATA.TXT", (sample_dir / "BKMVDATA.TXT").read_bytes())),
    ]


def text_of(response) -> str:
    return html_lib.unescape(response.text)


def test_empty_dashboard(client):
    response = client.get("/")
    assert response.status_code == 200
    assert 'dir="rtl"' in response.text
    assert "עדיין לא הופקו דוחות" in response.text
    assert "http://" not in response.text and "https://" not in response.text


def test_upload_creates_the_latest_month_report(client, store, sample_dir):
    response = client.post("/upload", files=sample_files(sample_dir))
    assert response.status_code == 303 and response.headers["location"] == "/"
    assert [(r["month"], r["status"]) for r in store.list()] == [("2026-06", "needs_review")]

    page = text_of(client.get("/"))
    assert 'סטודיו אלון עיצוב בע"מ' in page
    assert "יוני 2026" in page and "דורש בדיקה" in page and "טרם נסקר" in page


def test_upload_a_specific_month(client, store, sample_dir):
    client.post("/upload", files=sample_files(sample_dir), data={"month": "2026-05"})
    assert [(r["month"], r["status"]) for r in store.list()] == [("2026-05", "ready")]
    assert "מוכן" in text_of(client.get("/"))


def test_upload_all_months(client, store, sample_dir):
    client.post("/upload", files=sample_files(sample_dir), data={"all_months": "1"})
    assert len(store.list()) == 6


def test_upload_accepts_a_zipped_data_file(client, store, sample_dir):
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.write(sample_dir / "BKMVDATA.TXT", "BKMVDATA.TXT")
    files = [
        ("files", ("INI.TXT", (sample_dir / "INI.TXT").read_bytes())),
        ("files", ("BKMVDATA.zip", buffer.getvalue())),
    ]
    assert client.post("/upload", files=files).status_code == 303
    assert len(store.list()) == 1


def test_folder_upload_with_several_clients(client, store, sample_dir):
    files = sample_files(sample_dir, "OPENFRMT/51400001.26/07011000/")
    broken = (sample_dir / "INI.TXT").read_bytes()[:-30]
    files += [
        ("files", ("OPENFRMT/51400002.26/07011000/INI.TXT", broken)),
        ("files", ("OPENFRMT/51400002.26/07011000/BKMVDATA.TXT", (sample_dir / "BKMVDATA.TXT").read_bytes())),
    ]
    response = client.post("/upload", files=files)
    assert response.status_code == 200  # partial success: stay on the page and show the failure
    assert len(store.list()) == 1
    page = text_of(response)
    assert "51400002.26" in page and "INI.TXT" in page


def test_corrupt_upload_shows_a_hebrew_error_and_stores_nothing(client, store, sample_dir):
    files = [
        ("files", ("INI.TXT", (sample_dir / "INI.TXT").read_bytes()[:-30])),
        ("files", ("BKMVDATA.TXT", (sample_dir / "BKMVDATA.TXT").read_bytes())),
    ]
    response = client.post("/upload", files=files)
    assert response.status_code == 400
    assert "רשומת סיכום" in text_of(response)
    assert store.list() == []


def test_upload_without_the_required_files(client, store, sample_dir):
    only_ini = [("files", ("INI.TXT", (sample_dir / "INI.TXT").read_bytes()))]
    response = client.post("/upload", files=only_ini)
    assert response.status_code == 400 and "BKMVDATA" in text_of(response)
    response = client.post("/upload", files=[("files", ("notes.txt", b"hello"))])
    assert response.status_code == 400 and "INI.TXT" in text_of(response)
    assert store.list() == []


def test_upload_rejects_a_malformed_month(client, store, sample_dir):
    response = client.post("/upload", files=sample_files(sample_dir), data={"month": "June"})
    assert response.status_code == 400
    assert store.list() == []


def test_review_flow(client, store, sample_dir):
    client.post("/upload", files=sample_files(sample_dir))
    report_id = store.list()[0]["id"]

    review_page = client.get(f"/reports/{report_id}")
    assert review_page.status_code == 200
    assert f"/reports/{report_id}/html" in review_page.text
    assert "סמן כנסקר" in review_page.text

    draft = client.get(f"/reports/{report_id}/html")
    assert "טיוטה" in draft.text and "₪113,500" in draft.text

    response = client.post(f"/reports/{report_id}/review")
    assert response.status_code == 303 and response.headers["location"] == f"/reports/{report_id}"
    assert store.get(report_id)["reviewed_at"] is not None

    approved = client.get(f"/reports/{report_id}/html")
    assert "טיוטה" not in approved.text and "נסקר" in approved.text
    assert "סמן כנסקר" not in client.get(f"/reports/{report_id}").text
    assert "טרם נסקר" not in text_of(client.get("/"))


def test_downloads(client, store, sample_dir):
    client.post("/upload", files=sample_files(sample_dir))
    report_id = store.list()[0]["id"]

    html = client.get(f"/reports/{report_id}/html?download=1")
    assert html.headers["content-disposition"] == 'attachment; filename="514000017_2026-06.html"'

    pdf = client.get(f"/reports/{report_id}/pdf")
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["content-disposition"] == 'attachment; filename="514000017_2026-06.pdf"'
    assert pdf.content.startswith(b"%PDF")


def test_unknown_report_is_404(client):
    assert client.get("/reports/999").status_code == 404
    assert client.get("/reports/999/html").status_code == 404
    assert client.get("/reports/999/pdf").status_code == 404
    assert client.post("/reports/999/review").status_code == 404


def test_cross_site_posts_are_refused(client, store, sample_dir):
    client.post("/upload", files=sample_files(sample_dir))
    report_id = store.list()[0]["id"]
    response = client.post(f"/reports/{report_id}/review", headers={"origin": "https://evil.example"})
    assert response.status_code == 403
    assert store.get(report_id)["reviewed_at"] is None


def test_unexpected_host_header_is_refused(client):
    assert client.get("/", headers={"host": "evil.example"}).status_code == 400
