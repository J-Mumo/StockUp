"""Purge specific ``FinancialStatement`` rows identified as polluted interims
or period-mismatch records.

Usage::

    python -m scripts.purge_financial_rows                                  # dry-run defaults
    python -m scripts.purge_financial_rows --commit                         # persist defaults
    python -m scripts.purge_financial_rows --rows KCB:2025,EQTY:2025        # custom set (dry-run)
    python -m scripts.purge_financial_rows --rows KCB:2025 --commit         # persist custom

Default target set (derived from audit_financials errors on 2026-09-13):

    KCB  FY2025  - EPS=4.93 vs NI/shares=15.22  (interim EPS in full-year row)
    EQTY FY2025  - equity -47.5% YoY             (interim balance sheet)
    NCBA FY2026  - fiscal_year 2026 exists in Sept 2026 with near-full-year NI
                   (H1 filing labelled as annual)

The script prints each row it would delete along with any linked references
(intrinsic_values FKs) so the operator can see the blast radius before
committing.
"""
from __future__ import annotations

import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Company, FinancialStatement


DEFAULT_TARGETS: tuple[tuple[str, int, str], ...] = (
    ("KCB",  2025, "EPS=4.93 vs NI/shares=15.22 (interim EPS in FY row)"),
    ("EQTY", 2025, "equity -47.5% YoY (interim balance sheet)"),
    ("NCBA", 2026, "H1-2026 filing labelled as annual"),
)


def _parse_rows(spec: str) -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = []
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            ticker, year = token.split(":")
            out.append((ticker.strip().upper(), int(year), "user-supplied"))
        except ValueError as exc:
            raise SystemExit(f"bad --rows token {token!r}, expected TICKER:YEAR") from exc
    return out


def _resolve(
    db: Session, ticker: str, year: int
) -> tuple[Company | None, FinancialStatement | None]:
    company = db.scalar(select(Company).where(Company.ticker_symbol == ticker))
    if company is None:
        return None, None
    fs = db.scalar(
        select(FinancialStatement).where(
            FinancialStatement.company_id == company.id,
            FinancialStatement.fiscal_year == year,
        )
    )
    return company, fs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rows", help="TICKER:YEAR pairs, comma-separated (default: known polluted set)")
    ap.add_argument("--commit", action="store_true", help="Persist deletions (default: dry-run)")
    args = ap.parse_args()

    targets = _parse_rows(args.rows) if args.rows else list(DEFAULT_TARGETS)

    db = SessionLocal()
    deleted = 0
    missing = 0
    try:
        for ticker, year, reason in targets:
            company, fs = _resolve(db, ticker, year)
            if company is None:
                print(f"[skip] {ticker} FY{year}: no company row")
                missing += 1
                continue
            if fs is None:
                print(f"[skip] {ticker} FY{year}: no financial_statement row")
                missing += 1
                continue

            ni = float(fs.net_income) if fs.net_income else None
            eq = float(fs.shareholders_equity or fs.total_equity or 0) or None
            metrics_keys = list((fs.sector_metrics or {}).keys())
            print(
                f"[del]  {ticker} FY{year}: reason={reason}\n"
                f"         NI={ni} equity={eq} period_type={fs.period_type} "
                f"sector_metrics_keys={metrics_keys}"
            )
            db.delete(fs)
            deleted += 1

        if args.commit:
            db.commit()
            print(f"\ncommitted {deleted} deletion(s); {missing} not found.")
        else:
            db.rollback()
            print(f"\n[dry-run] rolled back. would delete {deleted} row(s); {missing} not found.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
