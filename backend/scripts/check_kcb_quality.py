"""Quick smoke check of the normalized earnings-growth factor + subscores
for KCB, run against prod data.

    docker exec stockup-api-1 python -m scripts.check_kcb_quality
"""
from app.database import SessionLocal
from app.models.company import Company
from app.models.financial_statement import FinancialStatement
from app.services.recommendation_engine import assess_quality


def main() -> None:
    db = SessionLocal()
    try:
        kcb = db.query(Company).filter(Company.ticker_symbol == "KCB").first()
        if kcb is None:
            print("KCB not found")
            return
        rows = (
            db.query(FinancialStatement)
            .filter(FinancialStatement.company_id == kcb.id)
            .order_by(FinancialStatement.fiscal_year)
            .all()
        )
        print(f"KCB has {len(rows)} annual rows: "
              f"FY{rows[0].fiscal_year}-FY{rows[-1].fiscal_year}" if rows else "no rows")
        for r in rows:
            ni = float(r.net_income) if r.net_income is not None else None
            print(f"  FY{r.fiscal_year}: NI={ni!r}")
        q = assess_quality(rows, sector=kcb.sector)
        print(f"\nsector_kind: {q.sector_kind}")
        print(f"total score: {q.score}/{q.max_score}")
        print("\nFactors:")
        for f in q.factors:
            marker = "PASS" if f.passed else ("N/A " if f.insufficient_data else "FAIL")
            print(f"  [{marker}] {f.name}: {f.detail}")
        print("\nSubscores:")
        for s in q.subscores():
            print(f"  {s['name']}: {s['score']}/{s['max_score']} "
                  f"applicable={s['applicable']} passed={s['passed']} "
                  f"({s['detail']})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
