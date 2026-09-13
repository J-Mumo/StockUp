"""One-off insert of KCB FY2025 audited financials.

Reads the KCB Group PLC "Audited Financial Statements and Other Disclosures for
the period ended 31 December 2025" (the newspaper-style release published on
https://kcbgroup.com/financial-statements?years=2025) and writes the
consolidated figures into `financial_statements`.

Also corrects the FY2024 revenue row which was wrongly ingested (307.745B was
the off-balance-sheet "Letters of credit, guarantees, acceptances" line, not
the group's operating income of 204.867B).

Values below are in Kshs. Source PDF is cached at:
  data/annual_reports/KCB/2025.pdf

Run:
  python -m scripts.insert_kcb_2025_audited            # dry-run
  python -m scripts.insert_kcb_2025_audited --commit   # apply
"""
from __future__ import annotations

import argparse
from decimal import Decimal

from app.database import SessionLocal
from app.models.company import Company
from app.models.financial_statement import FinancialStatement


# All monetary figures below come straight from the audited release (Kshs '000
# columns), multiplied by 1000 to store as full shillings.
KCB_2025_CONSOLIDATED = {
    "fiscal_year": 2025,
    "period_type": "annual",
    # Income statement (Kshs '000 → Kshs)
    "revenue":               213_777_894 * 1000,   # Total operating income
    "net_income":             66_819_429 * 1000,   # Attributable to shareholders (matches EPS)
    "earnings_per_share":     Decimal("20.80"),
    "dividends_per_share":    Decimal("7.00"),
    # Balance sheet
    "total_assets":        2_147_206_575 * 1000,
    "total_liabilities":   1_806_650_963 * 1000,
    "shareholders_equity":   331_466_780 * 1000,   # Total shareholders' funds
    "total_equity":          340_555_612 * 1000,   # Shareholders' funds + minority interest
    # Ratios: ROE = attributable NI / avg equity; D/E = total liab / shareholders' funds.
    #   ROE = 66,819,429 / ((274,889,584 + 331,466,780) / 2) = 22.04%
    #   D/E = 1,806,650,963 / 331,466,780 = 5.4506
    "return_on_equity":      Decimal("0.2204"),
    "debt_to_equity":        Decimal("5.4506"),
    "notes": (
        "[PDF extracted FY2025 - KCB Group Plc FY 2025 Audited Financial "
        "Statements, 31-Dec-2025, consolidated column. Approved by Board "
        "11-Mar-2026, auditor PwC LLP unqualified. Manual insertion; OpenAI "
        "credits exhausted at ingest."
    ),
}

# FY2024 correction (existing row has 307.745B revenue which is off-balance
# sheet contingent liabilities). Correct value is total operating income.
KCB_2024_CORRECTIONS = {
    "revenue":     204_866_691 * 1000,
    "net_income":   60_089_353 * 1000,   # Attributable to shareholders (was 61.775B = incl. MI)
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="Persist changes")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        kcb = db.query(Company).filter(Company.ticker_symbol == "KCB").first()
        if not kcb:
            print("KCB not found in companies table")
            return 1

        # 1) Insert / update FY2025
        existing_2025 = (
            db.query(FinancialStatement)
            .filter(
                FinancialStatement.company_id == kcb.id,
                FinancialStatement.fiscal_year == 2025,
            )
            .first()
        )
        if existing_2025:
            print(f"FY2025 row already exists (id={existing_2025.id}); will UPDATE")
            for k, v in KCB_2025_CONSOLIDATED.items():
                if k in ("fiscal_year", "period_type"):
                    continue
                setattr(existing_2025, k, v)
        else:
            print("FY2025 row missing; will INSERT")
            fs = FinancialStatement(company_id=kcb.id, **KCB_2025_CONSOLIDATED)
            db.add(fs)

        # 2) Correct FY2024 row
        existing_2024 = (
            db.query(FinancialStatement)
            .filter(
                FinancialStatement.company_id == kcb.id,
                FinancialStatement.fiscal_year == 2024,
            )
            .first()
        )
        if existing_2024:
            print(f"FY2024 row (id={existing_2024.id}) — correcting revenue/net_income:")
            print(f"  revenue: {existing_2024.revenue} -> {KCB_2024_CORRECTIONS['revenue']:,}")
            print(f"  net_income: {existing_2024.net_income} -> {KCB_2024_CORRECTIONS['net_income']:,}")
            for k, v in KCB_2024_CORRECTIONS.items():
                setattr(existing_2024, k, v)
            existing_2024.notes = (
                (existing_2024.notes or "").rstrip()
                + " [FY2024 revenue+net_income corrected from FY2025 audited "
                "comparative; prior 307.745B was off-balance-sheet LC/guarantees.]"
            ).lstrip()
        else:
            print("FY2024 row not found — skipping correction")

        if args.commit:
            db.commit()
            print("Committed.")
        else:
            db.rollback()
            print("(dry-run; pass --commit to persist)")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
