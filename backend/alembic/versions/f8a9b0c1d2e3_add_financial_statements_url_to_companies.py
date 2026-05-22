"""add_financial_statements_url_to_companies

Revision ID: f8a9b0c1d2e3
Revises: e6f7g8h9i0j1
Create Date: 2026-05-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f8a9b0c1d2e3'
down_revision: Union[str, None] = 'e6f7g8h9i0j1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('companies', sa.Column('financial_statements_url', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('companies', 'financial_statements_url')
