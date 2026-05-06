"""Celery tasks for price data ingestion.

Scheduled daily at 6PM EAT (15:00 UTC) via Celery Beat.
"""

import logging
from datetime import datetime

from tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="tasks.price_tasks.fetch_all_prices",
    bind=True,
    max_retries=3,
    default_retry_delay=120,
    acks_late=True,
)
def fetch_all_prices(self):
    """Fetch daily prices for all active companies.

    Uses the price_fetcher orchestrator which tries:
      1. NSE scraper (afx.kwayisi.org)
      2. yfinance fallback

    Retries up to 3 times with 2-minute backoff on transient failures.
    """
    from app.database import SessionLocal
    from app.data.price_fetcher import fetch_daily_prices

    started_at = datetime.utcnow()
    logger.info(f"[price_tasks] Starting daily price fetch at {started_at.isoformat()}")

    db = SessionLocal()
    try:
        result = fetch_daily_prices(db)
        db.commit()

        elapsed = (datetime.utcnow() - started_at).total_seconds()
        logger.info(
            f"[price_tasks] Daily fetch complete in {elapsed:.1f}s — "
            f"inserted={result.get('inserted', 0)}, "
            f"updated={result.get('updated', 0)}, "
            f"errors={result.get('errors', 0)}"
        )
        return {
            "status": "success",
            "inserted": result.get("inserted", 0),
            "updated": result.get("updated", 0),
            "errors": result.get("errors", 0),
            "elapsed_seconds": elapsed,
        }
    except Exception as exc:
        db.rollback()
        logger.error(f"[price_tasks] Daily fetch failed: {exc}", exc_info=True)
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(
    name="tasks.price_tasks.backfill_company",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def backfill_company(self, ticker: str, days: int = 365):
    """Backfill historical prices for a single company.

    Args:
        ticker: Company ticker symbol (e.g., "SCOM").
        days: Number of days of history to fetch (default: 365).
    """
    from app.database import SessionLocal
    from app.data.price_fetcher import backfill_company_prices
    from app.models.company import Company

    logger.info(f"[price_tasks] Backfilling {ticker} for {days} days")

    db = SessionLocal()
    try:
        company = db.query(Company).filter(Company.ticker_symbol == ticker).first()
        if not company:
            logger.warning(f"[price_tasks] Company not found: {ticker}")
            return {"status": "error", "message": f"Company not found: {ticker}"}

        result = backfill_company_prices(db, company, days=days)
        db.commit()

        logger.info(f"[price_tasks] Backfill {ticker}: {result}")
        return {"status": "success", "ticker": ticker, **result}
    except Exception as exc:
        db.rollback()
        logger.error(f"[price_tasks] Backfill {ticker} failed: {exc}", exc_info=True)
        raise self.retry(exc=exc)
    finally:
        db.close()
