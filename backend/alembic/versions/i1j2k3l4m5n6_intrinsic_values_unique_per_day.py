"""dedupe intrinsic_values and add unique constraint on (company_id, valuation_date)

Revision ID: i1j2k3l4m5n6
Revises: h0i1j2k3l4m5
Create Date: 2026-09-13 18:00:00.000000

Before this migration ``compute_valuation`` inserted a fresh row every time it
ran, so we accumulated 3-5 duplicate rows per (company_id, valuation_date) and
had no way to enforce single-source-of-truth per day.

This migration:
1. De-duplicates existing ``intrinsic_values`` rows, keeping the newest ``id``
   per (company_id, valuation_date).
2. Adds a UNIQUE constraint on (company_id, valuation_date) so subsequent
   inserts must go through the new same-day upsert path.

Data-side cleanup (deleting stale bank rows priced by the industrial DCF
before ``bank_residual_income`` existed, backfilling ``model_used`` on
non-bank legacy rows) is handled by ``scripts/purge_stale_iv.py`` — that's a
separate, repeatable data operation, not a schema change.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "i1j2k3l4m5n6"
down_revision: Union[str, None] = "h0i1j2k3l4m5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Delete duplicate rows, keeping the newest id per (company_id, valuation_date).
    op.execute(
        """
        DELETE FROM intrinsic_values
         WHERE id IN (
             SELECT id FROM (
                 SELECT id,
                        ROW_NUMBER() OVER (
                            PARTITION BY company_id, valuation_date
                            ORDER BY id DESC
                        ) AS rn
                   FROM intrinsic_values
             ) t
            WHERE rn > 1
         )
        """
    )
    op.create_unique_constraint(
        "uq_intrinsic_company_date",
        "intrinsic_values",
        ["company_id", "valuation_date"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_intrinsic_company_date",
        "intrinsic_values",
        type_="unique",
    )
