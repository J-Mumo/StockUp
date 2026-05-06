"""CLI commands for data management.

Usage:
    python -m cli.commands seed-nse
    python -m cli.commands backfill-prices
    python -m cli.commands backfill-prices --ticker SCOM
    python -m cli.commands backfill-kenyanstocks
    python -m cli.commands backfill-kenyanstocks --ticker SCOM
    python -m cli.commands update-prices-daily
"""

import sys
import logging
from pathlib import Path

# Add backend dir to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.data.seed_data import seed_nse_market_and_companies
from app.data.price_fetcher import backfill_all_prices, backfill_company_prices, fetch_daily_prices
from app.models.company import Company

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def cmd_seed_nse():
    """Seed NSE market and companies."""
    logger.info("Seeding NSE market and companies...")
    db = SessionLocal()
    try:
        stats = seed_nse_market_and_companies(db)
        logger.info(f"Seed results: {stats}")
        print(f"\n[OK] Seed complete:")
        print(f"   Market: {stats['market']}")
        print(f"   Companies created: {stats['companies_created']}")
        print(f"   Companies existing: {stats['companies_existing']}")
    finally:
        db.close()


def cmd_backfill_prices(ticker: str = None, delay: float = 2.0):
    """Backfill historical prices."""
    db = SessionLocal()
    try:
        if ticker:
            company = db.query(Company).filter(Company.ticker_symbol == ticker.upper()).first()
            if not company:
                print(f"[ERROR] Company not found: {ticker}")
                return
            logger.info(f"Backfilling prices for {company.ticker_symbol}...")
            stats = backfill_company_prices(db, company, delay=delay)
            print(f"\n[OK] Backfill complete for {company.ticker_symbol}:")
            print(f"   Source: {stats['source']}")
            print(f"   Prices upserted: {stats['upserted']}")
        else:
            logger.info("Backfilling prices for all companies...")
            stats = backfill_all_prices(db, delay=delay)
            print(f"\n[OK] Backfill complete:")
            print(f"   Companies: {stats['companies']}")
            print(f"   Total prices: {stats['total_prices']}")
            if stats['failed']:
                print(f"   Failed: {', '.join(stats['failed'])}")
    finally:
        db.close()


def cmd_update_daily():
    """Fetch today's prices for all companies."""
    logger.info("Fetching daily prices...")
    db = SessionLocal()
    try:
        stats = fetch_daily_prices(db)
        print(f"\n[OK] Daily update complete:")
        print(f"   Scraped: {stats['scraped']}")
        print(f"   yfinance: {stats['yfinance']}")
        print(f"   Failed: {stats['failed']}")
        print(f"   Upserted: {stats['upserted']}")
    finally:
        db.close()


def cmd_backfill_kenyanstocks(ticker: str = None, delay: float = 1.5):
    """Backfill historical prices exclusively from kenyanstocks.com.
    
    This source provides ~248 days of OHLCV data per company.
    """
    from app.data import kenyanstocks_adapter
    from app.data.price_fetcher import upsert_price
    import time

    db = SessionLocal()
    try:
        if ticker:
            companies = db.query(Company).filter(
                Company.ticker_symbol == ticker.upper()
            ).all()
            if not companies:
                print(f"[ERROR] Company not found: {ticker}")
                return
        else:
            companies = db.query(Company).filter(Company.is_active == True).all()

        print(f"\n[INFO] Backfilling {len(companies)} companies from kenyanstocks.com")
        total_upserted = 0
        failed = []

        for i, company in enumerate(companies, 1):
            print(f"  [{i}/{len(companies)}] {company.ticker_symbol}...", end=" ", flush=True)
            try:
                prices = kenyanstocks_adapter.fetch_history(company.ticker_symbol)
                if prices:
                    count = 0
                    for price_data in prices:
                        if price_data.get("close_price"):
                            upsert_price(db, company.id, price_data)
                            count += 1
                    db.commit()
                    total_upserted += count
                    print(f"{count} prices")
                else:
                    print("no data")
                    failed.append(company.ticker_symbol)
            except Exception as e:
                print(f"ERROR: {e}")
                failed.append(company.ticker_symbol)
                db.rollback()

            if i < len(companies):
                time.sleep(delay)

        print(f"\n[OK] Backfill complete:")
        print(f"   Companies processed: {len(companies)}")
        print(f"   Total prices upserted: {total_upserted}")
        if failed:
            print(f"   Failed ({len(failed)}): {', '.join(failed)}")
    finally:
        db.close()


