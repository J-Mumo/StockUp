"""Dump KCB FY2020-2024 financial_statement rows for review.

    docker exec stockup-api-1 python -m scripts.dump_kcb_fs
"""
from app.database import SessionLocal
from app.models.company import Company
from app.models.financial_statement import FinancialStatement


FIELDS = (
    "revenue net_income earnings_per_share free_cash_flow "
    "operating_cash_flow capital_expenditures "
    "total_assets total_liabilities total_equity shareholders_equity "
    "book_value_per_share debt_to_equity return_on_equity "
    "dividends_per_share current_ratio"
).split()


def main() -> None:
    db = SessionLocal()
    try:
        kcb = db.query(Company).filter(Company.ticker_symbol == "KCB").first()
        if kcb is None:
            print("KCB not found")
            return
        print(f"KCB shares_outstanding = {kcb.shares_outstanding}")
        rows = (
            db.query(FinancialStatement)
            .filter(FinancialStatement.company_id == kcb.id)
            .order_by(FinancialStatement.fiscal_year)
            .all()
        )
        for r in rows:
            print(f"\n--- FY{r.fiscal_year} (id={r.id}, period={r.period_type}) ---")
            for field in FIELDS:
                v = getattr(r, field, None)
                print(f"  {field} = {v!r}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
