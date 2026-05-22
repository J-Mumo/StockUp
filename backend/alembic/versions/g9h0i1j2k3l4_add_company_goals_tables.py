"""add company_goals and company_goal_progress tables

Revision ID: g9h0i1j2k3l4
Revises: f8a9b0c1d2e3
Create Date: 2026-05-22 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g9h0i1j2k3l4"
down_revision: Union[str, None] = "f8a9b0c1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "company_goals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("fiscal_year_set", sa.Integer(), nullable=False),
        sa.Column("goal_text", sa.String(length=500), nullable=False),
        sa.Column("goal_category", sa.String(length=30), nullable=False),
        sa.Column("metric_name", sa.String(length=80), nullable=True),
        sa.Column("target_value", sa.Numeric(20, 4), nullable=True),
        sa.Column("target_unit", sa.String(length=20), nullable=True),
        sa.Column("target_horizon_year", sa.Integer(), nullable=True),
        sa.Column("source_section", sa.String(length=40), nullable=True),
        sa.Column("source_quote", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_company_goals_company_year",
        "company_goals",
        ["company_id", "fiscal_year_set"],
    )

    op.create_table(
        "company_goal_progress",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("goal_id", sa.Integer(), sa.ForeignKey("company_goals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assessed_in_fiscal_year", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("actual_value", sa.Numeric(20, 4), nullable=True),
        sa.Column("narrative", sa.Text(), nullable=True),
        sa.Column("evidence_quote", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(length=10), nullable=False, server_default="medium"),
        sa.Column("assessment_method", sa.String(length=20), nullable=False, server_default="llm"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_goal_progress_goal_year",
        "company_goal_progress",
        ["goal_id", "assessed_in_fiscal_year"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_goal_progress_goal_year", table_name="company_goal_progress")
    op.drop_table("company_goal_progress")
    op.drop_index("ix_company_goals_company_year", table_name="company_goals")
    op.drop_table("company_goals")
