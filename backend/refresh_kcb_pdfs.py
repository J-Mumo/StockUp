"""One-off: refresh KCB cached annual PDFs with real Investor Presentations
(FY 2023/2024/2025) and Integrated Reports (2020-2022, plus 2023-2025 as
secondary fallback). Backs up existing thin files first.

Usage:
    python refresh_kcb_pdfs.py
"""
from __future__ import annotations

import logging
import re
import shutil
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("refresh_kcb")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
}

BASE = "https://kcbgroup.com"
IP_PAGES = [f"{BASE}/investor-presentations", f"{BASE}/investor-presentations?page=2"]
IR_PAGE = f"{BASE}/integrated-reports"

KCB_DIR = Path(__file__).resolve().parent / "data" / "annual_reports" / "KCB"
BACKUP_DIR = KCB_DIR / "_pre_ip_refresh"


def fetch(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.text


def parse_links(html: str) -> list[tuple[str, str]]:
    """Return list of (title, href) for downloadable items on the page."""
    soup = BeautifulSoup(html, "html.parser")
    items: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/download/" not in href:
            continue
        title = a.get_text(strip=True)
        if not title:
            continue
        items.append((title, href))
    return items


def find_fy_ip(items: list[tuple[str, str]]) -> dict[int, str]:
    """Match titles like 'KCB Group Plc FY 2024 Investor Presentation'."""
    rx = re.compile(r"FY\s*(\d{4}).*Investor Presentation", re.IGNORECASE)
    out: dict[int, str] = {}
    for title, href in items:
        m = rx.search(title)
        if m:
            year = int(m.group(1))
            out.setdefault(year, href)
    return out


def find_integrated(items: list[tuple[str, str]]) -> dict[int, str]:
    """Match titles like 'KCB Group Plc 2022 Integrated Report ...'."""
    rx = re.compile(r"Plc\s*(\d{4})\s+Integrated Report", re.IGNORECASE)
    out: dict[int, str] = {}
    for title, href in items:
        m = rx.search(title)
        if m:
            year = int(m.group(1))
            out.setdefault(year, href)
    return out


def download(url: str, dest: Path) -> int:
    with requests.get(url, headers=HEADERS, timeout=180, stream=True, allow_redirects=True) as r:
        r.raise_for_status()
        ct = r.headers.get("Content-Type", "")
        if "pdf" not in ct.lower() and not url.lower().endswith(".pdf"):
            # Many endpoints return PDF without correct CT; peek first bytes.
            chunk = next(r.iter_content(1024), b"")
            if not chunk.startswith(b"%PDF"):
                raise RuntimeError(f"Not a PDF (CT={ct}, first bytes={chunk[:8]!r})")
            with dest.open("wb") as f:
                f.write(chunk)
                for c in r.iter_content(65536):
                    f.write(c)
        else:
            with dest.open("wb") as f:
                for c in r.iter_content(65536):
                    f.write(c)
    return dest.stat().st_size


def main() -> int:
    KCB_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    log.info("Scraping Investor Presentations...")
    ip_items: list[tuple[str, str]] = []
    for url in IP_PAGES:
        ip_items.extend(parse_links(fetch(url)))
    fy_ip = find_fy_ip(ip_items)
    log.info("Found FY investor presentations: %s", sorted(fy_ip))

    log.info("Scraping Integrated Reports...")
    ir_items = parse_links(fetch(IR_PAGE))
    fy_ir = find_integrated(ir_items)
    log.info("Found integrated reports: %s", sorted(fy_ir))

    # Per-year preference: FY Investor Presentation if available, else Integrated Report.
    years = sorted(set(fy_ip) | set(fy_ir))
    chosen: dict[int, tuple[str, str]] = {}
    for y in years:
        if y in fy_ip:
            chosen[y] = ("FY-IP", fy_ip[y])
        elif y in fy_ir:
            chosen[y] = ("Integrated", fy_ir[y])

    log.info("Plan:")
    for y, (kind, _) in sorted(chosen.items()):
        log.info("  FY%d <- %s", y, kind)

    # Backup existing 2020/2022/2023/2024/2025.pdf
    for y in years:
        existing = KCB_DIR / f"{y}.pdf"
        if existing.exists():
            backup = BACKUP_DIR / f"{y}.pdf"
            if not backup.exists():
                shutil.move(str(existing), str(backup))
                log.info("Backed up %s -> %s", existing.name, backup)
            else:
                existing.unlink()
                log.info("Removed %s (backup already present)", existing.name)

    # Download new PDFs
    for y, (kind, url) in sorted(chosen.items()):
        dest = KCB_DIR / f"{y}.pdf"
        try:
            size = download(url, dest)
            log.info("Downloaded FY%d (%s) -> %s (%d KB)", y, kind, dest.name, size // 1024)
        except Exception as e:
            log.error("FAILED FY%d: %s", y, e)

    return 0


if __name__ == "__main__":
    sys.exit(main())
