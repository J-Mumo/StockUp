"""NSE scraper - scrapes stock prices from afx.kwayisi.org/nse/.

This is the primary data source for NSE stock prices. It scrapes:
1. Current day prices from the main listing page
2. Historical daily prices from individual company pages

Note: The site uses non-standard HTML (unclosed <td> tags), so we use
regex-based parsing for the history table rather than BeautifulSoup tree
traversal which fails on the nested tag structure.
"""

import logging
import re
from datetime import datetime, date
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://afx.kwayisi.org/nse"

# Regex for history table rows:
# <tr><td>YYYY-MM-DD<td>VOLUME<td>CLOSE<td class="...">CHANGE<td class="...">CHANGE%
_HISTORY_ROW_RE = re.compile(
    r"<tr><td>(\d{4}-\d{2}-\d{2})"   # date
    r"<td>([\d,]+)"                    # volume
    r"<td>([\d.]+)"                    # close price
    r"<td[^>]*>([^<]*)"               # change (may be empty)
    r"<td[^>]*>([^<]*)"               # change percent (may be empty)
)


def _parse_number(text: str) -> Optional[float]:
    """Parse a number string, handling commas and special chars."""
    if not text:
        return None
    try:
        cleaned = text.replace(",", "").replace("%", "").replace("+", "").strip()
        if not cleaned or cleaned == "-":
            return None
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _parse_date(text: str) -> Optional[date]:
    """Parse a date string in YYYY-MM-DD format."""
    if not text:
        return None
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def scrape_current_prices() -> list[dict]:
    """Scrape current day prices for all NSE companies.

    Returns list of dicts with keys: ticker, close_price, change, change_pct, volume
    """
    url = f"{BASE_URL}/"
    logger.info(f"Scraping current prices from {url}")

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch NSE page: {e}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    tables = soup.find_all("table")

    if len(tables) < 4:
        logger.error(f"Expected at least 4 tables, found {len(tables)}")
        return []

    # Use regex on the main company listing table (index 3)
    # The listing table has rows like:
    # <tr><td><a href="...">TICKER</a><td><a href="...">Company Name</a><td>VOLUME<td>PRICE<td>CHANGE
    # (Note: as of 2026, company name is wrapped in <a> and there is no
    # separate Change% column.)
    raw_html = str(tables[3])

    # Pattern: ticker link, then name link, volume, price, change
    listing_pattern = re.compile(
        r'<a[^>]*>([A-Z0-9]+)</a>'   # ticker
        r'<td><a[^>]*>[^<]*</a>'      # company name link (discarded)
        r'<td>([\d,.]*)'             # volume (may be empty)
        r'<td[^>]*>([\d.]+)'         # price
        r'<td[^>]*>([^<]*)'          # change (may be empty)
    )

    results = []
    for match in listing_pattern.finditer(raw_html):
        ticker = match.group(1).upper()
        volume = _parse_number(match.group(2))
        price = _parse_number(match.group(3))
        change = _parse_number(match.group(4))

        if price is not None:
            results.append({
                "ticker": ticker,
                "close_price": price,
                "change": change,
                "change_pct": None,
                "volume": int(volume) if volume else None,
                "price_date": date.today(),
                "source": "scraper",
            })

    logger.info(f"Scraped {len(results)} company prices")
    return results


def scrape_company_history(ticker: str) -> list[dict]:
    """Scrape historical price data for a single company.

    The afx.kwayisi.org site shows approximately 10 most recent trading days
    on each company page. Uses regex parsing to handle the non-standard HTML
    (unclosed <td> tags cause BeautifulSoup nesting issues).

    Args:
        ticker: Company ticker symbol (e.g., 'SCOM', 'EQTY')

    Returns: List of dicts with keys: price_date, close_price, change,
             change_pct, volume, source
    """
    ticker_lower = ticker.lower()
    url = f"{BASE_URL}/{ticker_lower}.html"
    logger.info(f"Scraping history for {ticker} from {url}")

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch {ticker} page: {e}")
        return []

    raw_html = response.text
    results = []

    for match in _HISTORY_ROW_RE.finditer(raw_html):
        date_str = match.group(1)
        volume_str = match.group(2)
        close_str = match.group(3)
        change_str = match.group(4)
        change_pct_str = match.group(5)

        parsed_date = _parse_date(date_str)
        close_price = _parse_number(close_str)

        if parsed_date is None or close_price is None:
            continue

        volume = _parse_number(volume_str)
        change = _parse_number(change_str)
        change_pct = _parse_number(change_pct_str)

        results.append({
            "ticker": ticker.upper(),
            "price_date": parsed_date,
            "close_price": close_price,
            "change": change,
            "change_pct": change_pct,
            "volume": int(volume) if volume else None,
            "source": "scraper",
        })

    # Sort by date descending (most recent first)
    results.sort(key=lambda x: x["price_date"], reverse=True)
    logger.info(f"Scraped {len(results)} historical prices for {ticker}")
    return results


def scrape_companies_list() -> list[dict]:
    """Scrape the list of all NSE-listed companies.

    Returns list of dicts with keys: ticker, name, href
    """
    url = f"{BASE_URL}/"
    logger.info(f"Scraping company list from {url}")

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch NSE page: {e}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")

    # Find all links to individual company pages
    companies = []
    seen_tickers = set()

    for link in soup.find_all("a"):
        href = link.get("href", "")
        if "/nse/" in href and href.endswith(".html"):
            ticker = link.get_text(strip=True).upper()
            if ticker and ticker not in seen_tickers and len(ticker) <= 10:
                seen_tickers.add(ticker)
                companies.append({
                    "ticker": ticker,
                    "href": href,
                })

    logger.info(f"Found {len(companies)} companies from scraping")
    return companies
