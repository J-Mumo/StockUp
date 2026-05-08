"""Celery tasks for valuation recalculation and financial data refresh.

Scheduled tasks:
- Daily at 7PM EAT (16:00 UTC): Recalculate all valuations (after price fetch)
- Monthly on 1st at 2AM EAT (23:00 UTC prev day): Refresh financial statements
"""

import logging
from datetime import datetime

from tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="tasks.valuation_tasks.recalculate_all_valuations",
    bind=True,
    max_retries=2,
    default_retry_delay=180,
    acks_late=True,
)
def recalculate_all_valuations(self):
    """Recalculate intrinsic valuations for all active companies.

    Uses the valuation engine (DCF + EPV + Book Value composite) to
    produce updated intrinsic value snapshots. Skips companies without
    sufficient financial data.

    Runs after the daily price fetch so that MOS reflects current prices.
    """
    from app.database import SessionLocal
    from app.services.valuation_engine import compute_all_valuations

    started_at = datetime.utcnow()
    logger.info(f"[valuation_tasks] Starting valuation recalc at {started_at.isoformat()}")

    db = SessionLocal()
    try:
        results = compute_all_valuations(db)

        # Tally outcomes
        successes = sum(1 for r in results.values() if not isinstance(r, str))
        skipped = sum(1 for r in results.values() if isinstance(r, str))

        elapsed = (datetime.utcnow() - started_at).total_seconds()
        logger.info(
            f"[valuation_tasks] Recalc complete in {elapsed:.1f}s — "
            f"valued={successes}, skipped={skipped}"
        )
        return {
            "status": "success",
            "companies_valued": successes,
            "companies_skipped": skipped,
            "elapsed_seconds": elapsed,
        }
    except Exception as exc:
        db.rollback()
        logger.error(f"[valuation_tasks] Recalc failed: {exc}", exc_info=True)
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(
    name="tasks.valuation_tasks.recalculate_single",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def recalculate_single(self, company_id: int):
    """Recalculate valuation for a single company.

    Useful for on-demand recalculation after new financial data is entered.

    Args:
        company_id: ID of the company to revalue.
    """
    from app.database import SessionLocal
    from app.services.valuation_engine import compute_valuation

    logger.info(f"[valuation_tasks] Recalculating company_id={company_id}")

    db = SessionLocal()
    try:
        result = compute_valuation(db, company_id)
        db.commit()

        if isinstance(result, str):
            logger.warning(
                f"[valuation_tasks] Skipped company_id={company_id}: {result}"
            )
            return {"status": "skipped", "company_id": company_id, "reason": result}

        logger.info(
            f"[valuation_tasks] Valued company_id={company_id}: "
            f"IV={result.weighted_intrinsic_value}, MOS={result.margin_of_safety_pct}"
        )
        return {
            "status": "success",
            "company_id": company_id,
            "intrinsic_value": result.weighted_intrinsic_value,
            "margin_of_safety": result.margin_of_safety_pct,
        }
    except Exception as exc:
        db.rollback()
        logger.error(
            f"[valuation_tasks] Recalc company_id={company_id} failed: {exc}",
            exc_info=True,
        )
        raise self.retry(exc=exc)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Monthly Financial Statements Refresh
# ---------------------------------------------------------------------------


@celery_app.task(
    name="tasks.valuation_tasks.refresh_all_financials",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
    acks_late=True,
)
def refresh_all_financials(self):
    """Refresh financial statements for all active companies from kenyanstocks.com.

    Runs monthly to pick up newly released annual/quarterly financials.
    After refreshing, automatically recomputes valuations for any company
    that received new data.

    Flow:
        1. Fetch latest financials from kenyanstocks.com for all companies
        2. Upsert new records (new fiscal years) into DB
        3. Recompute valuations for companies with new data
        4. Trigger alerts for companies with material IV changes
    """
    from app.database import SessionLocal
    from app.data.financials_fetcher import backfill_all_financials
    from app.services.valuation_engine import compute_valuation
    from app.routers.alerts import check_and_trigger_alerts
    from app.models.company import Company

    started_at = datetime.utcnow()
    logger.info(f"[valuation_tasks] Starting monthly financials refresh at {started_at.isoformat()}")

    db = SessionLocal()
    try:
        # Step 1: Fetch and upsert financials
        summary = backfill_all_financials(db, delay=1.5)
        logger.info(
            f"[valuation_tasks] Financials refresh: "
            f"success={summary['success_count']}, "
            f"failed={summary['failed_count']}, "
            f"upserted={summary['total_records_upserted']}"
        )

        # Step 2: Recompute valuations for companies that got new data
        if summary["total_records_upserted"] > 0:
            companies = (
                db.query(Company)
                .filter(Company.is_active == True)
                .all()
            )

            valued = 0
            for company in companies:
                result = compute_valuation(db, company.id)
                if not isinstance(result, str):
                    valued += 1
                    # Step 3: Check alerts
                    try:
                        check_and_trigger_alerts(db, company.id)
                    except Exception as alert_err:
                        logger.warning(
                            f"[valuation_tasks] Alert check failed for {company.ticker_symbol}: {alert_err}"
                        )

            db.commit()
            logger.info(f"[valuation_tasks] Recomputed valuations for {valued} companies")
        else:
            logger.info("[valuation_tasks] No new financial records — skipping valuation recompute")

        elapsed = (datetime.utcnow() - started_at).total_seconds()
        logger.info(f"[valuation_tasks] Monthly refresh complete in {elapsed:.1f}s")

        return {
            "status": "success",
            "financials_upserted": summary["total_records_upserted"],
            "companies_success": summary["success_count"],
            "companies_failed": summary["failed_count"],
            "shares_updated": summary.get("shares_updated_count", 0),
            "elapsed_seconds": elapsed,
        }
    except Exception as exc:
        db.rollback()
        logger.error(f"[valuation_tasks] Monthly refresh failed: {exc}", exc_info=True)
        raise self.retry(exc=exc)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Monthly Annual Report Parsing (PDF → OpenAI extraction)
# ---------------------------------------------------------------------------


@celery_app.task(
    name="tasks.valuation_tasks.parse_annual_reports",
    bind=True,
    max_retries=1,
    default_retry_delay=600,
    acks_late=True,
    time_limit=7200,  # 2 hour hard limit
    soft_time_limit=6600,  # 1h50m soft limit
)
def parse_annual_reports(self):
    """Parse annual report PDFs for all companies and extract financial data.

    Downloads PDFs from company IR websites (if not cached), sends them to
    OpenAI GPT-4.1 for structured extraction, validates results, and upserts
    into the DB. After parsing, recomputes valuations for any company that
    received new data.

    Runs monthly on the 5th at 3AM EAT (00:00 UTC) — a few days after
    companies typically publish reports.
    """
    from app.database import SessionLocal
    from app.data.annual_report_parser import parse_all_companies
    from app.services.valuation_engine import compute_valuation
    from app.models.company import Company

    started_at = datetime.utcnow()
    current_year = started_at.year
    # Parse current year and previous year (reports may be published with a lag)
    years = range(current_year - 1, current_year + 1)

    logger.info(
        f"[valuation_tasks] Starting annual report parsing at {started_at.isoformat()} "
        f"for years {list(years)}"
    )

    db = SessionLocal()
    try:
        # Step 1: Parse reports for all active companies
        summary = parse_all_companies(db, tickers=None, years=years, delay=5.0)

        parsed = summary.get("extracted", 0)
        failed = summary.get("failed", 0)
        logger.info(
            f"[valuation_tasks] Report parsing complete: "
            f"parsed={parsed}, failed={failed}"
        )

        # Step 2: Recompute valuations if any data was extracted
        valued = 0
        if parsed > 0:
            companies = (
                db.query(Company)
                .filter(Company.is_active == True)
                .all()
            )
            for company in companies:
                try:
                    result = compute_valuation(db, company.id)
                    if not isinstance(result, str):
                        valued += 1
                except Exception as val_err:
                    logger.warning(
                        f"[valuation_tasks] Valuation failed for {company.ticker_symbol}: {val_err}"
                    )
            db.commit()
            logger.info(f"[valuation_tasks] Recomputed valuations for {valued} companies")

        elapsed = (datetime.utcnow() - started_at).total_seconds()
        logger.info(f"[valuation_tasks] Annual report task complete in {elapsed:.1f}s")

        return {
            "status": "success",
            "reports_parsed": parsed,
            "reports_failed": failed,
            "companies_revalued": valued,
            "years": list(years),
            "elapsed_seconds": elapsed,
        }
    except Exception as exc:
        db.rollback()
        logger.error(f"[valuation_tasks] Annual report parsing failed: {exc}", exc_info=True)
        raise self.retry(exc=exc)
    finally:
        db.close()
