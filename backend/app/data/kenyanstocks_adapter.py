"""KenyanStocks.com adapter — fetches historical OHLCV data from kenyanstocks.com.

This site (Nuxt 3 SSR) exposes a payload endpoint per stock that contains
~248 trading days of historical data with full OHLCV + volume.

Endpoint pattern:
    https://kenyanstocks.com/stock/nse/{TICKER}/_payload.json

The Nuxt payload is a compact JSON array where objects reference other elements
by index. We decode it by resolving those references recursively.

Data fields returned per day: date, open, high, low, close, volume
"""

import logging
import time
from datetime import date, datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://kenyanstocks.com"
_SESSION_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def _resolve_payload_value(payload: list, ref) -> any:
    """Resolve a Nuxt payload reference to its actual value.

    In Nuxt 3 payloads, dict values and list items are often integer indices
    pointing to their real value elsewhere in the root array.
    """
    if isinstance(ref, int) and 0 <= ref < len(payload):
        val = payload[ref]
        if isinstance(val, dict):
            return {k: _resolve_payload_value(payload, v) for k, v in val.items()}
        elif isinstance(val, list):
            return [_resolve_payload_value(payload, item) for item in val]
        else:
            return val
    else:
        # Direct value (string, float, bool, None, or out-of-range int that IS the value)
        return ref


def fetch_history(ticker: str, timeout: int = 30) -> list[dict]:
    """Fetch historical price data for a single NSE company from kenyanstocks.com.

    Args:
        ticker: NSE ticker symbol (e.g., 'ABSA', 'KCB', 'SCOM')
        timeout: HTTP request timeout in seconds

    Returns:
        List of dicts with keys: price_date, open_price, high_price, low_price,
        close_price, volume, source — sorted by date descending (most recent first).
        Returns empty list on failure.
    """
    url = f"{BASE_URL}/stock/nse/{ticker.upper()}/_payload.json"
    logger.info(f"Fetching history for {ticker} from kenyanstocks.com")

    try:
        response = requests.get(url, headers=_SESSION_HEADERS, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch {ticker} from kenyanstocks.com: {e}")
        return []

    try:
        payload = response.json()
    except (ValueError, TypeError) as e:
        logger.error(f"Invalid JSON from kenyanstocks.com for {ticker}: {e}")
        return []

    # Decode the Nuxt payload structure
    try:
        return _parse_payload(payload, ticker)
    except (IndexError, KeyError, TypeError) as e:
        logger.error(f"Failed to parse payload for {ticker}: {e}")
        return []


def _parse_payload(payload: list, ticker: str) -> list[dict]:
    """Parse the Nuxt 3 payload array to extract historical OHLCV data."""
    if not isinstance(payload, list) or len(payload) < 4:
        logger.warning(f"Payload for {ticker} is too short ({len(payload)} elements)")
        return []

    # Index 3 is the main API response object (keyed by route)
    api_response = payload[3]
    if not isinstance(api_response, dict):
        logger.warning(f"Expected dict at payload[3], got {type(api_response)}")
        return []

    # Navigate: api_response[data] -> data_obj[historical_data] -> list of records
    data_idx = api_response.get("data")
    if not isinstance(data_idx, int):
        logger.warning(f"No 'data' reference in api_response for {ticker}")
        return []

    data_obj = payload[data_idx]
    if not isinstance(data_obj, dict):
        logger.warning(f"Expected dict at payload[{data_idx}], got {type(data_obj)}")
        return []

    hist_ref = data_obj.get("historical_data")
    if hist_ref is None:
        logger.warning(f"No 'historical_data' in data object for {ticker}")
        return []

    # Resolve the historical data list
    if isinstance(hist_ref, int):
        hist_list = payload[hist_ref]
    elif isinstance(hist_ref, list):
        hist_list = hist_ref
    else:
        logger.warning(f"Unexpected historical_data type for {ticker}: {type(hist_ref)}")
        return []

    if not isinstance(hist_list, list):
        logger.warning(f"historical_data is not a list for {ticker}")
        return []

    # Resolve each entry
    results = []
    for item_ref in hist_list:
        try:
            entry = _resolve_payload_value(payload, item_ref)
            if not isinstance(entry, dict):
                continue

            price_date = _parse_date(entry.get("date"))
            close_price = _safe_float(entry.get("close"))

            if price_date is None or close_price is None:
                continue

            results.append({
                "ticker": ticker.upper(),
                "price_date": price_date,
                "open_price": _safe_float(entry.get("open")),
                "high_price": _safe_float(entry.get("high")),
                "low_price": _safe_float(entry.get("low")),
                "close_price": close_price,
                "volume": _safe_int(entry.get("volume")),
                "source": "kenyanstocks",
            })
        except Exception as e:
            logger.debug(f"Skipping entry for {ticker}: {e}")
            continue

    # Sort by date descending (most recent first)
    results.sort(key=lambda x: x["price_date"], reverse=True)
    logger.info(f"Fetched {len(results)} historical prices for {ticker} from kenyanstocks.com")
    return results


def fetch_current_price(ticker: str, timeout: int = 30) -> Optional[dict]:
    """Fetch the most recent price for a ticker (today or last trading day).

    Returns a single dict with price data, or None if unavailable.
    """
    prices = fetch_history(ticker, timeout=timeout)
    if prices:
        return prices[0]  # Most recent (sorted desc)
    return None


def fetch_all_current_prices(tickers: list[str], delay: float = 1.0) -> list[dict]:
    """Fetch current prices for multiple tickers.

    Args:
        tickers: List of NSE ticker symbols
        delay: Delay between requests (seconds) for rate limiting

    Returns:
        List of dicts, one per ticker (most recent price entry)
    """
    results = []
    for i, ticker in enumerate(tickers):
        price = fetch_current_price(ticker)
        if price:
            results.append(price)
        if i < len(tickers) - 1:
            time.sleep(delay)
    return results


def _parse_date(value) -> Optional[date]:
    """Parse a date value (string or already date)."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None
    return None


def _safe_float(value) -> Optional[float]:
    """Safely convert a value to float."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _safe_int(value) -> Optional[int]:
    """Safely convert a value to int."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
