"""HTML report -> A4 PDF using a local headless Chromium (Playwright).

The page is loaded from a string and the browser context is offline, so
nothing about the client leaves the machine while printing.
"""
from __future__ import annotations

from pathlib import Path


def html_to_pdf_bytes(html: str) -> bytes:
    # Imported here so the rest of the pipeline works without a browser installed.
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            context = browser.new_context(offline=True, java_script_enabled=False)
            page = context.new_page()
            page.set_content(html, wait_until="load")
            return page.pdf(format="A4", print_background=True, prefer_css_page_size=True)
        finally:
            browser.close()


def html_to_pdf(html: str, out_path: Path | str) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(html_to_pdf_bytes(html))
    return out_path
