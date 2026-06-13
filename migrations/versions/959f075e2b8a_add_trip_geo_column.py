"""add trip geo column

Revision ID: 959f075e2b8a
Revises: 29823c6a0cd9
Create Date: 2026-06-13 10:58:14.676127

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '959f075e2b8a'
down_revision: Union[str, Sequence[str], None] = '29823c6a0cd9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("trips", sa.Column("geo", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("trips", "geo")
