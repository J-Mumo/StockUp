"""Idempotent KCB data patches — corrects known ingest bugs against
authoritative KCB Group 2024 audited financial statements.

Source: KCB Group PLC 2024 Integrated Report & audited consolidated
statement of financial position; CMA abridged FY2024 filings.

FY2020 (unit-error fix):
  revenue     88,745,452       -> 88,745,452,000       (x1000; raw KES vs thousands)
  net_income  19,603,642       -> 19,603,642,000       (x1000; reconciles with EPS 6.10)

FY2024 (authoritative-restate):
  net_income        52,238,219,000    -> 61,775,000,000
      (52.239B was ingested from Total Comprehensive Income line by
       mistake; the audited Profit for the Year is 61.775B. EPS 18.70 x
       weighted-avg shares 3.305B ~= 61.8B.)
  total_assets      2,170,873,992,000 -> 1,962,320,000,000
      (assets actually declined 9.6% YoY. Original value was a duplicate
       of FY2023 -- confirmed by KCB audited BS and Cytonn.)
  total_liabilities 1,959,903,519,000 -> 1,679,341,000,000
      (from audited BS; reconciles as 1,679.341 + 282.979 = 1,962.320.)
  total_equity      211,970,473,000   -> 282,979,000,000
      (total equity including minority interest; matches the already-
       correct shareholders_equity value and reconciles Assets = L + E.)

Idempotent: each field-level fix is guarded by a before-state check. It
accepts either the original ingested value OR any previously-committed
patched value that is still known-wrong, so re-running is safe.

    docker exec stockup-api-1 python -m scripts.patch_kcb_data --commit
"""
from __future__ import annotations

import argparse
from decimal import Decimal
from typing import Iterable

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


def _fix_field(
    row: FinancialStatement,
    field: str,
    accepted_before: Iterable[Decimal],
    target: Decimal,
) -> str:
    current = getattr(row, field)
    if current == target:
        return f"    {field}: already at target {target}"
    if not any(current == b for b in accepted_before):
        return (
            f"    {field}: skip — current {current} not in accepted "
            f"before-states {list(accepted_before)}"
        )
    setattr(row, field, target)
    return f"    {field}: {current} -> {target}"


def _fix_fy2020(db) -> list[str]:
    row = _get_row(db, "KCB", 2020)
    if row is None:
        return ["FY2020: not found"]

    lines = ["FY2020 (unit-error x1000):"]
    lines.append(
        _fix_field(
            row,
            "revenue",
            accepted_before=[Decimal("88745452.00")],
            target=Decimal("88745452000.00"),
        )
    )
    lines.append(
        _fix_field(
            row,
            "net_income",
            accepted_before=[Decimal("19603642.00")],
            target=Decimal("19603642000.00"),
        )
    )
    return lines


def _fix_fy2024(db) -> list[str]:
    row = _get_row(db, "KCB", 2024)
    if row is None:
        return ["FY2024: not found"]

    lines = ["FY2024 (authoritative restate from KCB FY2024 audited FS):"]
    # Net income: original 52.238B (misread as TCI) or prior-patched 61.8B.
    lines.append(
        _fix_field(
            row,
            "net_income",
            accepted_before=[
                Decimal("52238219000.00"),
                Decimal("61800000000.00"),
            ],
            target=Decimal("61775000000.00"),
        )
    )
    # Total assets: was duplicated from FY2023 value.
    lines.append(
        _fix_field(
            row,
            "total_assets",
            accepted_before=[Decimal("2170873992000.00")],
            target=Decimal("1962320000000.00"),
        )
    )
    # Total liabilities: reconciles Assets = Liab + Equity.
    lines.append(
        _fix_field(
            row,
            "total_liabilities",
            accepted_before=[Decimal("1959903519000.00")],
            target=Decimal("1679341000000.00"),
        )
    )
    # Total equity: wrong 212B replaced with authoritative 283B (matches
    # shareholders_equity, reconciles the balance sheet).
    lines.append(
        _fix_field(
            row,
            "total_equity",
            accepted_before=[Decimal("211970473000.00")],
            target=Decimal("282979000000.00"),
        )
    )
    return lines


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
        for line in _fix_fy2020(db):
            print(line)
        for line in _fix_fy2024(db):
            print(line)
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
