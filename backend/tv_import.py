"""Import TradingView price data from JSON cache into the database.

Usage:
    python tv_import.py           # Import all cached JSON files
    python tv_import.py KCB       # Import single ticker
"""
import json
import sys
from datetime import date
from pathlib import Path
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.database import SessionLocal
from app.models.company import Company
from app.models.price_history import PriceHistory

CACHE_DIR = Path(__file__).parent / "data" / "tv_prices"


def import_ticker(db, ticker: str) -> dict:
    """Import TradingView cached data for a single ticker."""
    cache_file = CACHE_DIR / f"{ticker}.json"
    if not cache_file.exists():
        return {"status": "no_file"}
    
    data = json.load(open(cache_file))
    # Filter zero-price entries
    valid = [d for d in data if d["close"] > 0]
    if not valid:
        return {"status": "no_valid_data"}
    
    company = db.query(Company).filter(Company.ticker_symbol == ticker).first()
    if not company:
        return {"status": "company_not_found"}
    
    inserted = 0
    updated_or_existing = 0
    for candle in valid:
        price_date = date.fromisoformat(candle["date"])

        stmt = pg_insert(PriceHistory).values(
            company_id=company.id,
            price_date=price_date,
            open_price=candle["open"],
            high_price=candle["high"],
            low_price=candle["low"],
            close_price=candle["close"],
            volume=candle["volume"],
            source="tradingview",
        )

        stmt = stmt.on_conflict_do_update(
            constraint="uq_company_price_date",
            set_={
                "open_price": stmt.excluded.open_price,
                "high_price": stmt.excluded.high_price,
                "low_price": stmt.excluded.low_price,
                "close_price": stmt.excluded.close_price,
                "volume": stmt.excluded.volume,
                "source": stmt.excluded.source,
            },
        )

        result = db.execute(stmt)
        if result.rowcount > 0:
            inserted += 1
        else:
            updated_or_existing += 1
    
    db.commit()
    return {
        "status": "ok",
        "total_valid": len(valid),
        "upserted": inserted,
        "unchanged": updated_or_existing,
    }


def main():
    db = SessionLocal()
    
    if len(sys.argv) > 1 and sys.argv[1] != "--all":
        ticker = sys.argv[1].upper()
        result = import_ticker(db, ticker)
        print(f"{ticker}: {result}")
    else:
        # Import all cached files
        files = list(CACHE_DIR.glob("*.json"))
        print(f"Importing {len(files)} cached ticker files...")
        total_upserted = 0
        for f in sorted(files):
            ticker = f.stem
            result = import_ticker(db, ticker)
            total_upserted += result.get("upserted", 0)
            print(f"  {ticker}: {result}")
        print(f"\nTotal upserted: {total_upserted}")


if __name__ == "__main__":
    main()
