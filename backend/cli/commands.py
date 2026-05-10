"""CLI commands for data management.

Usage:
    python -m cli.commands seed-nse
    python -m cli.commands backfill-prices
    python -m cli.commands backfill-prices --ticker SCOM
    python -m cli.commands rebuild-marketscreener-prices
    python -m cli.commands rebuild-marketscreener-prices --ticker SCOM
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
from app.models.price_history import PriceHistory

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


def cmd_rebuild_marketscreener_prices(ticker: str = None, delay: float = 2.0):
    """Remove kenyanstocks price rows and rebuild from Marketscreener.

    This is the replacement path for historical NSE data.
    """
    db = SessionLocal()
    try:
        query = db.query(Company)
        if ticker:
            query = query.filter(Company.ticker_symbol == ticker.upper())
            company_count = query.count()
        else:
            query = query.filter(Company.marketscreener_graphics_url.isnot(None))
            company_count = query.count()

        if company_count == 0:
            print("[INFO] No companies matched the requested Marketscreener rebuild.")
            return

        delete_query = db.query(PriceHistory).filter(PriceHistory.source == "kenyanstocks")
        if ticker:
            company = db.query(Company).filter(Company.ticker_symbol == ticker.upper()).first()
            if company:
                delete_query = delete_query.filter(PriceHistory.company_id == company.id)

        deleted = delete_query.delete(synchronize_session=False)
        db.commit()
        print(f"[OK] Deleted {deleted} kenyanstocks price rows")
    finally:
        db.close()

    cmd_backfill_marketscreener(ticker=ticker, delay=delay)


def cmd_set_marketscreener_url(ticker: str, graphics_url: str):
    """Persist a verified Marketscreener graphics URL for a company."""
    db = SessionLocal()
    try:
        company = db.query(Company).filter(Company.ticker_symbol == ticker.upper()).first()
        if not company:
            print(f"[ERROR] Company not found: {ticker}")
            return
        company.marketscreener_graphics_url = graphics_url.strip()
        db.commit()
        print(f"[OK] Stored Marketscreener URL for {company.ticker_symbol}")
    finally:
        db.close()


def cmd_backfill_marketscreener(ticker: str = None, delay: float = 2.0):
    """Backfill prices only for companies with verified Marketscreener URLs."""
    db = SessionLocal()
    try:
        query = db.query(Company)
        if ticker:
            query = query.filter(Company.ticker_symbol == ticker.upper())
        else:
            query = query.filter(Company.marketscreener_graphics_url.isnot(None))

        companies = query.all()
        if not companies:
            print("[INFO] No companies with verified Marketscreener URLs were found.")
            return

        print(f"\n[INFO] Backfilling {len(companies)} companies from Marketscreener")
        total_upserted = 0
        failed = []

        for index, company in enumerate(companies, 1):
            print(f"  [{index}/{len(companies)}] {company.ticker_symbol}...", end=" ", flush=True)
            if not company.marketscreener_graphics_url:
                print("no verified URL")
                failed.append(company.ticker_symbol)
                continue

            try:
                stats = backfill_company_prices(db, company, delay=delay)
                total_upserted += stats["upserted"]
                print(f"{stats['upserted']} prices via {stats['source']}")
            except Exception as e:
                print(f"ERROR: {e}")
                db.rollback()
                failed.append(company.ticker_symbol)

            if index < len(companies):
                import time
                time.sleep(delay)

        print(f"\n[OK] Marketscreener backfill complete:")
        print(f"   Companies processed: {len(companies)}")
        print(f"   Total prices upserted: {total_upserted}")
        if failed:
            print(f"   Failed ({len(failed)}): {', '.join(failed)}")
    finally:
        db.close()


def cmd_sync_marketscreener_registry():
    """Sync verified Marketscreener URLs from the registry into companies."""
    from app.data.marketscreener_registry import VERIFIED_MARKETSCREENER_URLS

    db = SessionLocal()
    try:
        updated = 0
        missing = []
        for ticker, graphics_url in VERIFIED_MARKETSCREENER_URLS.items():
            company = db.query(Company).filter(Company.ticker_symbol == ticker).first()
            if not company:
                missing.append(ticker)
                continue
            if company.marketscreener_graphics_url != graphics_url:
                company.marketscreener_graphics_url = graphics_url
                updated += 1
        db.commit()
        print("[OK] Marketscreener registry sync complete:")
        print(f"   URLs updated: {updated}")
        print(f"   Registry entries: {len(VERIFIED_MARKETSCREENER_URLS)}")
        if missing:
            print(f"   Missing companies ({len(missing)}): {', '.join(missing)}")
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
                    mos = result.margin_of_safety_pct
                    mos_str = f"{mos * 100:.1f}%" if mos is not None else "N/A"
                    print(f"IV={result.weighted_intrinsic_value:.2f}, MoS={mos_str}")
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


def cmd_enrich_financials(ticker: str = None, delay: float = 2.0, force: bool = False):
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
            result = enrich_company_financials(db, company, force_overwrite=force)
            if result["status"] == "success":
                print(f"  Done! Updated: {result['updated']}, Inserted: {result['inserted']}, Rejected: {result.get('rejected', 0)}")
            else:
                print(f"  Error: {result.get('error', 'unknown')}")
        else:
            print("  Enriching financials for all companies via AI...")
            print(f"  Provider: {__import__('app.config', fromlist=['get_settings']).get_settings().ai_provider}")
            results = enrich_all_companies(db, delay=delay, force_overwrite=force)
            print(f"\n  Done! Success: {results['success']}/{results['total']}, Errors: {results['errors']}")
    finally:
        db.close()


def cmd_reenrich_financials(tickers: str = None, delay: float = 2.0):
    """Clear bad AI data and re-enrich with validated LLM output.

    Use this to fix hallucinated FCF/OCF values. Clears existing AI-sourced
    cash flow data, calls the LLM with improved prompts & validation, and
    writes only validated data back.
    """
    from app.database import SessionLocal
    from app.data.ai_enrichment import reenrich_companies
    from app.models.company import Company

    ticker_list = None
    if tickers:
        ticker_list = [t.strip().upper() for t in tickers.split(",")]

    db = SessionLocal()
    try:
        label = ", ".join(ticker_list) if ticker_list else "ALL companies"
        print(f"  Re-enriching financials for {label}...")
        print(f"  This will CLEAR existing AI-sourced FCF/OCF/CapEx values and re-fetch.")
        print(f"  Provider: {__import__('app.config', fromlist=['get_settings']).get_settings().ai_provider}")
        print()

        results = reenrich_companies(db, tickers=ticker_list, delay=delay)
        total = results["total"]
        ok = sum(1 for r in results["results"] if r["status"] == "success")
        err = sum(1 for r in results["results"] if r["status"] != "success")
        print(f"\n  Done! Success: {ok}/{total}, Errors: {err}")
    finally:
        db.close()


def cmd_download_reports(ticker: str = None, year_start: int = 2020, year_end: int = 2025):
    """Download annual report PDFs from company IR websites.

    Downloads PDFs and caches them locally for later parsing.
    Uses the IR registry to resolve download URLs.
    """
    from app.data.pdf_downloader import download_annual_report
    from app.data.ir_registry import get_all_tickers_with_ir

    if ticker:
        tickers = [ticker.upper()]
    else:
        tickers = get_all_tickers_with_ir()

    years = list(range(year_start, year_end + 1))
    print(f"\n[INFO] Downloading annual reports for {len(tickers)} companies, years {year_start}-{year_end}")
    print(f"       Cache directory: data/annual_reports/\n")

    total_downloaded = 0
    total_failed = 0

    for i, t in enumerate(tickers, 1):
        print(f"  [{i}/{len(tickers)}] {t}:", end=" ", flush=True)
        ticker_ok = 0
        ticker_fail = 0

        for year in years:
            result = download_annual_report(t, year)
            if result is None:
                ticker_fail += 1
            else:
                ticker_ok += 1

        total_downloaded += ticker_ok
        total_failed += ticker_fail
        print(f"downloaded={ticker_ok}, failed={ticker_fail}")

    print(f"\n[OK] Download complete:")
    print(f"   Total downloaded: {total_downloaded}")
    print(f"   Total failed: {total_failed}")


def cmd_parse_annual_reports(ticker: str = None, year_start: int = 2020, year_end: int = 2025,
                              delay: float = 5.0):
    """Parse downloaded annual report PDFs and extract financial data.

    Sends cached PDFs to OpenAI GPT-4.1 for structured extraction,
    validates the results, and upserts into the financial_statements table.
    PDF-sourced data takes priority over AI-enriched data.
    """
    from app.data.annual_report_parser import parse_company_reports, parse_all_companies

    years = range(year_start, year_end + 1)

    db = SessionLocal()
    try:
        if ticker:
            t = ticker.upper()
            company = db.query(Company).filter(Company.ticker_symbol == t).first()
            if not company:
                print(f"[ERROR] Company not found: {ticker}")
                return
            print(f"\n[INFO] Parsing annual reports for {t}, years {year_start}-{year_end}")
            results = parse_company_reports(db, company, years=years, delay=delay)
            ok = sum(1 for r in results if r.get("status") == "success")
            fail = sum(1 for r in results if r.get("status") != "success")
            print(f"\n[OK] Parsed {ok} reports for {t} ({fail} failed/skipped)")
            for r in results:
                status = r.get("status", "unknown")
                year = r.get("year", "?")
                if status == "success":
                    print(f"   {year}: OK — {r.get('fields_updated', '?')} fields updated")
                else:
                    print(f"   {year}: {status} — {r.get('error', 'unknown')}")
        else:
            print(f"\n[INFO] Parsing annual reports for all companies, years {year_start}-{year_end}")
            print(f"       Delay between API calls: {delay}s")
            print(f"       Using OpenAI GPT-4.1 for extraction\n")

            summary = parse_all_companies(db, tickers=None, years=years, delay=delay)
            ok = summary.get("extracted", 0)
            fail = summary.get("failed", 0)
            total = summary.get("total_years", 0)
            print(f"\n[OK] Parse complete:")
            print(f"   Companies processed: {summary.get('companies_processed', 0)}")
            print(f"   Reports extracted: {ok}/{total}")
            print(f"   No PDF available: {summary.get('no_pdf', 0)}")
            print(f"   Failed: {fail}")
    finally:
        db.close()


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m cli.commands <command> [options]")
        print("\nCommands:")
        print("  seed-nse              Seed NSE market and companies")
        print("  backfill-prices       Backfill historical prices (all sources, priority order)")
        print("  backfill-prices --ticker SCOM   Backfill for a specific company")
        print("  set-marketscreener-url --ticker KCB --url https://.../graphics/")
        print("  sync-marketscreener-registry   Sync reviewed Marketscreener URLs into companies")
        print("  backfill-marketscreener Backfill only companies with verified Marketscreener URLs")
        print("  backfill-marketscreener --ticker KCB   Backfill specific company")
        print("  rebuild-marketscreener-prices Purge kenyanstocks rows and rebuild from Marketscreener")
        print("  rebuild-marketscreener-prices --ticker KCB   Rebuild specific company")
        print("  backfill-financials   Backfill financial statements from kenyanstocks.com")
        print("  backfill-financials --ticker SCOM   Backfill specific company")
        print("  enrich-financials     Fill missing data (FCF, CapEx) using AI")
        print("  enrich-financials --ticker SCOM   Enrich specific company")
        print("  enrich-financials --force         Overwrite existing AI values")
        print("  reenrich-financials   Clear bad AI data & re-enrich with validation")
        print("  reenrich-financials --tickers KCB,EQTY,SBIC   Re-enrich specific companies")
        print("  compute-valuations    Compute intrinsic valuations for all companies")
        print("  compute-valuations --ticker SCOM   Compute for specific company")
        print("  update-prices-daily   Fetch today's prices")
        print("  import-csv            Import historical prices from CSV archive")
        print("  import-csv --dir PATH Import from a specific directory")
        print("  download-reports      Download annual report PDFs from company IR websites")
        print("  download-reports --ticker SCOM   Download for specific company")
        print("  download-reports --year-start 2020 --year-end 2025")
        print("  parse-annual-reports  Parse downloaded PDFs and extract financials via OpenAI")
        print("  parse-annual-reports --ticker SCOM   Parse for specific company")
        print("  parse-annual-reports --year-start 2020 --year-end 2025")
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
    elif command == "rebuild-marketscreener-prices":
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
        cmd_rebuild_marketscreener_prices(ticker=ticker, delay=delay)
    elif command == "set-marketscreener-url":
        ticker = None
        url = None
        if "--ticker" in sys.argv:
            idx = sys.argv.index("--ticker")
            if idx + 1 < len(sys.argv):
                ticker = sys.argv[idx + 1]
        if "--url" in sys.argv:
            idx = sys.argv.index("--url")
            if idx + 1 < len(sys.argv):
                url = sys.argv[idx + 1]
        if not ticker or not url:
            print("Usage: python -m cli.commands set-marketscreener-url --ticker KCB --url https://.../graphics/")
            return
        cmd_set_marketscreener_url(ticker=ticker, graphics_url=url)
    elif command == "sync-marketscreener-registry":
        cmd_sync_marketscreener_registry()
    elif command == "backfill-marketscreener":
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
        cmd_backfill_marketscreener(ticker=ticker, delay=delay)
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
        force = "--force" in sys.argv
        if "--ticker" in sys.argv:
            idx = sys.argv.index("--ticker")
            if idx + 1 < len(sys.argv):
                ticker = sys.argv[idx + 1]
        if "--delay" in sys.argv:
            idx = sys.argv.index("--delay")
            if idx + 1 < len(sys.argv):
                delay = float(sys.argv[idx + 1])
        cmd_enrich_financials(ticker=ticker, delay=delay, force=force)
    elif command == "reenrich-financials":
        tickers = None
        delay = 2.0
        if "--tickers" in sys.argv:
            idx = sys.argv.index("--tickers")
            if idx + 1 < len(sys.argv):
                tickers = sys.argv[idx + 1]
        if "--delay" in sys.argv:
            idx = sys.argv.index("--delay")
            if idx + 1 < len(sys.argv):
                delay = float(sys.argv[idx + 1])
        cmd_reenrich_financials(tickers=tickers, delay=delay)
    elif command == "update-prices-daily":
        cmd_update_daily()
    elif command == "import-csv":
        archive_dir = None
        if "--dir" in sys.argv:
            idx = sys.argv.index("--dir")
            if idx + 1 < len(sys.argv):
                archive_dir = sys.argv[idx + 1]
        cmd_import_csv(archive_dir=archive_dir)
    elif command == "download-reports":
        ticker = None
        year_start = 2020
        year_end = 2025
        if "--ticker" in sys.argv:
            idx = sys.argv.index("--ticker")
            if idx + 1 < len(sys.argv):
                ticker = sys.argv[idx + 1]
        if "--year-start" in sys.argv:
            idx = sys.argv.index("--year-start")
            if idx + 1 < len(sys.argv):
                year_start = int(sys.argv[idx + 1])
        if "--year-end" in sys.argv:
            idx = sys.argv.index("--year-end")
            if idx + 1 < len(sys.argv):
                year_end = int(sys.argv[idx + 1])
        cmd_download_reports(ticker=ticker, year_start=year_start, year_end=year_end)
    elif command == "parse-annual-reports":
        ticker = None
        year_start = 2020
        year_end = 2025
        delay = 5.0
        if "--ticker" in sys.argv:
            idx = sys.argv.index("--ticker")
            if idx + 1 < len(sys.argv):
                ticker = sys.argv[idx + 1]
        if "--year-start" in sys.argv:
            idx = sys.argv.index("--year-start")
            if idx + 1 < len(sys.argv):
                year_start = int(sys.argv[idx + 1])
        if "--year-end" in sys.argv:
            idx = sys.argv.index("--year-end")
            if idx + 1 < len(sys.argv):
                year_end = int(sys.argv[idx + 1])
        if "--delay" in sys.argv:
            idx = sys.argv.index("--delay")
            if idx + 1 < len(sys.argv):
                delay = float(sys.argv[idx + 1])
        cmd_parse_annual_reports(ticker=ticker, year_start=year_start, year_end=year_end, delay=delay)
    else:
        print(f"Unknown command: {command}")


if __name__ == "__main__":
    main()
