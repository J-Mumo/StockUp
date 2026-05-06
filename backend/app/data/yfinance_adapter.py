"""yfinance adapter for NSE stock prices.

Uses Yahoo Finance API via yfinance library. NSE tickers use the .NR suffix.
This is used as a secondary/fallback data source.
"""

import logging
from datetime import date, datetime
from typing import Optional

import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)


def fetch_history(
    yfinance_ticker: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    period: str = "max",
) -> list[dict]:
    """Fetch historical price data from yfinance.
    
    Args:
        yfinance_ticker: Yahoo Finance ticker (e.g., 'SCOM.NR')
        start_date: Start date for history (optional)
        end_date: End date for history (optional)
        period: Period string if no dates given (e.g., '1y', '5y', 'max')
        
    Returns: List of dicts with keys: price_date, open, high, low, close, volume
    """
    logger.info(f"Fetching yfinance history for {yfinance_ticker}")

    try:
        ticker = yf.Ticker(yfinance_ticker)

        if start_date and end_date:
            df = ticker.history(start=start_date.isoformat(), end=end_date.isoformat())
        elif start_date:
            df = ticker.history(start=start_date.isoformat())
        else:
            df = ticker.history(period=period)

        if df.empty:
            logger.warning(f"No data returned for {yfinance_ticker}")
            return []

        results = []
        for idx, row in df.iterrows():
            price_date = idx.date() if isinstance(idx, (datetime, pd.Timestamp)) else idx
            results.append({
                "price_date": price_date,
                "open_price": round(float(row.get("Open", 0)), 4) if pd.notna(row.get("Open")) else None,
                "high_price": round(float(row.get("High", 0)), 4) if pd.notna(row.get("High")) else None,
                "low_price": round(float(row.get("Low", 0)), 4) if pd.notna(row.get("Low")) else None,
                "close_price": round(float(row.get("Close", 0)), 4) if pd.notna(row.get("Close")) else None,
                "volume": int(row.get("Volume", 0)) if pd.notna(row.get("Volume")) else None,
                "source": "yfinance",
            })

        logger.info(f"Fetched {len(results)} prices for {yfinance_ticker}")
        return results

    except Exception as e:
        logger.error(f"yfinance error for {yfinance_ticker}: {e}")
        return []


def fetch_daily(yfinance_ticker: str) -> Optional[dict]:
    """Fetch the latest daily price from yfinance.
    
    Returns: Single dict with price data, or None if failed.
    """
    results = fetch_history(yfinance_ticker, period="5d")
    if results:
        return results[-1]  # Return most recent
    return None
