"""PDF downloader — fetches and caches annual report PDFs from company IR pages.

Downloads annual report PDFs from company investor relations websites and
caches them locally for processing by the annual report parser.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.config import get_settings
from app.data.ir_registry import get_ir_entry

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,application/octet-stream,*/*",
}


def _get_cache_dir() -> Path:
    """Return the PDF cache directory, creating it if needed."""
    settings = get_settings()
    cache_dir = Path(settings.pdf_cache_dir)
    if not cache_dir.is_absolute():
        # Relative to backend/ directory
        cache_dir = Path(__file__).resolve().parent.parent.parent / cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _get_pdf_path(ticker: str, fiscal_year: int) -> Path:
    """Return the local cache path for a specific report PDF."""
    cache_dir = _get_cache_dir()
    company_dir = cache_dir / ticker.upper()
    company_dir.mkdir(parents=True, exist_ok=True)
    return company_dir / f"{fiscal_year}.pdf"


def _download_file(url: str, dest: Path, timeout: int = 60) -> bool:
    """Download a file from URL to local path.

    Returns True if successful, False otherwise.
    """
    settings = get_settings()
    max_bytes = settings.pdf_max_size_mb * 1024 * 1024

    try:
        response = requests.get(
            url,
            headers=_HEADERS,
            timeout=timeout,
            stream=True,
            allow_redirects=True,
        )
        response.raise_for_status()

        # Check content-type
        content_type = response.headers.get("content-type", "").lower()
        if "pdf" not in content_type and "octet-stream" not in content_type:
            logger.warning(
                "Unexpected content type '%s' for %s", content_type, url
            )
            # Still try — some servers don't set correct content-type

        # Stream download with size check
        total = 0
        with open(dest, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                total += len(chunk)
                if total > max_bytes:
                    logger.error(
                        "PDF too large (>%dMB): %s",
                        settings.pdf_max_size_mb,
                        url,
                    )
                    dest.unlink(missing_ok=True)
                    return False
                f.write(chunk)

        # Verify it's actually a PDF (check magic bytes)
        with open(dest, "rb") as f:
            header = f.read(5)
            if header != b"%PDF-":
                logger.error(
                    "Downloaded file is not a valid PDF: %s (header: %r)",
                    url,
                    header,
                )
                dest.unlink(missing_ok=True)
                return False

        logger.info(
            "Downloaded PDF: %s -> %s (%.1f KB)",
            url,
            dest,
            total / 1024,
        )
        return True

    except requests.RequestException as e:
        logger.error("Failed to download %s: %s", url, e)
        dest.unlink(missing_ok=True)
        return False


def _normalize_url(url: str) -> str:
    """Normalize discovered URL text into a usable absolute URL string."""
    cleaned = (url or "").strip().strip('"\'')
    if cleaned.endswith(".pdf/"):
        cleaned = cleaned[:-1]
    return cleaned


def _domain_matches(url: str, search_domain: str) -> bool:
    """Return True when URL host is within expected company domain."""
    if not search_domain:
        return True
    host = urlparse(url).netloc.lower()
    domain = search_domain.lower().lstrip(".")
    return host == domain or host.endswith(f".{domain}")


def _score_pdf_candidate(url: str, fiscal_year: int) -> tuple[int, int]:
    """Score a PDF candidate URL; lower tuple is better."""
    lower = url.lower()
    score = 0

    if str(fiscal_year) not in lower:
        score += 4
    if "annual" not in lower and "financial" not in lower:
        score += 2
    if "report" not in lower and "statement" not in lower:
        score += 1
    if not lower.endswith(".pdf"):
        score += 3
    if "integrated-report" in lower or "full-year" in lower:
        score -= 2
    if re.search(r"(?:^|[^a-z0-9])q[1-4](?:[^a-z0-9]|$)", lower):
        score += 4

    # Prefer shorter, cleaner URLs when scores tie.
    return score, len(url)


def _is_likely_annual_report_pdf(url: str, fiscal_year: int) -> bool:
    """Heuristic filter to reject non-annual-report PDFs."""
    lower = url.lower()
    filename = os.path.basename(urlparse(url).path).lower()
    if ".pdf" not in lower:
        return False
    if str(fiscal_year) not in lower:
        return False

    strong_positive = (
        "annual-report",
        "annual_report",
        "annualreport",
        "financial-statements",
        "financial_statement",
        "financials",
        "integrated-report",
    )
    weak_positive = ("annual", "report", "statement", "financial")
    blocked = (
        "proxy",
        "agm",
        "notice",
        "form",
        "minutes",
        "presentation",
        "slides",
        "results-presentation",
        "half-year",
        "interim",
        "dividend",
        "climate",
        "sustainability",
        "responsible-banking",
        "prb",
        "polling",
        "results",
    )

    if any(token in filename for token in blocked):
        return False
    if re.search(r"(?:^|[^a-z0-9])q[1-4](?:[^a-z0-9]|$)", filename):
        return False
    if any(token in filename for token in strong_positive):
        return True
    return sum(token in filename for token in weak_positive) >= 2


def _extract_pdf_links_from_html(
    html: str,
    base_url: str,
    fiscal_year: int,
    search_domain: str,
) -> list[str]:
    """Extract PDF links from page HTML and rank likely annual reports."""
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[str] = []

    for anchor in soup.select("a[href]"):
        href = anchor.get("href")
        if not href:
            continue
        href_lower = href.lower()
        if ".pdf" not in href_lower:
            continue

        absolute = _normalize_url(urljoin(base_url, href))
        if not absolute.startswith(("http://", "https://")):
            continue
        if not _domain_matches(absolute, search_domain):
            continue
        candidates.append(absolute)

    # Some pages embed PDF links in scripts/JSON blobs.
    for match in re.findall(r"https?://[^\"'\s<>]+?\.pdf(?:\?[^\"'\s<>]*)?", html, flags=re.IGNORECASE):
        absolute = _normalize_url(match)
        if _domain_matches(absolute, search_domain):
            candidates.append(absolute)

    unique = sorted(set(candidates), key=lambda u: _score_pdf_candidate(u, fiscal_year))
    return unique


def _collect_pdf_candidates_from_pages(
    page_urls: list[str],
    fiscal_year: int,
    search_domain: str,
    timeout: int,
) -> list[str]:
    """Fetch likely IR pages and return ranked PDF candidates."""
    discovered: list[str] = []
    seen_pages: set[str] = set()

    for page_url in page_urls:
        normalized_page = _normalize_url(page_url)
        if not normalized_page or normalized_page in seen_pages:
            continue
        if not normalized_page.startswith(("http://", "https://")):
            continue
        seen_pages.add(normalized_page)

        try:
            response = requests.get(
                normalized_page,
                headers=_HEADERS,
                timeout=min(timeout, 20),
                allow_redirects=True,
            )
            response.raise_for_status()
        except requests.RequestException as e:
            logger.debug("Skipping page crawl %s: %s", normalized_page, e)
            continue

        page_candidates = _extract_pdf_links_from_html(
            response.text,
            str(response.url),
            fiscal_year,
            search_domain,
        )
        discovered.extend(page_candidates)

    return sorted(set(discovered), key=lambda u: _score_pdf_candidate(u, fiscal_year))


def _search_pdf_candidates(
    ticker: str,
    company_name: str,
    fiscal_year: int,
    search_domain: str,
    timeout: int,
) -> list[str]:
    """Search the web for likely PDF links constrained to company domain."""
    domain_part = f"site:{search_domain} " if search_domain else ""
    query = (
        f"{domain_part}{company_name} {ticker} {fiscal_year} "
        "annual report pdf"
    )

    try:
        response = requests.get(
            "https://duckduckgo.com/html/",
            params={"q": query},
            headers=_HEADERS,
            timeout=min(timeout, 20),
            allow_redirects=True,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        logger.debug("Search fallback failed for %s FY%d: %s", ticker, fiscal_year, e)
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    candidates: list[str] = []

    for anchor in soup.select("a[href]"):
        href = anchor.get("href") or ""
        if not href:
            continue

        candidate = href
        if "duckduckgo.com/l/?" in href or href.startswith("/l/?"):
            parsed = urlparse(urljoin("https://duckduckgo.com", href))
            uddg = parse_qs(parsed.query).get("uddg")
            if uddg:
                candidate = unquote(uddg[0])

        candidate = _normalize_url(candidate)
        if ".pdf" not in candidate.lower():
            continue
        if not candidate.startswith(("http://", "https://")):
            continue
        if not _domain_matches(candidate, search_domain):
            continue

        candidates.append(candidate)

    return sorted(set(candidates), key=lambda u: _score_pdf_candidate(u, fiscal_year))


def _find_pdf_url_via_llm(
    ticker: str,
    company_name: str,
    fiscal_year: int,
    search_domain: str = "",
) -> tuple[str | None, str | None]:
    """Use LLM to find the annual report PDF URL for a company.

    Asks GPT to search for and return the direct PDF URL for the
    company's annual report for the given fiscal year.
    """
    import openai

    settings = get_settings()
    if not settings.openai_api_key:
        logger.warning("No OpenAI API key — cannot search for PDF URL")
        return None, None

    client = openai.OpenAI(api_key=settings.openai_api_key)

    domain_hint = f" Their website domain is {search_domain}." if search_domain else ""

    prompt = (
        f"I need the DIRECT URL to the annual report PDF for "
        f"{company_name} (NSE ticker: {ticker}), a company listed on "
        f"the Nairobi Securities Exchange, Kenya, for fiscal year {fiscal_year}."
        f"{domain_hint}\n\n"
        f"Please provide:\n"
        f"1. The direct URL to the PDF annual report (not a webpage)\n"
        f"2. If you cannot find the exact URL, provide the investor "
        f"relations page URL where it might be found\n\n"
        f"Return ONLY a JSON object:\n"
        f'{{"pdf_url": "https://...", "ir_page": "https://...", '
        f'"confidence": "high|medium|low"}}'
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a financial research assistant. Find the "
                        "annual report PDF URL for the specified company. "
                        "Return only JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=500,
        )

        import json

        text = response.choices[0].message.content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])

        data = json.loads(text)
        pdf_url = _normalize_url(data.get("pdf_url", "")) or None
        ir_page = _normalize_url(data.get("ir_page", "")) or None
        if pdf_url and pdf_url.lower().endswith(".pdf"):
            return pdf_url, ir_page
        # Fallback to IR page
        if ir_page:
            logger.info(
                "LLM couldn't find direct PDF URL for %s FY%d, "
                "suggested IR page: %s",
                ticker,
                fiscal_year,
                ir_page,
            )
        return pdf_url, ir_page

    except Exception as e:
        logger.error("LLM PDF URL search failed for %s: %s", ticker, e)
        return None, None


def download_annual_report(
    ticker: str,
    fiscal_year: int,
    company_name: str = "",
    *,
    force_redownload: bool = False,
) -> str | None:
    """Download an annual report PDF and return the local file path.

    Strategy:
    1. Check local cache (skip if already downloaded)
    2. Try direct URL from IR registry pattern
    3. Try LLM-assisted URL discovery
    4. Download and verify

    Args:
        ticker: Company ticker symbol.
        fiscal_year: The fiscal year of the report.
        company_name: Full company name (for LLM search).
        force_redownload: Redownload even if cached.

    Returns:
        Local file path string if successful, None if not found.
    """
    ticker = ticker.upper()
    pdf_path = _get_pdf_path(ticker, fiscal_year)

    # Check cache
    if pdf_path.exists() and not force_redownload:
        logger.debug(
            "Using cached PDF: %s FY%d -> %s", ticker, fiscal_year, pdf_path
        )
        return str(pdf_path)

    settings = get_settings()
    ir_entry = get_ir_entry(ticker)

    # Strategy 1: Try direct URL pattern from registry
    if ir_entry.report_url_pattern:
        url = ir_entry.report_url_pattern.format(year=fiscal_year)
        logger.info("Trying direct URL pattern: %s", url)
        if _download_file(url, pdf_path, timeout=settings.pdf_download_timeout):
            return str(pdf_path)

    # Strategy 2: Use LLM to find the PDF URL
    logger.info(
        "Searching for PDF URL via LLM: %s FY%d", ticker, fiscal_year
    )
    pdf_url, ir_page = _find_pdf_url_via_llm(
        ticker,
        company_name or ticker,
        fiscal_year,
        search_domain=ir_entry.search_domain,
    )

    if pdf_url:
        logger.info("LLM found URL: %s", pdf_url)
        if _download_file(pdf_url, pdf_path, timeout=settings.pdf_download_timeout):
            return str(pdf_path)

    # Strategy 3: Crawl IR pages and discover candidate PDF links.
    crawl_pages: list[str] = []
    if ir_page:
        crawl_pages.append(ir_page)
    if ir_entry.ir_url:
        crawl_pages.append(ir_entry.ir_url)

    if crawl_pages:
        candidates = _collect_pdf_candidates_from_pages(
            crawl_pages,
            fiscal_year=fiscal_year,
            search_domain=ir_entry.search_domain,
            timeout=settings.pdf_download_timeout,
        )
        if candidates:
            likely_candidates = [
                c for c in candidates if _is_likely_annual_report_pdf(c, fiscal_year)
            ]
            logger.info(
                "Found %d PDF candidates on IR pages for %s FY%d (%d likely annual reports)",
                len(candidates),
                ticker,
                fiscal_year,
                len(likely_candidates),
            )
            candidates = likely_candidates
        for candidate in candidates[:8]:
            if _download_file(candidate, pdf_path, timeout=settings.pdf_download_timeout):
                return str(pdf_path)

    # Strategy 4: Web search fallback for PDF links on company domain.
    search_candidates = _search_pdf_candidates(
        ticker=ticker,
        company_name=company_name or ticker,
        fiscal_year=fiscal_year,
        search_domain=ir_entry.search_domain,
        timeout=settings.pdf_download_timeout,
    )
    likely_search_candidates = [
        c for c in search_candidates if _is_likely_annual_report_pdf(c, fiscal_year)
    ]
    if likely_search_candidates:
        logger.info(
            "Search fallback found %d likely PDF URLs for %s FY%d",
            len(likely_search_candidates),
            ticker,
            fiscal_year,
        )
    for candidate in likely_search_candidates[:8]:
        if _download_file(candidate, pdf_path, timeout=settings.pdf_download_timeout):
            return str(pdf_path)

    logger.warning(
        "Could not find/download annual report for %s FY%d",
        ticker,
        fiscal_year,
    )
    return None


def download_reports_for_company(
    ticker: str,
    company_name: str = "",
    years: range = range(2020, 2026),
    *,
    force_redownload: bool = False,
) -> dict[int, str | None]:
    """Download annual reports for a company across multiple years.

    Returns dict mapping fiscal_year -> local path (or None if failed).
    """
    results: dict[int, str | None] = {}
    for year in years:
        path = download_annual_report(
            ticker,
            year,
            company_name=company_name,
            force_redownload=force_redownload,
        )
        results[year] = path
    return results


def list_cached_reports(ticker: str | None = None) -> dict[str, list[int]]:
    """List all cached annual report PDFs.

    Returns dict mapping ticker -> list of fiscal years with cached PDFs.
    """
    cache_dir = _get_cache_dir()
    result: dict[str, list[int]] = {}

    if ticker:
        company_dir = cache_dir / ticker.upper()
        if company_dir.exists():
            years = sorted(
                int(f.stem)
                for f in company_dir.glob("*.pdf")
                if f.stem.isdigit()
            )
            if years:
                result[ticker.upper()] = years
    else:
        for company_dir in sorted(cache_dir.iterdir()):
            if company_dir.is_dir():
                years = sorted(
                    int(f.stem)
                    for f in company_dir.glob("*.pdf")
                    if f.stem.isdigit()
                )
                if years:
                    result[company_dir.name] = years

    return result
