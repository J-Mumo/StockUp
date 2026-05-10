"""Price fetcher orchestrator - coordinates data sources with fallback logic.

Tries Marketscreener first when a verified graphics URL exists, then falls back
to the current scraper and yfinance.
Implements idempotent upsert to prevent duplicate price records.
"""

import logging
import time
from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.company import Company
from app.models.price_history import PriceHistory
from app.data import nse_scraper, yfinance_adapter, marketscreener_adapter
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def upsert_price(db: Session, company_id: int, price_data: dict) -> bool:
    """Insert or update a single price record (idempotent).
    
    Uses PostgreSQL ON CONFLICT to avoid duplicates.
    Returns True if a new record was inserted, False if updated/skipped.
    """
    stmt = pg_insert(PriceHistory).values(
        company_id=company_id,
        price_date=price_data["price_date"],
        open_price=price_data.get("open_price"),
        high_price=price_data.get("high_price"),
        low_price=price_data.get("low_price"),
        close_price=price_data["close_price"],
        volume=price_data.get("volume"),
        change_percent=price_data.get("change_pct"),
        source=price_data.get("source", "unknown"),
        fetched_at=datetime.utcnow(),
    )

    # On conflict, update the price data (allows corrections)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_company_price_date",
        set_={
            "open_price": stmt.excluded.open_price,
            "high_price": stmt.excluded.high_price,
            "low_price": stmt.excluded.low_price,
            "close_price": stmt.excluded.close_price,
            "volume": stmt.excluded.volume,
            "change_percent": stmt.excluded.change_percent,
            "source": stmt.excluded.source,
            "fetched_at": stmt.excluded.fetched_at,
        },
    )

    result = db.execute(stmt)
    return result.rowcount > 0


def fetch_daily_prices(db: Session) -> dict:
    """Fetch today's prices for all active companies.
    
    Strategy:
    1. Try scraper for bulk current prices (single HTTP request)
    2. For any companies not covered, try yfinance individually
    
    Returns dict with stats.
    """
    stats = {"scraped": 0, "yfinance": 0, "failed": 0, "upserted": 0}

    # Get all active companies
    companies = db.query(Company).filter(Company.is_active == True).all()
    ticker_to_company = {c.ticker_symbol: c for c in companies}

    # Step 1: Try scraper for bulk prices
    if settings.scraper_enabled:
        try:
            scraped_prices = nse_scraper.scrape_current_prices()
            for price_data in scraped_prices:
                ticker = price_data.get("ticker")
                company = ticker_to_company.get(ticker)
                if company and price_data.get("close_price"):
                    if upsert_price(db, company.id, price_data):
                        stats["upserted"] += 1
                    stats["scraped"] += 1
                    ticker_to_company.pop(ticker, None)  # Remove from remaining
        except Exception as e:
            logger.error(f"Scraper failed: {e}")

    # Step 2: Try yfinance for remaining companies
    if settings.yfinance_enabled:
        remaining = {t: c for t, c in ticker_to_company.items() if c.yfinance_ticker}
        for ticker, company in remaining.items():
            try:
                price_data = yfinance_adapter.fetch_daily(company.yfinance_ticker)
                if price_data and price_data.get("close_price"):
                    if upsert_price(db, company.id, price_data):
                        stats["upserted"] += 1
                    stats["yfinance"] += 1
                else:
                    stats["failed"] += 1
                time.sleep(0.5)  # Rate limiting for yfinance
            except Exception as e:
                logger.warning(f"yfinance failed for {ticker}: {e}")
                stats["failed"] += 1

    db.commit()
    logger.info(
        f"Daily fetch complete: scraped={stats['scraped']}, "
        f"yfinance={stats['yfinance']}, failed={stats['failed']}, "
        f"upserted={stats['upserted']}"
    )
    return stats


def backfill_company_prices(
    db: Session,
    company: Company,
    delay: float = 1.0,
) -> dict:
    """Backfill historical prices for a single company.
    
    Strategy (priority order):
    1. Try Marketscreener if a verified graphics URL is stored
    2. Try afx scraper for company history page (~10 days)
    3. Try yfinance for full history
    
    Returns dict with stats.
    """
    stats = {"total": 0, "upserted": 0, "source": "none"}

    if settings.marketscreener_enabled and company.marketscreener_graphics_url:
        try:
            prices = marketscreener_adapter.candles_to_price_rows(
                marketscreener_adapter.fetch_history_sync(company.marketscreener_graphics_url)
            )
            if prices:
                stats["source"] = "marketscreener"
                for price_data in prices:
                    if price_data.get("close_price"):
                        upsert_price(db, company.id, price_data)
                        stats["upserted"] += 1
                    stats["total"] += 1
                db.commit()
                logger.info(
                    f"Backfilled {company.ticker_symbol} via marketscreener: "
                    f"{stats['upserted']} prices"
                )
                return stats
        except Exception as e:
            logger.warning(
                f"Marketscreener backfill failed for {company.ticker_symbol}: {e}"
            )

    # Priority 1: afx scraper (~10 days)
    if settings.scraper_enabled:
        try:
            prices = nse_scraper.scrape_company_history(company.ticker_symbol)
            if prices:
                stats["source"] = "scraper"
                for price_data in prices:
                    if price_data.get("close_price"):
                        upsert_price(db, company.id, price_data)
                        stats["upserted"] += 1
                    stats["total"] += 1
                db.commit()
                logger.info(
                    f"Backfilled {company.ticker_symbol} via scraper: "
                    f"{stats['upserted']} prices"
                )
                return stats
        except Exception as e:
            logger.warning(f"Scraper backfill failed for {company.ticker_symbol}: {e}")

    # Priority 2: yfinance
    if settings.yfinance_enabled and company.yfinance_ticker:
        try:
            time.sleep(delay)  # Rate limiting
            prices = yfinance_adapter.fetch_history(company.yfinance_ticker, period="max")
            if prices:
                stats["source"] = "yfinance"
                for price_data in prices:
                    if price_data.get("close_price"):
                        upsert_price(db, company.id, price_data)
                        stats["upserted"] += 1
                    stats["total"] += 1
                db.commit()
                logger.info(
                    f"Backfilled {company.ticker_symbol} via yfinance: "
                    f"{stats['upserted']} prices"
                )
                return stats
        except Exception as e:
            logger.warning(f"yfinance backfill failed for {company.ticker_symbol}: {e}")

    logger.warning(f"No data source available for {company.ticker_symbol}")
    return stats


def backfill_all_prices(db: Session, delay: float = 2.0) -> dict:
    """Backfill historical prices for all active companies.
    
    Args:
        db: Database session
        delay: Delay between companies (seconds) for rate limiting
        
    Returns dict with overall stats.
    """
    companies = db.query(Company).filter(Company.is_active == True).all()
    overall = {"companies": len(companies), "total_prices": 0, "failed": []}

    for i, company in enumerate(companies, 1):
        logger.info(f"Backfilling {i}/{len(companies)}: {company.ticker_symbol}")
        try:
            stats = backfill_company_prices(db, company, delay=delay)
            overall["total_prices"] += stats["upserted"]
            if stats["source"] == "none":
                overall["failed"].append(company.ticker_symbol)
        except Exception as e:
            logger.error(f"Failed to backfill {company.ticker_symbol}: {e}")
            overall["failed"].append(company.ticker_symbol)
            db.rollback()

        if i < len(companies):
            time.sleep(delay)

    logger.info(
        f"Backfill complete: {overall['companies']} companies, "
        f"{overall['total_prices']} total prices, "
        f"{len(overall['failed'])} failed"
    )
    return overall