def cmd_import_csv(archive_dir: str = None):
    """Import historical prices from CSV archive files."""
    from cli.import_csv import import_all_csvs, DEFAULT_ARCHIVE_DIR

    target_dir = archive_dir or DEFAULT_ARCHIVE_DIR
    logger.info(f"Importing CSV archives from: {target_dir}")
    result = import_all_csvs(target_dir)
    print(f"\n[OK] CSV Import complete:")
    print(f"   Files processed: {result.get('files_processed', 0)}")
    print(f"   Total rows read: {result.get('total_rows', 0)}")
    print(f"   Prices imported: {result.get('total_imported', 0)}")
    print(f"   Rows skipped:    {result.get('total_skipped', 0)}")
    if result.get("all_unmatched_tickers"):
        print(f"   Unmatched tickers ({len(result['all_unmatched_tickers'])}): {', '.join(result['all_unmatched_tickers'])}")


def cmd_backfill_financials(ticker: str = None, delay: float = 1.5):
    """Backfill financial statements from kenyanstocks.com.

    Fetches 4 years of annual financial data (income statement, balance sheet,
    cash flow, ratios) for all active companies or a single specified company.
    """
    from app.data.financials_fetcher import backfill_company_financials, backfill_all_financials

    db = SessionLocal()
    try:
        if ticker:
            company = db.query(Company).filter(Company.ticker_symbol == ticker.upper()).first()
            if not company:
                print(f"[ERROR] Company not found: {ticker}")
                return
            print(f"Backfilling financials for {company.name} ({company.ticker_symbol})...")
            result = backfill_company_financials(db, company)
            if result["error"]:
                print(f"[FAILED] {result['error']}")
            else:
                print(f"[OK] Fetched {result['records_fetched']} records, upserted {result['records_upserted']}")
                if result.get("shares_updated"):
                    print(f"   Updated shares_outstanding for {company.ticker_symbol}")
        else:
            print("Backfilling financials for all active companies from kenyanstocks.com...")
            summary = backfill_all_financials(db, delay=delay)
            print(f"\n[OK] Financials backfill complete:")
            print(f"   Companies processed: {summary['total_companies']}")
            print(f"   Successful: {summary['success_count']}")
            print(f"   Failed: {summary['failed_count']}")
            print(f"   Total records upserted: {summary['total_records_upserted']}")
            print(f"   Shares outstanding updated: {summary['shares_updated_count']}")
            if summary["failures"]:
                print(f"\n   Failures:")
                for f in summary["failures"]:
                    print(f"     - {f}")
    finally:
        db.close()


def cmd_compute_valuations(ticker: str = None):
    """Compute intrinsic valuations for all companies (or a single ticker)."""
    from app.database import SessionLocal
    from app.services.valuation_engine import compute_valuation, compute_all_valuations, ValuationResult
    from app.models.company import Company

    db = SessionLocal()
    try:
        if ticker:
            company = db.query(Company).filter(Company.ticker_symbol == ticker.upper()).first()
            if not company:
                print(f"  Company '{ticker}' not found.")
                return
            print(f"  Computing valuation for {company.ticker_symbol}...", end=" ", flush=True)
            try:
                result = compute_valuation(db, company.id)
                db.commit()
                if result and result.weighted_intrinsic_value:
                    print(f"IV={result.weighted_intrinsic_value:.2f}, MoS={result.margin_of_safety:.1f}%")
                else:
                    print("Insufficient data")
            except Exception as e:
                print(f"Error: {e}")
        else:
            print("  Computing valuations for all companies...")
            results = compute_all_valuations(db)
            computed = sum(1 for v in results.values() if isinstance(v, ValuationResult))
            errors = [(k, v) for k, v in results.items() if isinstance(v, str)]
            print(f"\n  Done! Computed: {computed}, Errors: {len(errors)}, Total: {len(results)}")
            if errors:
                print("  Errors:")
                for company_id, err in errors[:10]:
                    print(f"    - Company #{company_id}: {err}")
                if len(errors) > 10:
                    print(f"    ... and {len(errors) - 10} more")
    finally:
        db.close()


