"""Report bank-sector coverage: for every company classified as a bank,
show years of financial_statement rows and years with sector_metrics.
Used to prioritise which banks are ready for valuation.

    docker exec stockup-api-1 python -m scripts.bank_coverage
"""
from app.database import SessionLocal
from app.models.company import Company
from app.models.financial_statement import FinancialStatement
from app.services.valuation.sectors import SectorKind, classify_sector


def main() -> None:
    db = SessionLocal()
    try:
        banks = (
            db.query(Company)
            .order_by(Company.ticker_symbol)
            .all()
        )
        banks = [c for c in banks if classify_sector(c.sector) == SectorKind.BANK]
        print(f"{len(banks)} bank companies\n")
        print(f"{'Ticker':<8}{'Sector':<24}{'FS years':<30}{'Sector metrics years'}")
        print("-" * 100)
        for c in banks:
            rows = (
                db.query(FinancialStatement)
                .filter(FinancialStatement.company_id == c.id)
                .order_by(FinancialStatement.fiscal_year)
                .all()
            )
            years = [str(r.fiscal_year) for r in rows]
            sm_years = [
                str(r.fiscal_year) for r in rows
                if r.sector_metrics
            ]
            print(
                f"{c.ticker_symbol:<8}{(c.sector or '-')[:22]:<24}"
                f"{','.join(years) if years else '(none)':<30}"
                f"{','.join(sm_years) if sm_years else '(none)'}"
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
