"""Analyze price data coverage per company."""
from sqlalchemy import text
from app.database import SessionLocal

db = SessionLocal()

r = db.execute(text("""
    SELECT c.ticker_symbol, 
           COUNT(*) as rows,
           MIN(p.price_date) as first_date,
           MAX(p.price_date) as last_date,
           STRING_AGG(DISTINCT p.source, ', ') as sources
    FROM price_history p
    JOIN companies c ON c.id = p.company_id
    GROUP BY c.ticker_symbol
    ORDER BY c.ticker_symbol
""")).fetchall()

print(f"{'Ticker':<10} {'Rows':>5} {'First':>12} {'Last':>12} {'Sources'}")
print("-" * 70)
for x in r:
    print(f"{x[0]:<10} {x[1]:>5} {str(x[2]):>12} {str(x[3]):>12} {x[4]}")

if r:
    print("\nCoverage years by company:")
    for x in r:
        if x[2] and x[3]:
            years = x[3].year - x[2].year + 1
            print(f"  {x[0]:<10} ~{years:>2} years ({x[2]} -> {x[3]})")

# Companies with NO price data
r2 = db.execute(text("""
    SELECT c.ticker_symbol FROM companies c
    WHERE c.is_active = true
    AND c.id NOT IN (SELECT DISTINCT company_id FROM price_history)
""")).fetchall()
if r2:
    print(f"\nCompanies with NO price data: {[x[0] for x in r2]}")

r4 = db.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM companies WHERE is_active = true) AS active_companies,
            (SELECT COUNT(DISTINCT p.company_id)
             FROM price_history p
             JOIN companies c2 ON c2.id = p.company_id
             WHERE c2.is_active = true) AS companies_with_prices
""")).fetchone()

if r4 and r4[0]:
        pct = (r4[1] / r4[0]) * 100
        print(f"\nCompany coverage: {r4[1]}/{r4[0]} ({pct:.1f}%) have at least one price row")

# Year coverage summary
r3 = db.execute(text("""
    SELECT EXTRACT(YEAR FROM price_date)::int as yr, COUNT(*) 
    FROM price_history GROUP BY yr ORDER BY yr
""")).fetchall()
print(f"\nYear coverage:")
for yr, cnt in r3:
    print(f"  {yr}: {cnt} rows")

# Approximate gap analysis by company (missing weekdays only)
r5 = db.execute(text("""
        WITH ordered AS (
            SELECT
                c.ticker_symbol,
                p.price_date,
                LEAD(p.price_date) OVER (PARTITION BY c.ticker_symbol ORDER BY p.price_date) AS next_date
            FROM price_history p
            JOIN companies c ON c.id = p.company_id
        )
        SELECT
            ticker_symbol,
            COALESCE(SUM(GREATEST(0, (next_date - price_date) - 1)), 0) AS missing_days
        FROM ordered
        GROUP BY ticker_symbol
        ORDER BY missing_days DESC, ticker_symbol
        LIMIT 15
""")).fetchall()

if r5:
        print("\nTop 15 potential gap counts (calendar-day basis):")
        for ticker, gaps in r5:
                print(f"  {ticker:<10} {int(gaps):>6} missing days")
