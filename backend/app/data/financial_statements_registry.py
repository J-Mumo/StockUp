"""Financial Statements Registry — fetches and caches financial statement PDFs from company IR pages.

Downloads financial statement PDFs from company investor relations websites,
extracts financial data using annual report parser, and stores in database.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.company import Company
from app.data.annual_report_parser import parse_annual_report

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
}


# Hosts known to sit behind Cloudflare bot protection that block plain
# ``requests`` traffic with HTTP 403. Use ``cloudscraper`` for these so
# the JS challenge is solved transparently.
_CLOUDFLARE_HOSTS = (
    "imbankgroup.com",
)


def _make_session(url: str) -> requests.Session:
    """Return a session capable of fetching ``url``.

    Returns a ``cloudscraper`` session for known Cloudflare-protected
    hosts, otherwise a plain ``requests.Session``.
    """
    host = (urlparse(url).netloc or "").lower()
    if any(host == h or host.endswith("." + h) for h in _CLOUDFLARE_HOSTS):
        try:
            import cloudscraper  # type: ignore

            return cloudscraper.create_scraper()
        except ImportError:
            logger.warning(
                "cloudscraper not installed; falling back to plain requests for %s",
                host,
            )
    return requests.Session()


def _is_safaricom_url(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower()
    return host == "www.safaricom.co.ke" or host.endswith(".safaricom.co.ke")


def _extract_fiscal_year(title: str, pdf_url: str) -> int | None:
    year_ended_match = re.search(
        r"year\s+ended[^\d]*(20\d{2})",
        title,
        flags=re.IGNORECASE,
    )
    if year_ended_match:
        return int(year_ended_match.group(1))

    # High-precision pattern: when the title contains a phrase such as
    # "Annual Report and Financial Statements 2024" or "Integrated
    # Report 2023", the trailing year is the fiscal year, even when an
    # earlier publication date in the same title contains a different
    # year (e.g. "27 MAR 2025 Kakuzi Plc Annual Report and Financial
    # Statements 2024").
    phrase_match = re.search(
        r"(?:annual\s+report(?:\s+(?:and|&)\s+(?:audited\s+)?financial\s+statements?)?|"
        r"integrated\s+(?:annual\s+)?report|"
        r"audited\s+financial\s+statements?|"
        r"financial\s+statements?)\b[^\d]{0,30}?(20\d{2})",
        title,
        flags=re.IGNORECASE,
    )
    if phrase_match:
        return int(phrase_match.group(1))

    # Prefer years in the title over years in the URL: issuer CMSs often
    # embed the publication year in the filename or upload path (e.g.,
    # "Bamburi-2026-FY-Results.pdf" for FY2025 results published in
    # 2026, or wp-content/uploads/2026/04/). The title text ("Financial
    # Statements 2025") is the authoritative fiscal-year indicator.
    title_years = [int(y) for y in re.findall(r"(?<!\d)20\d{2}(?!\d)", title)]

    # Fall back to the filename portion of the URL (not the full path) so
    # CMS upload directories don't leak the upload year. URL-decode so
    # that percent-encoded spaces ("%2031ST" in "31ST DEC 2025") don't
    # match the bare 20YY pattern as a fake year (2031).
    from urllib.parse import unquote

    url_filename = pdf_url.rsplit("/", 1)[-1] if pdf_url else ""
    url_filename = unquote(url_filename)
    url_years = [int(y) for y in re.findall(r"(?<!\d)20\d{2}(?!\d)", url_filename)]

    if title_years:
        # When a listing page applies the same section heading (e.g. the
        # AGM/publication year) to many entries, every per-link title
        # inherits that year. If the URL filename names a specific year
        # that is also among the title candidates, prefer it. Otherwise,
        # if the URL filename has its own year, trust the URL filename
        # (the title year is then almost certainly the page heading).
        if url_years:
            shared = [y for y in title_years if y in url_years]
            if shared:
                return max(shared)
            return max(url_years)
        return max(title_years)

    if url_years:
        return max(url_years)

    # Safaricom and similar issuers often label as FY24/FY25 without full year.
    fy_match = re.search(r"\bFY\s*[-_]?\s*(\d{2})\b", title, flags=re.IGNORECASE)
    if fy_match:
        yy = int(fy_match.group(1))
        return 2000 + yy if yy <= 50 else 1900 + yy

    return None


def _statement_score(stmt: dict) -> int:
    title = (stmt.get("title") or "").lower()
    score = 0
    if "integrated report" in title:
        score += 6
    if "combined annual" in title or "annual and sustainability report" in title:
        # BAT Kenya's "Combined Annual and Sustainability Report" is the
        # full annual report (8-10MB); prefer it over the abridged FY
        # Results press releases.
        score += 7
    if "annual report" in title:
        score += 5
    if "audited" in title:
        score += 2
    if "financial statement" in title:
        score += 2
    if "results booklet" in title:
        score += 1
    if "full year results" in title:
        # Abridged FY results PDFs are useful fallbacks only.
        score += 1
    if "press release" in title:
        score += 0
    return score


def _get_cache_dir(ticker: str) -> Path:
    """Return the PDF cache directory for a company."""
    settings = get_settings()
    cache_dir = Path(settings.pdf_cache_dir)
    if not cache_dir.is_absolute():
        cache_dir = Path(__file__).resolve().parent.parent.parent / cache_dir
    company_dir = cache_dir / ticker.upper()
    company_dir.mkdir(parents=True, exist_ok=True)
    return company_dir


def _get_pdf_path(ticker: str, fiscal_year: int, quarter: Optional[str] = None) -> Path:
    """Return the local cache path for a specific report PDF."""
    cache_dir = _get_cache_dir(ticker)
    if quarter:
        filename = f"{fiscal_year}_{quarter}.pdf"
    else:
        filename = f"{fiscal_year}.pdf"
    return cache_dir / filename


def _extract_statements_from_html(html: str, base_url: str) -> list[dict]:
    """Extract financial statement links from HTML page.
    
    Returns list of dicts with keys: title, pdf_url, fiscal_year, quarter
    """
    soup = BeautifulSoup(html, "html.parser")
    statements = []

    is_safaricom = _is_safaricom_url(base_url)

    include_keywords = [
        "financial statement",
        "financial statements",
        "audited financial",
        "annual report",
        "integrated report",
        # Co-operative Bank and similar issuers label FY filings simply as
        # "... Financials" (e.g., "Co-op Bank Financials – FY 2025").
        "financials",
        # BAT Kenya posts abridged FY/HY results PDFs under "Full Year
        # Results" / "Half Year Results" headings. Include "full year
        # results"; the half-year variants are skipped by the quarter
        # detector below.
        "full year results",
        "combined annual and sustainability report",
    ]
    if is_safaricom:
        include_keywords.extend([
            "results booklet",
            "press release",
        ])

    exclude_keywords = [
        "policy",
        "charter",
        "terms of reference",
        # Match "sustainability report" specifically so we don't reject
        # joint filings like "Combined Annual and Sustainability Report".
        "sustainability report",
        "esg report",
        "presentation",
        "code of conduct",
        "disclosure policy",
        # Investor-relations pages mix annual reports with corporate-event
        # documents that follow similar naming. Exclude these explicitly so
        # the row-text fallback (which can pick up a nearby "Annual Report"
        # heading) doesn't accidentally classify them as annuals.
        "agm",
        "notice of ",
        "proxy",
        "calendar of corporate events",
        "dividend",
        "circular",
        "voting result",
        "q&a",
        "shareholder information",
        "corporate governance report",
        "governance report",
    ]
    if not is_safaricom:
        exclude_keywords.extend([
            "booklet",
            "press release",
        ])

    generic_link_text = {"download", "download pdf", "view", "view pdf", "read more", "pdf"}

    # CDN URL patterns that serve PDFs without a .pdf extension. Match
    # these so we can still classify the link as a PDF candidate.
    pdf_cdn_patterns = (
        "dxm.content-center.totalenergies.com",
        "evp-api-totalenergies-dam",
        "play.html?",  # Wedia media player URL
        "/api/wedia/dam/",
        "MediaUid=",
    )

    for link in soup.select("a[href]"):
        href = link.get("href") or ""
        href_low = href.lower()
        is_pdf_like = ".pdf" in href_low or any(p.lower() in href_low for p in pdf_cdn_patterns)
        if not is_pdf_like:
            continue

        pdf_url = href if href.startswith("http") else urljoin(base_url, href)
        link_text = link.get_text(" ", strip=True)
        title_attr = link.get("title") or ""

        # Some sites (e.g., Co-operative Bank, Kenya Re) render only
        # "Download" as the anchor text and place the real title in a
        # nearby heading or a sibling cell of the same row. Walk up the
        # DOM looking first for a heading element, then for any ancestor
        # whose text contains substantially more than the link text.
        heading_text = ""
        node = link
        for _ in range(8):
            parent = node.parent
            if parent is None:
                break
            heading = parent.find(["h1", "h2", "h3", "h4", "h5", "h6"])
            if heading:
                heading_text = heading.get_text(" ", strip=True)
                if heading_text:
                    break
            node = parent

        row_text = ""
        if not heading_text and link_text and link_text.lower() in generic_link_text:
            node = link
            for _ in range(8):
                parent = node.parent
                if parent is None:
                    break
                txt = parent.get_text(" ", strip=True)
                # Pick the smallest ancestor that introduces meaningful
                # additional text beyond the generic link label and is
                # not so broad that it contains many sibling rows. We do
                # NOT require an include-keyword match here, because that
                # would cause the walker to climb past a tight per-row
                # container with off-topic text (e.g. Kakuzi's
                # "Corporate Governance Report" row) into a parent that
                # bundles many siblings and accidentally contains the
                # "annual report" keyword from a neighbouring entry.
                # The include / exclude filters below operate on the
                # chosen title and reject non-annual rows on their own.
                stripped = txt.replace(link_text, "").strip(" |\u2013\u2014-:.,")
                if len(stripped) >= 10 and len(txt) <= 400:
                    row_text = stripped
                    break
                node = parent

        candidates = [t for t in (heading_text, row_text, link_text, title_attr) if t]
        if link_text and link_text.lower() in generic_link_text:
            title = heading_text or row_text or " | ".join(dict.fromkeys(candidates))
        else:
            title = " | ".join(dict.fromkeys(candidates))
        if not title:
            title = link.parent.get_text(" ", strip=True) if link.parent else ""

        text_blob = f"{title} {pdf_url}".lower()
        # Build a separate blob for exclude checks that uses only the
        # title and URL filename (not the full URL path). Issuers often
        # post legitimate annual reports under /agm/<year>/ directories;
        # the path word "agm" should not by itself disqualify them.
        from urllib.parse import urlparse as _urlparse_fn
        _url_filename = _urlparse_fn(pdf_url).path.rsplit("/", 1)[-1]
        exclude_blob = f"{title} {_url_filename}".lower()
        # Normalise hyphens/underscores to spaces so file slugs like
        # "Integrated-Report-2024.pdf" match the "integrated report"
        # keyword.
        text_blob_norm = re.sub(r"[-_]+", " ", text_blob)
        if not any(k in text_blob_norm for k in include_keywords):
            continue
        # Combined annual+sustainability reports legitimately contain
        # "sustainability report"; don't let that single exclude rule
        # reject them when an annual-report signal is present too.
        is_combined_annual = (
            "annual and sustainability" in text_blob_norm
            or "combined annual" in text_blob_norm
        )
        exclude_blob_norm = re.sub(r"[-_]+", " ", exclude_blob)
        if not is_combined_annual and any(k in exclude_blob_norm for k in exclude_keywords):
            continue

        fiscal_year = _extract_fiscal_year(title, pdf_url)

        # Keep annual statements only. Detect quarter/half-year markers in
        # both the title and the PDF URL because issuers vary (e.g., the
        # filename may contain "Q32024" while the heading is normalised).
        quarter = None
        quarter_match = re.search(
            r"\b(Q[1-4]|H[12]|half[- ]?year|interim)\b",
            title,
            flags=re.IGNORECASE,
        )
        if not quarter_match:
            quarter_match = re.search(
                r"(?:[\s\-_/]|^)(Q[1-4]|H[12])(?=[\s\-_/.]|\d{2,4})",
                pdf_url,
                flags=re.IGNORECASE,
            )
        if quarter_match:
            q = (
                quarter_match.group(1)
                .upper()
                .replace("HALF-YEAR", "H1")
                .replace("HALF YEAR", "H1")
                .replace("INTERIM", "H1")
            )
            quarter = q if q in {"Q1", "Q2", "Q3", "Q4", "H1", "H2"} else None
        if quarter:
            continue

        statements.append(
            {
                "title": title,
                "pdf_url": pdf_url,
                "fiscal_year": fiscal_year,
                "quarter": None,
            }
        )

    # Some CMSes (e.g., BAT Kenya's tab panels) serialise additional tab
    # content as HTML-encoded strings inside data attributes or inline
    # JS. BeautifulSoup sees them only as text. Unescape the raw HTML
    # once and re-scan for any PDF anchors we haven't already captured.
    import html as _html

    unescaped = _html.unescape(html).replace("\\u003c", "<").replace("\\u003e", ">").replace("\\\"", '"')
    if unescaped != html:
        seen_urls = {s["pdf_url"] for s in statements}
        anchor_re = re.compile(
            r'<a[^>]+href="([^"]+\.pdf[^"]*)"[^>]*>([^<]{1,300})</a>',
            flags=re.IGNORECASE,
        )
        for m in anchor_re.finditer(unescaped):
            href = m.group(1).strip()
            link_text = re.sub(r"\s+", " ", m.group(2)).strip()
            if not link_text:
                continue
            pdf_url = href if href.startswith("http") else urljoin(base_url, href)
            if pdf_url in seen_urls:
                continue

            text_blob_norm = re.sub(r"[-_]+", " ", f"{link_text} {pdf_url}".lower())
            if not any(k in text_blob_norm for k in include_keywords):
                continue
            is_combined_annual = (
                "annual and sustainability" in text_blob_norm
                or "combined annual" in text_blob_norm
            )
            if not is_combined_annual and any(k in text_blob_norm for k in exclude_keywords):
                continue

            fiscal_year = _extract_fiscal_year(link_text, pdf_url)

            quarter_match = re.search(
                r"\b(Q[1-4]|H[12]|half[- ]?year)\b",
                link_text,
                flags=re.IGNORECASE,
            )
            if not quarter_match:
                quarter_match = re.search(
                    r"(?:[\s\-_/]|^)(Q[1-4]|H[12])(?=[\s\-_/.]|\d{2,4})",
                    pdf_url,
                    flags=re.IGNORECASE,
                )
            if quarter_match:
                continue

            statements.append(
                {
                    "title": link_text,
                    "pdf_url": pdf_url,
                    "fiscal_year": fiscal_year,
                    "quarter": None,
                }
            )
            seen_urls.add(pdf_url)

    return statements


def _extract_detail_page_candidates(html: str, base_url: str) -> list[dict]:
    """Find listing entries that link to an HTML detail page (not a PDF).

    Some IR sites (e.g., Bamburi) render an archive of year-named annual
    report links that each open a per-year content page where the PDF is
    embedded. Detect those entries here so the registry can follow them.

    Returns dicts with keys: title, detail_url.
    """
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[dict] = []
    seen: set[str] = set()

    include_keywords = (
        "annual report",
        "financial statement",
        "integrated report",
        "financial year results",
        "fy results",
        "financial report",
        "annual and financial",
    )

    # Some titles (e.g., "Bamburi Cement Annual and Financial Report 2014")
    # don't contain the exact substring "annual report"; allow them via a
    # looser regex match too.
    looser_pattern = re.compile(
        r"annual\s+(?:and\s+\w+\s+)?(?:financial\s+)?report", re.IGNORECASE
    )

    base_host = (urlparse(base_url).netloc or "").lower()

    for link in soup.select("a[href]"):
        href = (link.get("href") or "").strip()
        if not href or href.startswith("#"):
            continue
        if ".pdf" in href.lower():
            continue

        text = link.get_text(" ", strip=True)
        if not text:
            continue
        low = text.lower()
        if not (any(k in low for k in include_keywords) or looser_pattern.search(low)):
            continue
        # Require an explicit 20YY year to anchor the entry.
        if not re.search(r"20\d{2}", text):
            continue

        full_url = href if href.startswith("http") else urljoin(base_url, href)
        # Only follow same-host detail pages.
        if (urlparse(full_url).netloc or "").lower() != base_host:
            continue
        if full_url == base_url or full_url in seen:
            continue
        seen.add(full_url)
        candidates.append({"title": text, "detail_url": full_url})

    return candidates


def fetch_financial_statements_list(
    base_url: str,
    max_pages: int = 5,
    timeout: int = 20,
) -> list[dict]:
    """Fetch all financial statements from a paginated financial statements URL.
    
    Args:
        base_url: The base financial statements page URL (e.g., https://kcbgroup.com/financial-statements)
        max_pages: Maximum number of pages to fetch (pagination safety limit)
        timeout: Request timeout in seconds
    
    Returns:
        List of statement dicts with keys: title, pdf_url, fiscal_year, quarter
    """
    all_statements = []
    seen_urls = set()
    
    session = _make_session(base_url)

    # Different CMS templates use different pagination query params.
    # Try the most common patterns (plain ?page=N and WordPress Search&Filter
    # ?sf_paged=N) for each page number.
    pagination_params = ["page", "sf_paged"]
    page_param_in_use: Optional[str] = None

    for page_num in range(1, max_pages + 1):
        if page_num == 1:
            page_urls = [base_url]
        elif page_param_in_use:
            page_urls = [f"{base_url}?{page_param_in_use}={page_num}"]
        else:
            page_urls = [f"{base_url}?{p}={page_num}" for p in pagination_params]

        statements: list[dict] = []
        successful_param: Optional[str] = None

        for page_url in page_urls:
            try:
                response = session.get(
                    page_url,
                    headers=_HEADERS,
                    timeout=timeout,
                    allow_redirects=True,
                )
                response.raise_for_status()
            except requests.RequestException as e:
                logger.warning("Failed to fetch page %d from %s: %s", page_num, page_url, e)
                continue

            page_statements = _extract_statements_from_html(response.text, response.url)
            new_unique = [s for s in page_statements if s["pdf_url"] not in seen_urls]
            if new_unique:
                statements = page_statements
                if page_num > 1 and "=" in page_url:
                    successful_param = page_url.split("?", 1)[1].split("=", 1)[0]
                break

        if not statements:
            logger.info("No statements found on page %d, stopping pagination", page_num)
            break

        if page_num == 2 and successful_param and not page_param_in_use:
            page_param_in_use = successful_param

        for stmt in statements:
            if stmt["pdf_url"] not in seen_urls:
                all_statements.append(stmt)
                seen_urls.add(stmt["pdf_url"])

        logger.info("Found %d statements on page %d (%d total unique)", len(statements), page_num, len(all_statements))

    # Equity exposes year-filtered docs via category endpoints rather than
    # straightforward pagination on the investor-relations landing page.
    if not all_statements and "equitygroupholdings.com" in base_url:
        parsed = urlparse(base_url)
        root = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else "https://equitygroupholdings.com"
        fallback_urls = [
            f"{root}/investor-relation/?cat=financial-results",
            f"{root}/investor-relation/?cat=annual-report",
        ]
        for fallback_url in fallback_urls:
            try:
                response = session.get(
                    fallback_url,
                    headers=_HEADERS,
                    timeout=timeout,
                    allow_redirects=True,
                )
                response.raise_for_status()
            except requests.RequestException as e:
                logger.warning("Failed Equity fallback URL %s: %s", fallback_url, e)
                continue

            statements = _extract_statements_from_html(response.text, response.url)
            for stmt in statements:
                if stmt["pdf_url"] not in seen_urls:
                    all_statements.append(stmt)
                    seen_urls.add(stmt["pdf_url"])
            logger.info("Equity fallback %s yielded %d statements", fallback_url, len(statements))

    # Some IR sites (e.g., Bamburi) link each year's annual report to a
    # detail page that embeds the PDF rather than linking the PDF
    # directly. Re-fetch the landing page to enumerate those detail
    # links, then follow each and extract the PDF.
    if len(all_statements) <= 1:
        try:
            response = session.get(
                base_url,
                headers=_HEADERS,
                timeout=timeout,
                allow_redirects=True,
            )
            response.raise_for_status()
            detail_candidates = _extract_detail_page_candidates(response.text, response.url)
        except requests.RequestException as e:
            logger.warning("Failed to re-fetch landing %s for detail pages: %s", base_url, e)
            detail_candidates = []

        for cand in detail_candidates:
            detail_url = cand["detail_url"]
            try:
                detail_resp = session.get(
                    detail_url,
                    headers={**_HEADERS, "Referer": base_url},
                    timeout=timeout,
                    allow_redirects=True,
                )
                detail_resp.raise_for_status()
            except requests.RequestException as e:
                logger.warning("Failed to fetch detail page %s: %s", detail_url, e)
                continue

            sub_statements = _extract_statements_from_html(detail_resp.text, detail_resp.url)
            # Override the title with the listing entry text so fiscal
            # year detection uses the human-curated year rather than any
            # publication year embedded in the PDF filename.
            listing_title = cand["title"]
            for sub in sub_statements:
                sub["title"] = f"{listing_title} | {sub['title']}" if sub.get("title") else listing_title
                sub["fiscal_year"] = _extract_fiscal_year(listing_title, sub["pdf_url"])
                if sub["pdf_url"] not in seen_urls:
                    all_statements.append(sub)
                    seen_urls.add(sub["pdf_url"])
            if sub_statements:
                logger.info(
                    "Detail page %s yielded %d statement(s)",
                    detail_url,
                    len(sub_statements),
                )

    # Deduplicate by fiscal year, preferring strongest annual artefacts.
    by_year: dict[int, dict] = {}
    for stmt in all_statements:
        year = stmt.get("fiscal_year")
        if not year:
            continue
        current = by_year.get(year)
        score = _statement_score(stmt)
        if not current:
            by_year[year] = {**stmt, "_score": score}
            continue
        if score > current.get("_score", 0):
            by_year[year] = {**stmt, "_score": score}

    if by_year:
        all_statements = [
            {k: v for k, v in by_year[y].items() if k != "_score"}
            for y in sorted(by_year.keys(), reverse=True)
        ]
    
    return all_statements


def download_pdf(
    url: str,
    dest_path: Path,
    timeout: int = 60,
    *,
    referer_url: str | None = None,
) -> bool:
    """Download a PDF from URL to local path.
    
    Returns True if successful, False otherwise.
    """
    settings = get_settings()
    max_bytes = settings.pdf_max_size_mb * 1024 * 1024

    # TotalEnergies / Wedia "play.html" URLs serve the player HTML rather
    # than the PDF; resolve them to the embedded ``download_url`` first.
    if "play.html?" in url.lower() and "MediaUid=" in url:
        try:
            player_resp = requests.get(
                url,
                headers=_HEADERS,
                timeout=min(timeout, 30),
                allow_redirects=True,
            )
            if player_resp.status_code == 200:
                # First try unescaped JSON (rare on Wedia, but handle it).
                m = re.search(
                    r'"download_url"\s*:\s*"([^"]+pdf[^"]*)"',
                    player_resp.text,
                )
                if not m:
                    # Wedia embeds the JSON HTML-escaped inside script content;
                    # capture lazily up to the closing &quot; (URLs contain
                    # &amp; which would otherwise terminate a [^&] class).
                    m = re.search(
                        r"download_url&quot;:&quot;(.+?pdf.*?)&quot;",
                        player_resp.text,
                    )
                if m:
                    import html as _html_mod
                    resolved = _html_mod.unescape(m.group(1))
                    logger.info("Resolved Wedia player URL -> %s", resolved)
                    url = resolved
        except requests.RequestException as e:
            logger.warning("Failed to resolve Wedia player URL %s: %s", url, e)

    download_session = _make_session(url)
    try:
        response = download_session.get(
            url,
            headers=_HEADERS,
            timeout=timeout,
            stream=True,
            allow_redirects=True,
        )
        if response.status_code in {401, 403} and referer_url:
            parsed_ref = urlparse(referer_url)
            origin = f"{parsed_ref.scheme}://{parsed_ref.netloc}" if parsed_ref.scheme and parsed_ref.netloc else None
            session = _make_session(url)
            # Warm up anti-hotlink/session checks from list page first.
            try:
                session.get(referer_url, headers=_HEADERS, timeout=min(timeout, 30), allow_redirects=True)
            except requests.RequestException:
                pass

            retry_headers = {
                **_HEADERS,
                "Referer": referer_url,
                "Accept": "application/pdf,*/*",
            }
            if origin:
                retry_headers["Origin"] = origin

            response = session.get(
                url,
                headers=retry_headers,
                timeout=timeout,
                stream=True,
                allow_redirects=True,
            )
        response.raise_for_status()
        
        total = 0
        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                total += len(chunk)
                if total > max_bytes:
                    logger.error(
                        "PDF too large (>%dMB): %s",
                        settings.pdf_max_size_mb,
                        url,
                    )
                    dest_path.unlink(missing_ok=True)
                    return False
                f.write(chunk)
        
        # Verify it's actually a PDF
        with open(dest_path, "rb") as f:
            header = f.read(5)
        if header != b"%PDF-":
            logger.error(
                "Downloaded file is not a valid PDF: %s (header: %r)",
                url,
                header,
            )
            try:
                dest_path.unlink(missing_ok=True)
            except OSError:
                pass
            return False
        
        logger.info(
            "Downloaded PDF: %s -> %s (%.1f KB)",
            url,
            dest_path,
            total / 1024,
        )
        return True
        
    except requests.RequestException as e:
        logger.error("Failed to download %s: %s", url, e)
        dest_path.unlink(missing_ok=True)
        return False


def sync_financial_statements_registry(
    company: Company,
    base_url: str,
    db: Session,
    parse_and_store: bool = True,
) -> dict:
    """Sync a company's financial statements from a paginated registry URL.
    
    Args:
        company: Company model instance
        base_url: Financial statements list URL
        db: Database session
        parse_and_store: Whether to parse PDFs and store in database
    
    Returns:
        Dict with keys: url_saved, pdfs_downloaded, pdfs_parsed, errors
    """
    result = {
        "url_saved": False,
        "pdfs_downloaded": 0,
        "pdfs_parsed": 0,
        "errors": [],
    }
    
    # Save the URL to the company record
    try:
        company.financial_statements_url = base_url
        db.add(company)
        db.commit()
        result["url_saved"] = True
        logger.info("Saved financial statements URL for %s", company.ticker_symbol)
    except Exception as e:
        logger.error("Failed to save URL for %s: %s", company.ticker_symbol, e)
        result["errors"].append(f"Failed to save URL: {str(e)}")
        return result
    
    # Fetch all statements from paginated URL
    try:
        statements = fetch_financial_statements_list(base_url)
        logger.info("Fetched %d financial statements for %s", len(statements), company.ticker_symbol)
    except Exception as e:
        logger.error("Failed to fetch statements for %s: %s", company.ticker_symbol, e)
        result["errors"].append(f"Failed to fetch statements: {str(e)}")
        return result
    
    if not statements:
        result["errors"].append("No financial statements found on URL")
        return result
    
    # Download and parse each statement
    for stmt in statements:
        if not stmt.get("fiscal_year"):
            logger.debug("Skipping statement without fiscal year: %s", stmt.get("title"))
            continue
        
        # Get or create destination path
        dest_path = _get_pdf_path(company.ticker_symbol, stmt["fiscal_year"], stmt.get("quarter"))
        
        # Skip if already downloaded
        if dest_path.exists():
            logger.debug("PDF already cached: %s", dest_path.name)
            if parse_and_store:
                try:
                    result_parse = parse_annual_report(
                        db,
                        company,
                        stmt["fiscal_year"],
                        force_redownload=False,
                        skip_if_exists=False,
                    )
                    if result_parse.get("status") == "skipped_existing":
                        logger.info(
                            "Skipped (already stored): %s FY%d",
                            company.ticker_symbol,
                            stmt["fiscal_year"],
                        )
                    elif result_parse.get("status") in {"ok", "success"}:
                        result["pdfs_parsed"] += 1
                        logger.info("Parsed (cached): %s FY%d", company.ticker_symbol, stmt["fiscal_year"])
                    else:
                        logger.warning("Parse failed for cached PDF %s: %s", dest_path.name, result_parse.get("error"))
                except Exception as e:
                    logger.error("Failed to parse cached PDF %s: %s", dest_path.name, e)
                    result["errors"].append(f"Failed to parse {dest_path.name}: {str(e)}")
            else:
                result["pdfs_downloaded"] += 1
            continue
        
        # Download PDF
        if not download_pdf(stmt["pdf_url"], dest_path, referer_url=base_url):
            result["errors"].append(f"Failed to download: {stmt['title']}")
            continue
        
        result["pdfs_downloaded"] += 1

        # Parse and store if requested
        if parse_and_store:
            try:
                result_parse = parse_annual_report(
                    db,
                    company,
                    stmt["fiscal_year"],
                    force_redownload=False,
                    skip_if_exists=False,
                )
                if result_parse.get("status") == "skipped_existing":
                    logger.info(
                        "Skipped (already stored): %s FY%d",
                        company.ticker_symbol,
                        stmt["fiscal_year"],
                    )
                elif result_parse.get("status") in {"ok", "success"}:
                    result["pdfs_parsed"] += 1
                    logger.info("Parsed and stored: %s FY%d", company.ticker_symbol, stmt["fiscal_year"])
                    # Pace OpenAI calls to stay under the 30k TPM budget.
                    # Large annual reports easily consume 20-25k tokens.
                    import time as _t
                    _t.sleep(60)
                else:
                    logger.warning("Parse warning for %s: %s", dest_path.name, result_parse.get("error"))
            except Exception as e:
                logger.error(
                    "Failed to parse %s: %s",
                    dest_path,
                    e,
                )
                result["errors"].append(f"Failed to parse {dest_path.name}: {str(e)}")
    
    return result
