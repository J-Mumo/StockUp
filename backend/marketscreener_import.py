"""Import Marketscreener cached price data from JSON into the database.

Usage:
    python marketscreener_import.py
    python marketscreener_import.py KCB
"""

import json
import sys
from datetime import date
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import SessionLocal
from app.models.company import Company
from app.models.price_history import PriceHistory


CACHE_DIR = Path(__file__).parent / "data" / "marketscreener_prices"


def import_ticker(db, ticker: str) -> dict:
    cache_file = CACHE_DIR / f"{ticker}.json"
    if not cache_file.exists():
        return {"status": "no_file"}

    data = json.loads(cache_file.read_text(encoding="utf-8"))
    valid = [row for row in data if row.get("close", 0) > 0]
    if not valid:
        return {"status": "no_valid_data"}

    company = db.query(Company).filter(Company.ticker_symbol == ticker).first()
    if not company:
        return {"status": "company_not_found"}

    upserted = 0
    unchanged = 0
    for candle in valid:
        stmt = pg_insert(PriceHistory).values(
            company_id=company.id,
            price_date=date.fromisoformat(candle["date"]),
            open_price=candle["open"],
            high_price=candle["high"],
            low_price=candle["low"],
            close_price=candle["close"],
            volume=candle.get("volume"),
            source="marketscreener",
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
            upserted += 1
        else:
            unchanged += 1

    db.commit()
    return {
        "status": "ok",
        "total_valid": len(valid),
        "upserted": upserted,
        "unchanged": unchanged,
    }


def main() -> None:
    db = SessionLocal()

    if len(sys.argv) > 1 and sys.argv[1] != "--all":
        ticker = sys.argv[1].upper()
        print(f"{ticker}: {import_ticker(db, ticker)}")
        return

    files = sorted(CACHE_DIR.glob("*.json"))
    print(f"Importing {len(files)} Marketscreener cache files...")
    total_upserted = 0
    for cache_file in files:
        ticker = cache_file.stem
        result = import_ticker(db, ticker)
        total_upserted += result.get("upserted", 0)
        print(f"  {ticker}: {result}")
    print(f"Total upserted: {total_upserted}")


if __name__ == "__main__":
    main()