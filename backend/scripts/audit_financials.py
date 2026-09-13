"""Audit ``financial_statements`` rows for internal consistency.

Runs :func:`app.data.quality.validate_row` across every row (grouped by
company) and prints a human-readable report. Optionally applies cheap
derivations (BVPS from equity/shares).

Usage::

    python -m scripts.audit_financials                 # audit everyone
    python -m scripts.audit_financials --sector bank   # audit banks only
    python -m scripts.audit_financials --tickers KCB,EQTY
    python -m scripts.audit_financials --derive        # also fill blanks (dry-run unless --commit)
    python -m scripts.audit_financials --derive --commit
    python -m scripts.audit_financials --errors-only
"""
from __future__ import annotations

import argparse
from collections import defaultdict

from sqlalchemy import select

from app.database import SessionLocal
from app.data.quality import audit_company, derive_missing_fields
from app.models import Company


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sector", help="Filter companies by sector substring (e.g. 'bank')")
    ap.add_argument("--tickers", help="Comma-separated tickers to audit")
    ap.add_argument("--derive", action="store_true", help="Fill BVPS from equity/shares")
    ap.add_argument("--commit", action="store_true", help="Persist --derive changes (default is dry-run)")
    ap.add_argument("--errors-only", action="store_true")
    args = ap.parse_args()

    ticker_filter: set[str] | None = None
    if args.tickers:
        ticker_filter = {t.strip().upper() for t in args.tickers.split(",") if t.strip()}

    db = SessionLocal()
    try:
        stmt = select(Company).order_by(Company.ticker_symbol)
        if args.sector:
            stmt = stmt.where(Company.sector.ilike(f"%{args.sector}%"))
        companies = list(db.scalars(stmt))
        if ticker_filter:
            companies = [c for c in companies if c.ticker_symbol.upper() in ticker_filter]

        totals: dict[str, int] = defaultdict(int)
        derived_total = 0

        for company in companies:
            rows_reports = audit_company(db, company)
            if not rows_reports:
                continue

            company_derived: list[str] = []
            if args.derive:
                for fs, _ in rows_reports:
                    applied = derive_missing_fields(fs, company)
                    if applied:
                        derived_total += 1
                        keys = ", ".join(f"{k}={v:.2f}" for k, v in applied.items())
                        company_derived.append(f"FY{fs.fiscal_year} {keys}")

            interesting = [
                (fs, r) for fs, r in rows_reports
                if r.errors or (r.warnings and not args.errors_only)
            ]
            if not interesting and not company_derived:
                continue

            print(f"\n=== {company.ticker_symbol:6s} ({company.sector}) ===")
            for line in company_derived:
                print(f"  [derived] {line}")

            for fs, report in interesting:
                for issue in report.issues:
                    if args.errors_only and issue.severity != "error":
                        continue
                    totals[issue.severity] += 1
                    print(
                        f"  FY{fs.fiscal_year} [{issue.severity:5s}] "
                        f"{issue.field_name}: {issue.message}"
                    )

        if args.derive:
            if args.commit:
                db.commit()
                print(f"\ncommitted {derived_total} derived value(s).")
            else:
                db.rollback()
                print(f"\n[dry-run] would derive {derived_total} value(s). Use --commit to persist.")

        print(
            f"\nsummary: errors={totals.get('error', 0)}, "
            f"warnings={totals.get('warn', 0)}, "
            f"derived={derived_total}"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
