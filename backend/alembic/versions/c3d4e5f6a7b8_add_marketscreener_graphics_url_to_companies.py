"""add_marketscreener_graphics_url_to_companies

Revision ID: c3d4e5f6a7b8
Revises: b2ef5543a91e
Create Date: 2026-05-08 15:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2ef5543a91e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('companies', sa.Column('marketscreener_graphics_url', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('companies', 'marketscreener_graphics_url')