def cmd_enrich_financials(ticker: str = None, delay: float = 2.0):
    """Enrich financial data using AI (fill in FCF, CapEx, etc.)."""
    from app.database import SessionLocal
    from app.data.ai_enrichment import enrich_company_financials, enrich_all_companies
    from app.models.company import Company

    db = SessionLocal()
    try:
        if ticker:
            company = db.query(Company).filter(Company.ticker_symbol == ticker.upper()).first()
            if not company:
                print(f"  Company '{ticker}' not found.")
                return
            print(f"  Enriching financials for {company.ticker_symbol} via AI...")
            result = enrich_company_financials(db, company)
            if result["status"] == "success":
                print(f"  Done! Updated: {result['updated']}, Inserted: {result['inserted']}")
            else:
                print(f"  Error: {result.get('error', 'unknown')}")
        else:
            print("  Enriching financials for all companies via AI...")
            print(f"  Provider: {__import__('app.config', fromlist=['get_settings']).get_settings().ai_provider}")
            results = enrich_all_companies(db, delay=delay)
            print(f"\n  Done! Success: {results['success']}/{results['total']}, Errors: {results['errors']}")
    finally:
        db.close()


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m cli.commands <command> [options]")
        print("\nCommands:")
        print("  seed-nse              Seed NSE market and companies")
        print("  backfill-prices       Backfill historical prices (all sources, priority order)")
        print("  backfill-prices --ticker SCOM   Backfill for a specific company")
        print("  backfill-kenyanstocks Backfill from kenyanstocks.com (~248 days OHLCV)")
        print("  backfill-kenyanstocks --ticker SCOM   Backfill specific company")
        print("  backfill-financials   Backfill financial statements from kenyanstocks.com")
        print("  backfill-financials --ticker SCOM   Backfill specific company")
        print("  enrich-financials     Fill missing data (FCF, CapEx) using AI")
        print("  enrich-financials --ticker SCOM   Enrich specific company")
        print("  compute-valuations    Compute intrinsic valuations for all companies")
        print("  compute-valuations --ticker SCOM   Compute for specific company")
        print("  update-prices-daily   Fetch today's prices")
        print("  import-csv            Import historical prices from CSV archive")
        print("  import-csv --dir PATH Import from a specific directory")
        return

    command = sys.argv[1]

    if command == "seed-nse":
        cmd_seed_nse()
    elif command == "backfill-prices":
        ticker = None
        delay = 2.0
        if "--ticker" in sys.argv:
            idx = sys.argv.index("--ticker")
            if idx + 1 < len(sys.argv):
                ticker = sys.argv[idx + 1]
        if "--delay" in sys.argv:
            idx = sys.argv.index("--delay")
            if idx + 1 < len(sys.argv):
                delay = float(sys.argv[idx + 1])
        cmd_backfill_prices(ticker=ticker, delay=delay)
    elif command == "backfill-kenyanstocks":
        ticker = None
        delay = 1.5
        if "--ticker" in sys.argv:
            idx = sys.argv.index("--ticker")
            if idx + 1 < len(sys.argv):
                ticker = sys.argv[idx + 1]
        if "--delay" in sys.argv:
            idx = sys.argv.index("--delay")
            if idx + 1 < len(sys.argv):
                delay = float(sys.argv[idx + 1])
        cmd_backfill_kenyanstocks(ticker=ticker, delay=delay)
    elif command == "backfill-financials":
        ticker = None
        delay = 2.0
        if "--ticker" in sys.argv:
            idx = sys.argv.index("--ticker")
            if idx + 1 < len(sys.argv):
                ticker = sys.argv[idx + 1]
        if "--delay" in sys.argv:
            idx = sys.argv.index("--delay")
            if idx + 1 < len(sys.argv):
                delay = float(sys.argv[idx + 1])
        cmd_backfill_financials(ticker=ticker, delay=delay)
    elif command == "compute-valuations":
        ticker = None
        if "--ticker" in sys.argv:
            idx = sys.argv.index("--ticker")
            if idx + 1 < len(sys.argv):
                ticker = sys.argv[idx + 1]
        cmd_compute_valuations(ticker=ticker)
    elif command == "enrich-financials":
        ticker = None
        delay = 2.0
        if "--ticker" in sys.argv:
            idx = sys.argv.index("--ticker")
            if idx + 1 < len(sys.argv):
                ticker = sys.argv[idx + 1]
        if "--delay" in sys.argv:
            idx = sys.argv.index("--delay")
            if idx + 1 < len(sys.argv):
                delay = float(sys.argv[idx + 1])
        cmd_enrich_financials(ticker=ticker, delay=delay)
    elif command == "update-prices-daily":
        cmd_update_daily()
    elif command == "import-csv":
        archive_dir = None
        if "--dir" in sys.argv:
            idx = sys.argv.index("--dir")
            if idx + 1 < len(sys.argv):
                archive_dir = sys.argv[idx + 1]
        cmd_import_csv(archive_dir=archive_dir)
    else:
        print(f"Unknown command: {command}")


if __name__ == "__main__":
    main()
