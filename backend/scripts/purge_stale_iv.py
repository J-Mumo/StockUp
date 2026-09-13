"""Purge stale / mis-modeled intrinsic_values rows.

Two classes of legacy noise in the intrinsic_values table:

1. **Bank rows priced by the industrial DCF.** Before the sector dispatcher
   landed, banks (KCB, EQTY, NCBA, etc.) were fed through ``industrial_dcf``,
   which produced absurd IVs (KCB IV = 5,322 vs true 120). Those rows have
   ``model_used IS NULL OR ''`` on tickers whose sector classifies as BANK.
   They are demonstrably wrong and must be deleted.

2. **Non-bank rows with ``model_used`` unset.** These were computed by the
   same ``industrial_dcf`` we still use today, so the numbers are fine — the
   column just didn't exist yet. Backfill ``model_used = 'industrial_dcf'``.

Same-day duplicates are handled by the alembic migration (unique constraint)
and the compute path (delete-then-insert). This script is idempotent and
safe to run multiple times.

Usage::

    python -m scripts.purge_stale_iv            # dry run
    python -m scripts.purge_stale_iv --commit   # apply
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import or_, and_

from app.database import SessionLocal
from app.models.company import Company
from app.models.intrinsic_value import IntrinsicValue
from app.services.valuation.sectors import SectorKind, classify_sector


def main(commit: bool) -> int:
    db = SessionLocal()
    try:
        # ---- 1. Purge stale bank rows ----
        companies = db.query(Company).all()
        bank_ids: list[int] = [
            c.id for c in companies if classify_sector(c.sector) == SectorKind.BANK
        ]

        stale_bank_q = db.query(IntrinsicValue).filter(
            IntrinsicValue.company_id.in_(bank_ids) if bank_ids else False,
            or_(
                IntrinsicValue.model_used.is_(None),
                IntrinsicValue.model_used == "",
            ),
        )
        stale_bank_count = stale_bank_q.count()
        print(
            f"Stale bank IV rows to delete: {stale_bank_count} "
            f"(across {len(bank_ids)} banks)"
        )
        if stale_bank_count and commit:
            stale_bank_q.delete(synchronize_session=False)

        # ---- 2. Backfill model_used on non-bank legacy rows ----
        non_bank_ids: list[int] = [
            c.id for c in companies if classify_sector(c.sector) != SectorKind.BANK
        ]
        backfill_q = db.query(IntrinsicValue).filter(
            IntrinsicValue.company_id.in_(non_bank_ids) if non_bank_ids else False,
            or_(
                IntrinsicValue.model_used.is_(None),
                IntrinsicValue.model_used == "",
            ),
        )
        backfill_count = backfill_q.count()
        print(
            f"Non-bank IV rows to backfill model_used='industrial_dcf': "
            f"{backfill_count}"
        )
        if backfill_count and commit:
            backfill_q.update(
                {IntrinsicValue.model_used: "industrial_dcf"},
                synchronize_session=False,
            )

        if commit:
            db.commit()
            print("Committed.")
        else:
            print("(dry-run; pass --commit to persist)")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()
    sys.exit(main(args.commit))
