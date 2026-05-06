"""CSV import script for historical NSE price archives.

Imports CSV files from C:\\Users\\JOEL\\Downloads\\stock-archives\\archive\\
into the price_history table using idempotent upsert.

Usage:
    python -m cli.commands import-csv
    python -m cli.commands import-csv --dir "C:\\path\\to\\csv\\folder"
    python -m cli.commands import-csv --file "path_to_single_file.csv"
"""

import csv
import logging
import os
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.company import Company
from app.data.price_fetcher import upsert_price

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Default archive directory
DEFAULT_ARCHIVE_DIR = r"C:\Users\JOEL\Downloads\stock-archives\archive"

# Historical ticker aliases — maps old/variant ticker codes to current DB ticker_symbol.
# These cover NSE name changes, mergers, and rebrandings over 2007-2025.
TICKER_ALIASES = {
    # Banking sector rebrandings
    "BBK": "ABSA",       # Barclays Bank Kenya → ABSA Bank Kenya (2020)
    "CFC": "SBIC",       # CFC Stanbic Holdings → Stanbic Holdings
    "NIC": "NCBA",       # NIC Bank → merged into NCBA Group (2019)
    "NBK": "KCB",        # National Bank of Kenya → acquired by KCB (2020)

    # Company rebrandings
    "FIRE": "SMER",      # Firestone East Africa → Sameer Africa
    "C&G": "CGEN",       # Car & General shorthand
    "ARM": "ARMC",       # ARM Cement (delisted 2018, may not match)
    "PAFR": "PANL",      # Pan Africa Insurance → Pan Africa Life (if applicable)
    "ICDC": "CDSC",      # ICDC → Central Depository

    # ETFs/Indices  
    "NSE20": None,       # NSE 20-Share Index — skip, not a company
    "NSE25": None,       # NSE 25-Share Index — skip
    "NSEASI": None,      # NSE All-Share Index — skip

    # Old tickers that are the same as current
    "SCOM": "SCOM",
    "EQTY": "EQTY",
    "KCB": "KCB",
    "SCBK": "SCBK",
}


def parse_date_flexible(date_str: str) -> Optional[date]:
    """Parse dates in multiple formats found in the CSV files.

    Formats found:
    - '2-Jan-25' (D-Mon-YY) — 2025 format
    - '1/2/2007' (M/D/YYYY) — 2007 format
    - '2007-01-02' (ISO) — unlikely but handle
    """
    date_str = date_str.strip()
    if not date_str:
        return None

    # Try D-Mon-YY format (e.g., "2-Jan-25")
    try:
        return datetime.strptime(date_str, "%d-%b-%y").date()
    except ValueError:
        pass

    # Try M/D/YYYY format (e.g., "1/2/2007")
    try:
        return datetime.strptime(date_str, "%m/%d/%Y").date()
    except ValueError:
        pass

    # Try D/M/YYYY format (e.g., "2/1/2007")
    try:
        return datetime.strptime(date_str, "%d/%m/%Y").date()
    except ValueError:
        pass

    # Try ISO format
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        pass

    return None


def parse_number(text: str) -> Optional[float]:
    """Parse a number, handling commas, percentage signs, dashes."""
    if not text:
        return None
    cleaned = text.strip().replace(",", "").replace("%", "").replace('"', '')
    if not cleaned or cleaned == "-" or cleaned == "–":
        return None
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def parse_volume(text: str) -> Optional[int]:
    """Parse volume which may have commas and be quoted."""
    val = parse_number(text)
    if val is not None:
        return int(val)
    return None


def build_company_lookup(db: Session) -> dict[str, int]:
    """Build ticker_symbol → company_id lookup including aliases."""
    companies = db.query(Company).filter(Company.is_active == True).all()
    lookup = {}

    # Direct ticker → id mapping
    for c in companies:
        lookup[c.ticker_symbol.upper()] = c.id

    # Add aliases that map to existing companies
    for alias, target in TICKER_ALIASES.items():
        if target is None:
            continue  # Skip indices
        if target.upper() in lookup and alias.upper() not in lookup:
            lookup[alias.upper()] = lookup[target.upper()]

    return lookup


