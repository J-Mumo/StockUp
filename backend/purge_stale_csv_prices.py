"""Purge stale csv_archive price data — removes runs of identical close prices
spanning more than 60 consecutive trading days.

Usage:
    python purge_stale_csv_prices.py          # Dry run (report only)
    python purge_stale_csv_prices.py --apply   # Actually delete
"""
import sys
from collections import defaultdict
from sqlalchemy import text
from app.database import SessionLocal

DRY_RUN = "--apply" not in sys.argv
MAX_CONSECUTIVE = 60

db = SessionLocal()

# Use SQL to do the heavy lifting — find runs via window functions
# This query finds consecutive runs of identical close prices per company
print("Analyzing stale price runs...")

result = db.execute(text("""
WITH ordered AS (
    SELECT p.id, p.company_id, c.ticker_symbol, p.price_date, p.close_price,
           LAG(p.close_price) OVER (PARTITION BY p.company_id ORDER BY p.price_date) as prev_close,
           ROW_NUMBER() OVER (PARTITION BY p.company_id ORDER BY p.price_date) as rn
    FROM price_history p
    JOIN companies c ON c.id = p.company_id
    WHERE p.source = 'csv_archive'
),
run_groups AS (
    SELECT *,
           SUM(CASE WHEN close_price = prev_close THEN 0 ELSE 1 END) 
               OVER (PARTITION BY company_id ORDER BY rn) as run_group
    FROM ordered
),
run_sizes AS (
    SELECT *, COUNT(*) OVER (PARTITION BY company_id, run_group) as run_length
    FROM run_groups
)
SELECT id, ticker_symbol, price_date, close_price, run_length
FROM run_sizes
WHERE run_length > :max_consecutive
ORDER BY ticker_symbol, price_date
"""), {"max_consecutive": MAX_CONSECUTIVE}).fetchall()

print(f"Stale rows to delete: {len(result)}")

# Group by ticker for reporting
ticker_stats = defaultdict(lambda: {"count": 0, "price": None, "min_date": None, "max_date": None})
stale_ids = []
for row in result:
    pid, ticker, pdate, close, run_len = row
    stale_ids.append(pid)
    s = ticker_stats[ticker]
    s["count"] += 1
    s["price"] = float(close)
    if s["min_date"] is None or pdate < s["min_date"]:
        s["min_date"] = pdate
    if s["max_date"] is None or pdate > s["max_date"]:
        s["max_date"] = pdate

print(f"Affected tickers: {len(ticker_stats)}")
print(f"\n{'Ticker':<10} {'Stale':>6} {'Close':>10} {'From':>12} {'To':>12}")
print("-" * 55)
for ticker in sorted(ticker_stats, key=lambda t: -ticker_stats[t]["count"]):
    s = ticker_stats[ticker]
    print(f"{ticker:<10} {s['count']:>6} {s['price']:>10.4f} {str(s['min_date']):>12} {str(s['max_date']):>12}")

if DRY_RUN:
    print("\n*** DRY RUN — no changes made. Pass --apply to delete. ***")
else:
    batch_size = 1000
    total_deleted = 0
    for i in range(0, len(stale_ids), batch_size):
        batch = stale_ids[i:i+batch_size]
        db.execute(text("DELETE FROM price_history WHERE id = ANY(:ids)"), {"ids": batch})
        total_deleted += len(batch)
        if total_deleted % 5000 == 0:
            print(f"  Deleted {total_deleted}/{len(stale_ids)}...")
    db.commit()
    print(f"\n✅ Deleted {total_deleted} stale csv_archive price rows.")
