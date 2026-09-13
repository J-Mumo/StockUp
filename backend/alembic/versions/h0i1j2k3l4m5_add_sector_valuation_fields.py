"""add sector_metrics, model_used, scenario_values

Revision ID: h0i1j2k3l4m5
Revises: g9h0i1j2k3l4
Create Date: 2026-09-13 12:00:00.000000

Adds:
- financial_statements.sector_metrics (JSON) — bank/insurer/REIT-specific inputs
- intrinsic_values.model_used (VARCHAR) — which valuation strategy produced the row
- intrinsic_values.scenario_values (JSON) — conservative/base/strong per-share values
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h0i1j2k3l4m5"
down_revision: Union[str, None] = "g9h0i1j2k3l4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "financial_statements",
        sa.Column("sector_metrics", sa.JSON(), nullable=True),
    )
    op.add_column(
        "intrinsic_values",
        sa.Column("model_used", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "intrinsic_values",
        sa.Column("scenario_values", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("intrinsic_values", "scenario_values")
    op.drop_column("intrinsic_values", "model_used")
    op.drop_column("financial_statements", "sector_metrics")