def import_csv_file(
    db: Session,
    filepath: Path,
    company_lookup: dict[str, int],
) -> dict:
    """Import a single CSV file into the database.

    Returns stats dict.
    """
    stats = {
        "file": filepath.name,
        "rows_total": 0,
        "rows_imported": 0,
        "rows_skipped_no_ticker": 0,
        "rows_skipped_no_price": 0,
        "rows_skipped_no_date": 0,
        "unmatched_tickers": set(),
    }

    with open(filepath, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)

        # Normalize column names (handle case differences)
        batch_count = 0

        for row in reader:
            stats["rows_total"] += 1

            # Get ticker code (handle both column name variants)
            code = (row.get("Code") or row.get("CODE") or "").strip().upper()
            if not code:
                stats["rows_skipped_no_ticker"] += 1
                continue

            # Skip known index entries
            if TICKER_ALIASES.get(code) is None and code in TICKER_ALIASES:
                stats["rows_skipped_no_ticker"] += 1
                continue

            # Resolve ticker to company_id
            company_id = company_lookup.get(code)
            if company_id is None:
                stats["unmatched_tickers"].add(code)
                stats["rows_skipped_no_ticker"] += 1
                continue

            # Parse date
            date_str = (row.get("Date") or row.get("DATE") or "").strip()
            price_date = parse_date_flexible(date_str)
            if price_date is None:
                stats["rows_skipped_no_date"] += 1
                continue

            # Parse price data
            close_price = parse_number(row.get("Day Price", ""))
            if close_price is None or close_price <= 0:
                stats["rows_skipped_no_price"] += 1
                continue

            low_price = parse_number(row.get("Day Low", ""))
            high_price = parse_number(row.get("Day High", ""))
            change_pct = parse_number(row.get("Change%", row.get("Change%", "")))
            volume = parse_volume(row.get("Volume", ""))

            # Build price data dict for upsert
            price_data = {
                "price_date": price_date,
                "open_price": None,  # Not available in CSV
                "high_price": high_price,
                "low_price": low_price,
                "close_price": close_price,
                "volume": volume,
                "change_pct": change_pct,
                "source": "csv_archive",
            }

            upsert_price(db, company_id, price_data)
            stats["rows_imported"] += 1
            batch_count += 1

            # Commit in batches of 1000 for performance
            if batch_count >= 1000:
                db.commit()
                batch_count = 0

        # Final commit
        if batch_count > 0:
            db.commit()

    return stats


def import_all_csvs(archive_dir: str = DEFAULT_ARCHIVE_DIR) -> dict:
    """Import all NSE CSV archive files from a directory.

    Returns overall stats.
    """
    archive_path = Path(archive_dir)
    if not archive_path.exists():
        logger.error(f"Archive directory not found: {archive_dir}")
        return {"error": f"Directory not found: {archive_dir}"}

    csv_files = sorted(archive_path.glob("NSE_data_all_stocks_*.csv"))
    if not csv_files:
        logger.error(f"No NSE_data_all_stocks_*.csv files found in {archive_dir}")
        return {"error": "No matching CSV files found"}

    logger.info(f"Found {len(csv_files)} CSV files to import")

    db = SessionLocal()
    try:
        company_lookup = build_company_lookup(db)
        logger.info(f"Company lookup built: {len(company_lookup)} tickers (including aliases)")

        overall = {
            "files_processed": 0,
            "total_rows": 0,
            "total_imported": 0,
            "total_skipped": 0,
            "all_unmatched_tickers": set(),
        }

        for i, csv_file in enumerate(csv_files, 1):
            logger.info(f"Importing {i}/{len(csv_files)}: {csv_file.name}")
            stats = import_csv_file(db, csv_file, company_lookup)

            overall["files_processed"] += 1
            overall["total_rows"] += stats["rows_total"]
            overall["total_imported"] += stats["rows_imported"]
            overall["total_skipped"] += (
                stats["rows_skipped_no_ticker"]
                + stats["rows_skipped_no_price"]
                + stats["rows_skipped_no_date"]
            )
            overall["all_unmatched_tickers"].update(stats["unmatched_tickers"])

            logger.info(
                f"  {csv_file.name}: {stats['rows_imported']}/{stats['rows_total']} imported, "
                f"unmatched: {stats['unmatched_tickers'] if stats['unmatched_tickers'] else 'none'}"
            )

        overall["all_unmatched_tickers"] = sorted(overall["all_unmatched_tickers"])
        logger.info(
            f"\nImport complete: {overall['files_processed']} files, "
            f"{overall['total_imported']} prices imported, "
            f"{overall['total_skipped']} skipped"
        )
        if overall["all_unmatched_tickers"]:
            logger.info(f"Unmatched tickers: {overall['all_unmatched_tickers']}")

        return overall

    finally:
        db.close()


if __name__ == "__main__":
    import_dir = DEFAULT_ARCHIVE_DIR
    if len(sys.argv) > 1:
        import_dir = sys.argv[1]
    result = import_all_csvs(import_dir)
    print(f"\n{'='*60}")
    print(f"IMPORT RESULTS")
    print(f"{'='*60}")
    print(f"Files processed: {result.get('files_processed', 0)}")
    print(f"Total rows read: {result.get('total_rows', 0)}")
    print(f"Prices imported: {result.get('total_imported', 0)}")
    print(f"Rows skipped:    {result.get('total_skipped', 0)}")
    if result.get("all_unmatched_tickers"):
        print(f"Unmatched tickers ({len(result['all_unmatched_tickers'])}): {', '.join(result['all_unmatched_tickers'])}")
