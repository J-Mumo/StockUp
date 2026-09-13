"""Idempotent KCB data patch — fixes two known ingest bugs.

1. FY2020 revenue & net_income were ingested as raw KES instead of
   thousands (off by 3 orders of magnitude). Fix: multiply by 1000.
     - revenue     88,745,452     -> 88,745,452,000       (88.7B, matches KCB Group FY2020 operating income)
     - net_income  19,603,642     -> 19,603,642,000       (19.6B, matches KCB Group FY2020 PAT and reconciles with EPS 6.10 / shares 3.213B)

2. FY2024 net_income was ingested as 52.2B but KCB Group Q4 2024
   announcement reports 61.8B (also reconciles with EPS 18.70 on
   weighted-avg shares 3.305B). Fix: overwrite with 61.8B.

Idempotent: checks the current value against the "before" fingerprint and
only writes if it matches; skips otherwise. Safe to re-run.

    docker exec stockup-api-1 python -m scripts.patch_kcb_data --commit
"""
from __future__ import annotations

import argparse
from decimal import Decimal

from app.database import SessionLocal
from app.models.company import Company
from app.models.financial_statement import FinancialStatement


def _get_row(db, ticker: str, fiscal_year: int) -> FinancialStatement | None:
    company = db.query(Company).filter(Company.ticker_symbol == ticker).first()
    if company is None:
        return None
    return (
        db.query(FinancialStatement)
        .filter(
            FinancialStatement.company_id == company.id,
            FinancialStatement.fiscal_year == fiscal_year,
        )
        .first()
    )


def _fix_fy2020(db) -> str:
    row = _get_row(db, "KCB", 2020)
    if row is None:
        return "FY2020: not found"

    expected_revenue = Decimal("88745452.00")
    expected_ni = Decimal("19603642.00")
    if row.revenue != expected_revenue or row.net_income != expected_ni:
        return (
            f"FY2020: skip — current revenue={row.revenue}, ni={row.net_income} "
            f"don't match expected before-state; already patched or drift"
        )

    row.revenue = expected_revenue * 1000
    row.net_income = expected_ni * 1000
    return f"FY2020: revenue {expected_revenue} -> {row.revenue}, ni {expected_ni} -> {row.net_income}"


def _fix_fy2024(db) -> str:
    row = _get_row(db, "KCB", 2024)
    if row is None:
        return "FY2024: not found"

    expected_ni = Decimal("52238219000.00")
    new_ni = Decimal("61800000000.00")
    if row.net_income != expected_ni:
        return (
            f"FY2024: skip — current ni={row.net_income} "
            f"doesn't match expected before-state; already patched or drift"
        )

    row.net_income = new_ni
    return f"FY2024: net_income {expected_ni} -> {new_ni}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Persist changes (default: dry-run)",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        print(_fix_fy2020(db))
        print(_fix_fy2024(db))
        if args.commit:
            db.commit()
            print("Committed.")
        else:
            db.rollback()
            print("(dry-run; use --commit to persist)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
