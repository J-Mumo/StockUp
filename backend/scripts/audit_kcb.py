"""Ad-hoc KCB data-quality audit — prints issues surfaced by
``app.data.quality.audit_company`` for verifying the new YoY-flat and
scale-jump anomaly checks on real prod data.

Run inside the api container:
    docker exec stockup-api-1 python -m scripts.audit_kcb
"""
from app.database import SessionLocal
from app.models.company import Company
from app.data.quality import audit_company


def main() -> None:
    db = SessionLocal()
    try:
        kcb = db.query(Company).filter(Company.ticker_symbol == "KCB").first()
        if kcb is None:
            print("KCB not found")
            return
        any_issues = False
        for row, report in audit_company(db, kcb):
            if not report.issues:
                continue
            any_issues = True
            print(f"FY{row.fiscal_year}:")
            for issue in report.issues:
                print(f"  [{issue.severity}] {issue.field_name}: {issue.message}")
        if not any_issues:
            print("no DQ issues surfaced for KCB")
    finally:
        db.close()


if __name__ == "__main__":
    main()
