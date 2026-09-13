"""One-off IMH shares-outstanding probe.

The audit sweep found IMH EPS consistently ~4x higher than NI/shares across
FY2014-2020, which points at a stale shares_outstanding value that predates
one of I&M Group's corporate actions (2019 share subdivision).
"""
from __future__ import annotations

from app.database import SessionLocal
from app.models.company import Company
from app.models.financial_statement import FinancialStatement


def main() -> None:
    db = SessionLocal()
    try:
        imh = db.query(Company).filter(Company.ticker_symbol == "IMH").first()
        if imh is None:
            print("IMH not found")
            return
        print(f"IMH shares_outstanding = {imh.shares_outstanding:,}")

        rows = (
            db.query(FinancialStatement)
            .filter(FinancialStatement.company_id == imh.id)
            .order_by(FinancialStatement.fiscal_year.asc())
            .all()
        )
        print(f"\n{'FY':<6}{'net_income':>20}{'eps':>10}{'implied_shares':>20}{'ratio_to_stored':>18}")
        for r in rows:
            ni = float(r.net_income) if r.net_income else None
            eps = float(r.earnings_per_share) if r.earnings_per_share else None
            if ni and eps:
                implied = ni / eps
                ratio = implied / float(imh.shares_outstanding) if imh.shares_outstanding else None
                print(
                    f"{r.fiscal_year:<6}{ni:>20,.0f}{eps:>10.2f}"
                    f"{implied:>20,.0f}{ratio if ratio else 0:>18.3f}"
                )
    finally:
        db.close()


if __name__ == "__main__":
    main()
