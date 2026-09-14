"""add company_ai_analyses table

Revision ID: j2k3l4m5n6o7
Revises: i1j2k3l4m5n6
Create Date: 2026-09-14 12:00:00.000000

Adds the ``company_ai_analyses`` table which stores LLM-generated per-company
research narratives. See ``app/models/company_ai_analysis.py`` for the full
column semantics.

Rows are shared across all users (unlike ``analysis_snapshots``, which is
user-scoped saved-report storage). One-row-per-generation; latest per
company is what the UI surfaces.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "j2k3l4m5n6o7"
down_revision: Union[str, None] = "i1j2k3l4m5n6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "company_ai_analyses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.Column("model_name", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=16), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("sector_kind", sa.String(length=32), nullable=True),
        sa.Column("narrative_md", sa.Text(), nullable=False),
        sa.Column("structured_json", sa.JSON(), nullable=True),
        sa.Column("triggered_by", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_ai_analysis_company_generated",
        "company_ai_analyses",
        ["company_id", "generated_at"],
    )
    op.create_index(
        "ix_ai_analysis_fingerprint",
        "company_ai_analyses",
        ["company_id", "input_fingerprint"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_analysis_fingerprint", table_name="company_ai_analyses")
    op.drop_index("ix_ai_analysis_company_generated", table_name="company_ai_analyses")
    op.drop_table("company_ai_analyses")
